"""SMS OTP sender — TagSolutions DLT HTTP API (backup channel to the Infobip WhatsApp
OTP). ONE OTP is generated, then pushed over BOTH WhatsApp and SMS so a client whose
number isn't on WhatsApp still receives the same code by SMS and can log in.
(founder 2026-09-28)

All config is read from environment variables (no secrets in code). Set on Render:
  SMS_API_USERNAME     e.g. MBBSMD
  SMS_API_KEY          the vendor API key (secret)
  SMS_SENDER           DLT header / sender ID   e.g. GCEDUS
  SMS_ROUTE            the vendor route name for transactional/OTP SMS
  SMS_DLT_TEMPLATE_ID  the DLT-approved content-template id for the OTP message
  SMS_OTP_TEMPLATE     the EXACT approved template text; the literal {#var#} (or {otp})
                       is replaced with the 6-digit code. Must match the DLT template.
  SMS_API_URL          (optional) override the endpoint; defaults to the TagSolutions URL
"""
import os
import logging

_DEFAULT_URL = 'https://tagsolutions.in/sms-panel/api/http/index.php'


def is_configured():
    """True only when every required SMS setting is present (cheap, no network)."""
    return all(os.environ.get(k) for k in (
        'SMS_API_USERNAME', 'SMS_API_KEY', 'SMS_SENDER',
        'SMS_ROUTE', 'SMS_DLT_TEMPLATE_ID', 'SMS_OTP_TEMPLATE',
    ))


def send_sms_otp(mobile10, otp):
    """Send the OTP by SMS. Returns (ok: bool, error: str|None). Never raises.
    `mobile10` is the bare 10-digit Indian mobile."""
    if not is_configured():
        return False, 'SMS not configured'
    username = os.environ.get('SMS_API_USERNAME', '')
    apikey = os.environ.get('SMS_API_KEY', '')
    sender = os.environ.get('SMS_SENDER', '')
    route = os.environ.get('SMS_ROUTE', '')
    template_id = os.environ.get('SMS_DLT_TEMPLATE_ID', '')
    template = os.environ.get('SMS_OTP_TEMPLATE', '')
    url = os.environ.get('SMS_API_URL', _DEFAULT_URL)

    # Fill the DLT template's OTP variable. Support both the DLT {#var#} marker and a
    # friendly {otp} placeholder so whichever the env value uses works.
    message = template.replace('{#var#}', str(otp)).replace('{otp}', str(otp))
    mobile = ''.join(ch for ch in str(mobile10 or '') if ch.isdigit())[-10:]
    if len(mobile) != 10:
        return False, 'invalid mobile'
    try:
        import requests
        params = {
            'username': username, 'apikey': apikey, 'apirequest': 'Text',
            'sender': sender, 'mobile': mobile, 'message': message,
            'route': route, 'TemplateID': template_id, 'format': 'JSON',
        }
        resp = requests.get(url, params=params, timeout=15)
        body = (resp.text or '')[:400]
        logging.info("SMS OTP to %s: HTTP %s body=%s", mobile, resp.status_code, body)
        if resp.status_code >= 400:
            return False, f'SMS provider HTTP {resp.status_code}'
        # TagSolutions returns JSON; a 2xx means accepted for delivery. If the body
        # clearly signals an error, surface it (kept lenient so a format change can't
        # silently drop the fallback).
        low = body.lower()
        if any(w in low for w in ('"error"', 'invalid', 'failed', 'insufficient', 'blocked')):
            return False, f'SMS provider rejected: {body}'
        return True, None
    except Exception as e:
        logging.error("send_sms_otp: %s", e)
        return False, str(e)
