"""
Email utility module for GooCampus HR Portal.
Handles sending emails via Resend API with proper formatting and branding.
"""

import os
import logging
from typing import List, Optional

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Default sender
DEFAULT_SENDER = "GooCampus HR <info@goocampus.in>"

# GooCampus Branding Colors
BRAND_NAVY = "#1e3a5f"
BRAND_ORANGE = "#f97316"


def _get_resend_client():
    """
    Initialise and return the Resend module with the API key set.
    Returns None if the key is missing.
    """
    api_key = os.getenv('RESEND_API_KEY')
    if not api_key:
        logger.warning(
            "RESEND_API_KEY environment variable not set. "
            "Email sending is disabled."
        )
        return None

    try:
        import resend
        resend.api_key = api_key
        return resend
    except ImportError:
        logger.error("resend package not installed. Run: pip install resend")
        return None


def send_email(
    to_list: List[str],
    subject: str,
    html_body: str,
    from_address: str = DEFAULT_SENDER,
    cc_list: Optional[List[str]] = None,
    attachments: Optional[List[dict]] = None
) -> bool:
    """
    Send an HTML email to a list of recipients via Resend API.

    Args:
        to_list: List of recipient email addresses.
        subject: Email subject line.
        html_body: HTML formatted email body.
        from_address: Sender address (default: GooCampus HR <info@goocampus.in>).
        cc_list: Optional list of CC recipient email addresses.

    Returns:
        True if email was sent successfully, False otherwise.
    """
    resend = _get_resend_client()
    if resend is None:
        logger.warning(
            f"Skipping email send: Resend not configured. "
            f"Recipients: {to_list}"
        )
        return False

    if not to_list:
        logger.error("Cannot send email: recipient list is empty")
        return False

    import time
    params = {
        "from": from_address,
        "to": to_list,
        "subject": subject,
        "html": html_body,
    }
    if cc_list:
        params["cc"] = cc_list
    if attachments:
        # Resend attachments: [{filename, content}] where content is base64 (str)
        # or raw bytes. Callers pass base64 strings (e.g. an .ics calendar invite).
        params["attachments"] = attachments

    # Resend caps sending at 2 requests/second, so a fast batch loop loses the
    # overflow to HTTP 429. Back off and retry on rate-limit errors so no email
    # is dropped just because it landed in a busy moment.
    last_err = None
    for attempt in range(4):
        try:
            result = resend.Emails.send(params)
            logger.info(
                f"Email sent successfully via Resend to {len(to_list)} recipient(s). "
                f"Subject: {subject}, ID: {result.get('id', 'N/A')}"
            )
            return True
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if attempt < 3 and ('too many requests' in msg or 'rate limit' in msg or '429' in msg):
                time.sleep(0.7 * (attempt + 1))
                continue
            break

    logger.error(f"Failed to send email via Resend: {str(last_err)}")
    return False


# ---------------------------------------------------------------------------
# Branded HTML helpers
# ---------------------------------------------------------------------------

def _get_email_header_html() -> str:
    """Generate GooCampus branded email header HTML."""
    return f"""
    <div style="background-color: {BRAND_NAVY}; padding: 20px; text-align: center; margin: 0;">
        <h1 style="color: white; margin: 0; font-family: Arial, sans-serif; font-size: 28px;">
            GooCampus HR Portal
        </h1>
        <p style="color: #e0e0e0; margin: 5px 0 0 0; font-family: Arial, sans-serif; font-size: 12px;">
            Human Resources Management System
        </p>
    </div>
    """


def _get_email_footer_html() -> str:
    """Generate GooCampus branded email footer HTML."""
    return f"""
    <div style="background-color: #f5f5f5; padding: 15px; text-align: center; margin-top: 30px; border-top: 3px solid {BRAND_ORANGE};">
        <p style="color: #666; font-family: Arial, sans-serif; font-size: 12px; margin: 0;">
            GooCampus HR Portal | Human Resources Management
        </p>
        <p style="color: #999; font-family: Arial, sans-serif; font-size: 11px; margin: 5px 0 0 0;">
            This is an automated message. Please do not reply to this email.
        </p>
    </div>
    """


# ---------------------------------------------------------------------------
# Branded email builder (GooCampus logo + navy/orange) — used by client
# registration, onboarding and welcome-call notifications.
# ---------------------------------------------------------------------------

BRAND_LOGO_URL = "https://goocampus.org/static/logo-white.png"
PORTAL_URL = "https://goocampus.org"


def render_branded_email(heading: str, inner_html: str, preheader: str = "") -> str:
    """Wrap inner HTML in a polished, email-client-safe GooCampus layout:
    navy header with the logo, an orange accent bar, a white body card and a
    footer. Use with the brand_* helpers below to build the body."""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#eef2f7;">
<span style="display:none;max-height:0;overflow:hidden;opacity:0;color:#eef2f7;">{preheader}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef2f7;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 2px 10px rgba(15,27,51,.08);font-family:Arial,Helvetica,sans-serif;">
  <tr><td style="background:{BRAND_NAVY};padding:22px 28px;text-align:center;">
    <img src="{BRAND_LOGO_URL}" alt="GooCampus" width="80" height="68" style="width:80px;height:68px;display:inline-block;border:0;">
  </td></tr>
  <tr><td style="height:4px;background:{BRAND_ORANGE};font-size:0;line-height:0;">&nbsp;</td></tr>
  <tr><td style="padding:28px 30px 6px;">
    <h1 style="margin:0;color:{BRAND_NAVY};font-size:20px;line-height:1.3;">{heading}</h1>
  </td></tr>
  <tr><td style="padding:6px 30px 28px;color:#334155;font-size:15px;line-height:1.6;">
    {inner_html}
  </td></tr>
  <tr><td style="background:#f8fafc;border-top:1px solid #e5e7eb;padding:18px 30px;text-align:center;color:#94a3b8;font-size:12px;line-height:1.6;">
    <strong style="color:#64748b;">GooCampus Edu Solutions</strong><br>
    Automated notification from the GooCampus portal.
  </td></tr>
</table>
</td></tr></table></body></html>"""


def brand_detail_rows(pairs) -> str:
    """pairs: list of (label, value). Renders a clean two-column details table."""
    cells = ""
    for k, v in pairs:
        cells += (
            f'<tr><td style="padding:7px 0;color:#64748b;font-size:13px;width:170px;'
            f'vertical-align:top;border-bottom:1px solid #f1f5f9;">{k}</td>'
            f'<td style="padding:7px 0 7px 10px;color:#0f172a;font-size:14px;font-weight:600;'
            f'border-bottom:1px solid #f1f5f9;">{v if (v is not None and v != "") else "&mdash;"}</td></tr>'
        )
    return f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin:8px 0 4px;">{cells}</table>'


def brand_photo_block(url: str, name: str = "") -> str:
    """Round client-photo avatar, centred. Empty string if no photo URL."""
    if not url:
        return ""
    return (
        f'<div style="text-align:center;margin:2px 0 18px;">'
        f'<img src="{url}" alt="{name}" width="104" height="104" '
        f'style="width:104px;height:104px;border-radius:50%;object-fit:cover;border:3px solid {BRAND_ORANGE};">'
        f'</div>'
    )


def brand_button(label: str, url: str) -> str:
    return (
        f'<div style="margin:22px 0 4px;text-align:center;">'
        f'<a href="{url}" style="background:{BRAND_ORANGE};color:#ffffff;text-decoration:none;'
        f'font-weight:700;font-size:14px;padding:12px 26px;border-radius:8px;display:inline-block;">{label}</a>'
        f'</div>'
    )


def brand_callout(text: str, color: str = "#EFF6FF", border: str = "#BFDBFE", tcolor: str = "#1E3A5F") -> str:
    return (
        f'<div style="background:{color};border:1px solid {border};border-radius:8px;'
        f'padding:12px 16px;margin:10px 0;color:{tcolor};font-size:14px;">{text}</div>'
    )


# ---------------------------------------------------------------------------
# Pre-built email functions
# ---------------------------------------------------------------------------

def send_birthday_reminder(
    birthday_person_name: str,
    birthday_date: str,
    recipient_emails: List[str]
) -> bool:
    """Send a birthday reminder email to team members (1 day before)."""
    if not recipient_emails:
        logger.error("Cannot send birthday reminder: recipient list is empty")
        return False

    subject = f"Tomorrow is {birthday_person_name}'s Birthday!"

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0;">
            {_get_email_header_html()}
            <div style="padding: 30px; background-color: white; margin: 0;">
                <h2 style="color: {BRAND_NAVY}; margin-top: 0;">
                    <span style="color: {BRAND_ORANGE};">&#127881;</span> Birthday Reminder
                </h2>
                <p style="font-size: 16px; margin: 20px 0;">Dear Team,</p>
                <div style="background-color: #f9f9f9; border-left: 4px solid {BRAND_ORANGE}; padding: 15px; margin: 20px 0;">
                    <p style="font-size: 16px; margin: 0;">
                        <strong>{birthday_person_name}</strong> will be celebrating their birthday on
                        <strong>{birthday_date}</strong>!
                    </p>
                </div>
                <p style="font-size: 14px; margin: 20px 0;">
                    Please join us in wishing them a wonderful day filled with joy and happiness.
                    Feel free to reach out and share your birthday wishes!
                </p>
                <div style="text-align: center; margin: 30px 0;">
                    <p style="font-size: 24px; margin: 0;">&#127874; &#127882; &#127880;</p>
                </div>
                <p style="font-size: 14px; margin: 20px 0; color: #666;">
                    Best wishes,<br>
                    <strong style="color: {BRAND_NAVY};">GooCampus HR Team</strong>
                </p>
            </div>
            {_get_email_footer_html()}
        </body>
    </html>
    """

    logger.info(
        f"Sending birthday reminder for {birthday_person_name} "
        f"(Date: {birthday_date}) to {len(recipient_emails)} recipient(s)"
    )
    return send_email(recipient_emails, subject, html_body)


def send_anniversary_reminder(
    employee_name: str,
    years: int,
    anniversary_date: str,
    recipient_emails: List[str]
) -> bool:
    """Send a work anniversary reminder email to team members."""
    if not recipient_emails:
        logger.error("Cannot send anniversary reminder: recipient list is empty")
        return False

    anniversary_text = f"{years} year" if years == 1 else f"{years} years"
    subject = f"{employee_name} - {anniversary_text} Work Anniversary!"

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0;">
            {_get_email_header_html()}
            <div style="padding: 30px; background-color: white; margin: 0;">
                <h2 style="color: {BRAND_NAVY}; margin-top: 0;">
                    <span style="color: {BRAND_ORANGE};">&#11088;</span> Work Anniversary Milestone
                </h2>
                <p style="font-size: 16px; margin: 20px 0;">Dear Team,</p>
                <div style="background-color: #f9f9f9; border-left: 4px solid {BRAND_ORANGE}; padding: 15px; margin: 20px 0;">
                    <p style="font-size: 16px; margin: 0;">
                        We are pleased to celebrate that <strong>{employee_name}</strong> is completing
                        <strong>{anniversary_text}</strong> of service at GooCampus on
                        <strong>{anniversary_date}</strong>!
                    </p>
                </div>
                <p style="font-size: 14px; margin: 20px 0;">
                    {employee_name} has been a valuable member of our team, contributing to our success
                    and growth. Their dedication and hard work have not gone unnoticed.
                </p>
                <p style="font-size: 14px; margin: 20px 0;">
                    Let's take this opportunity to express our gratitude for their commitment and wish them
                    continued success in their career journey with us!
                </p>
                <div style="text-align: center; margin: 30px 0;">
                    <p style="font-size: 24px; margin: 0;">&#127881; &#127775; &#128079;</p>
                </div>
                <p style="font-size: 14px; margin: 20px 0; color: #666;">
                    With appreciation,<br>
                    <strong style="color: {BRAND_NAVY};">GooCampus HR Team</strong>
                </p>
            </div>
            {_get_email_footer_html()}
        </body>
    </html>
    """

    logger.info(
        f"Sending anniversary reminder for {employee_name} ({anniversary_text}) "
        f"to {len(recipient_emails)} recipient(s)"
    )
    return send_email(recipient_emails, subject, html_body)


def send_announcement_email(
    title: str,
    message: str,
    posted_by_name: str,
    recipient_emails: List[str]
) -> bool:
    """Send an announcement email to all recipients."""
    if not recipient_emails:
        logger.error("Cannot send announcement: recipient list is empty")
        return False

    subject = f"Announcement: {title}"
    formatted_message = message.replace('\n', '<br>')

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0;">
            {_get_email_header_html()}
            <div style="padding: 30px; background-color: white; margin: 0;">
                <h2 style="color: {BRAND_NAVY}; margin-top: 0;">
                    <span style="color: {BRAND_ORANGE};">&#128226;</span> {title}
                </h2>
                <p style="font-size: 16px; margin: 20px 0;">Dear Team,</p>
                <div style="background-color: #f9f9f9; border-left: 4px solid {BRAND_ORANGE}; padding: 20px; margin: 20px 0;">
                    <p style="font-size: 14px; margin: 0; white-space: pre-wrap; word-wrap: break-word;">
                        {formatted_message}
                    </p>
                </div>
                <p style="font-size: 14px; margin: 20px 0; color: #666;">
                    Best regards,<br>
                    <strong style="color: {BRAND_NAVY};">{posted_by_name}</strong><br>
                    <span style="font-size: 12px;">GooCampus HR Team</span>
                </p>
            </div>
            {_get_email_footer_html()}
        </body>
    </html>
    """

    logger.info(
        f"Sending announcement '{title}' from {posted_by_name} "
        f"to {len(recipient_emails)} recipient(s)"
    )
    return send_email(recipient_emails, subject, html_body)


def send_happy_birthday_email(
    birthday_person_name: str,
    birthday_person_email: str
) -> bool:
    """Send a warm happy birthday email directly to the birthday person."""
    if not birthday_person_email:
        logger.error("Cannot send happy birthday email: no email address")
        return False

    subject = f"Happy Birthday, {birthday_person_name}!"
    first_name = birthday_person_name.split()[0] if birthday_person_name else birthday_person_name

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0;">
            {_get_email_header_html()}
            <div style="padding: 30px; background-color: white; margin: 0;">
                <div style="text-align: center; margin-bottom: 20px;">
                    <p style="font-size: 48px; margin: 0;">&#127874;&#127881;&#127880;</p>
                </div>
                <h2 style="color: {BRAND_NAVY}; text-align: center; margin-top: 0;">
                    Happy Birthday, <span style="color: {BRAND_ORANGE};">{first_name}!</span>
                </h2>
                <p style="font-size: 16px; margin: 20px 0; text-align: center;">
                    Dear <strong>{birthday_person_name}</strong>,
                </p>
                <div style="background: linear-gradient(135deg, #fff5eb, #fef3e6); border-left: 4px solid {BRAND_ORANGE}; padding: 20px; margin: 20px 0; border-radius: 0 8px 8px 0;">
                    <p style="font-size: 15px; margin: 0; line-height: 1.8;">
                        On behalf of the entire <strong style="color: {BRAND_NAVY};">GooCampus</strong> family,
                        we wish you a very happy birthday!
                    </p>
                    <p style="font-size: 15px; margin: 12px 0 0 0; line-height: 1.8;">
                        Your hard work, dedication, and positive energy make our workplace better every day.
                        We are truly grateful to have you as part of our team.
                    </p>
                    <p style="font-size: 15px; margin: 12px 0 0 0; line-height: 1.8;">
                        May this special day bring you endless joy, good health, and all the happiness
                        you deserve. Here's to another wonderful year ahead!
                    </p>
                </div>
                <div style="text-align: center; margin: 30px 0;">
                    <p style="font-size: 36px; margin: 0;">&#127882; &#127873; &#127775; &#127880; &#127874;</p>
                </div>
                <p style="font-size: 14px; margin: 20px 0; color: #666; text-align: center;">
                    With warm wishes from all of us,<br>
                    <strong style="color: {BRAND_NAVY};">The GooCampus Team</strong>
                </p>
            </div>
            {_get_email_footer_html()}
        </body>
    </html>
    """

    logger.info(
        f"Sending happy birthday email to {birthday_person_name} "
        f"({birthday_person_email})"
    )
    return send_email([birthday_person_email], subject, html_body)


def send_leave_status_email(
    employee_name: str,
    employee_email: str,
    leave_type: str,
    leave_date: str,
    status: str,
    actioned_by: str
) -> bool:
    """Send a leave approved/rejected email to the employee."""
    if not employee_email:
        logger.error("Cannot send leave status email: no email address")
        return False

    is_approved = status.lower() == 'approved'
    status_label = "Approved" if is_approved else "Rejected"
    status_color = "#22c55e" if is_approved else "#ef4444"
    status_icon = "&#9989;" if is_approved else "&#10060;"
    first_name = employee_name.split()[0] if employee_name else employee_name

    subject = f"Leave {status_label} — {leave_type} on {leave_date}"

    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0;">
            {_get_email_header_html()}
            <div style="padding: 30px; background-color: white; margin: 0;">
                <h2 style="color: {BRAND_NAVY}; margin-top: 0;">
                    {status_icon} Leave {status_label}
                </h2>
                <p style="font-size: 16px; margin: 20px 0;">Dear {first_name},</p>
                <div style="background-color: #f9f9f9; border-left: 4px solid {status_color}; padding: 15px; margin: 20px 0;">
                    <p style="font-size: 15px; margin: 0;">
                        Your <strong>{leave_type}</strong> leave on
                        <strong>{leave_date}</strong> has been
                        <strong style="color: {status_color};">{status_label.lower()}</strong>
                        by <strong>{actioned_by}</strong>.
                    </p>
                </div>
                <p style="font-size: 14px; margin: 20px 0; color: #666;">
                    You can view your leave history on the HR Portal.
                </p>
                <p style="font-size: 14px; margin: 20px 0; color: #666;">
                    Regards,<br>
                    <strong style="color: {BRAND_NAVY};">GooCampus HR Team</strong>
                </p>
            </div>
            {_get_email_footer_html()}
        </body>
    </html>
    """

    logger.info(
        f"Sending leave {status_label.lower()} email to {employee_name} "
        f"({employee_email})"
    )
    return send_email([employee_email], subject, html_body)


if __name__ == "__main__":
    logger.info("Email utilities module loaded successfully (Resend)")
