"""WhatsApp template register (founder 2026-11-17: "keep a place in the portal where all the WhatsApp templates
are approved and being used for what purpose with all its approved details").

Lives on the existing WhatsApp → Templates page (/whatsapp/templates, table wa_templates). Adds descriptive
columns — purpose, used_in, trigger_text, variables, approved_on, notes — an admin Edit-details drawer and an
"Add approved template" form (Infobip template sync 403s with our key, so approved templates are recorded here by
hand). The templates the portal sends automatically are pre-filled from KNOWN below; a team edit is never
overwritten (seed only fills empty fields).
"""
import logging

from db import get_db

logger = logging.getLogger(__name__)

DEFAULT_SENDER = '15558246314'
DETAIL_COLS = ('purpose', 'used_in', 'trigger_text', 'variables', 'approved_on', 'notes')
_READY = {'done': False}

KNOWN = [
    {'name': 'welcometogoocampus', 'language': 'en', 'category': 'UTILITY', 'status': 'APPROVED',
     'infobip_template_id': '1413956730516058', 'sender': DEFAULT_SENDER,
     'body_text': 'Hi Dr. {{1}}, thank you for registering on goocampus.in. Your NEET PG dashboard is ready. '
                  'Counselling news, deadlines, results and documents for {{2}} and MCC will appear there as soon '
                  'as they are released. Log in any time with your mobile number and OTP.',
     'buttons': 'URL button: Click Here',
     'purpose': 'Welcome a new goocampus.in doctor once their profile has a name and state.',
     'used_in': 'goocampus.in Admin → Registered Doctors → 💬 WhatsApp (message 1, sign-up switch)',
     'trigger_text': 'Automatic, every 10 min: anyone registering for the first time — free OR paid by invitation — '
                     'once they have added name + state (within 7 days of sign-up, after the switch-on). Once per '
                     'doctor. Team members only if Team is ticked in "Who gets it".',
     'variables': '{{1}} = doctor name (without "Dr.") · {{2}} = home state',
     'approved_on': '2026-11-17'},
    {'name': 'gc_profile_incomplete_v2', 'language': 'en', 'category': 'UTILITY', 'status': 'APPROVED',
     'infobip_template_id': '1064689406591742', 'sender': DEFAULT_SENDER,
     'body_text': 'Dear Doctor,\n\nThank you for registering with GooCampus.\n\nYour GooCampus.in dashboard is ready and '
                  'your mobile number is verified.\n\nPlease complete your profile by adding your name and state to '
                  'access the complete dashboard.\n\nIt takes less than a minute.',
     'buttons': 'URL button: Click Here',
     'purpose': 'Remind a new doctor (free or invited) to add name + state so the full dashboard opens.',
     'used_in': 'goocampus.in Admin → Registered Doctors → 💬 WhatsApp (message 2, sign-up switch)',
     'trigger_text': 'Automatic: any new doctor (free or invited) still missing name or state 15 minutes after '
                     'sign-up, again at 24 hours and at 72 hours (max 3). Team members only if Team is ticked.',
     'variables': 'none',
     'approved_on': '2026-11-18',
     'notes': 'Replaces gc_profile_incomplete (id 1952329065742254) — adds "Dear Doctor," and the thank-you line.'},
    {'name': 'gc_profile_incomplete', 'language': 'en', 'category': 'UTILITY', 'status': 'APPROVED',
     'infobip_template_id': '1952329065742254', 'sender': DEFAULT_SENDER,
     'body_text': 'Your GooCampus.in dashboard is ready and your mobile number is verified. Please complete your '
                  'profile by adding your name and state to access the complete dashboard. It takes less than a minute.',
     'buttons': 'URL button: Click Here',
     'purpose': 'Old version of the profile reminder (no greeting). Not used any more.',
     'used_in': 'Nothing — replaced by gc_profile_incomplete_v2 on 2026-11-18',
     'trigger_text': 'Not sent any more.',
     'variables': 'none',
     'approved_on': '2026-11-17',
     'notes': 'Retired 2026-11-18: replaced by gc_profile_incomplete_v2 (adds "Dear Doctor,").'},
    {'name': 'gc_enquiry_account', 'language': 'en', 'category': 'UTILITY', 'status': 'APPROVED',
     'infobip_template_id': '1118950867607827', 'sender': DEFAULT_SENDER,
     'body_text': 'Hi Dr. {{1}}, thank you for your enquiry with GooCampus. Our team will call you shortly.\n\n'
                  'Log in into your dashboard to get daily counselling updates.',
     'buttons': 'URL button: Click Here',
     'purpose': 'Thank a website enquirer, promise a call back and point them to the free dashboard.',
     'used_in': 'goocampus.in Admin → Registered Doctors → 💬 WhatsApp (message 3, enquiry switch)',
     'trigger_text': 'Automatic, every 10 min: new goocampus.in enquiries (Sales → Inquiries) and Management / NRI '
                     'call-backs made after the switch-on. Once per mobile number, ever.',
     'variables': '{{1}} = enquirer name (without "Dr.")',
     'approved_on': '2026-11-17'},
    {'name': 'gc_daily_account_update', 'language': 'en', 'category': 'UTILITY', 'status': 'APPROVED',
     'infobip_template_id': '39934717086143575', 'sender': DEFAULT_SENDER,
     'body_text': 'Dr. {{1}}, {{2}} new update(s) for {{3}} were posted on your personalised goocampus.in dashboard '
                  'today.\n\nLatest: {{4}}\n\nLog in to see the dates, documents and what you need to do next.',
     'buttons': 'URL button: Click Here · Quick reply: Stop updates',
     'purpose': 'News alert: tell a doctor how many new counselling updates for their MCC / state were just posted.',
     'used_in': 'goocampus.in Admin → Registered Doctors → 💬 WhatsApp (message 4, daily switch)',
     'trigger_text': 'Automatic, WITH the news email: when "Send combined email now" (or a single update\'s email send) '
                     'is pressed, one message to registered doctors AND team members (name + mobile; untick Team in '
                     '"Who gets it" to leave the team out) whose MCC or state is in those updates — max 3 a day. Not '
                     'for "Send to team" tests. "Stop updates" / STOP → never again.',
     'variables': '{{1}} = doctor name · {{2}} = number of updates today · {{3}} = "MCC & <state>" · '
                  '{{4}} = latest update heading',
     'approved_on': '2026-11-17'},
]
# Texts this module seeded earlier that were later corrected (founder 2026-11-17 night). A row still holding the
# OLD seeded text (i.e. never edited by the team) is moved to the new KNOWN text; any team edit is left alone.
OLD_SEED = {          # name → {column: [old seeded texts]} — any of them is replaced by the KNOWN text
    'welcometogoocampus': {'trigger_text': [
        'Automatic, every 10 min: anyone registering for the first time — free OR paid by invitation — once they have '
        'added name + state (within 7 days of sign-up, after the switch-on). Once per doctor. Not team / Counselling Desk.',
        'Automatic, every 10 min: doctors who signed up after the switch-on and have added name + state (within 7 '
        'days). Once per doctor. Not team / Counselling Desk.']},
    'gc_profile_incomplete_v2': {'trigger_text': [
        'Automatic: any new doctor (free or invited) still missing name or state 15 minutes after sign-up, again at '
        '24 hours and at 72 hours (max 3). Team / Desk accounts never get it.',
        'Automatic: any new doctor (free or invited) still missing name or state 15 minutes after sign-up, and '
        'again at 24 hours (max 2). Team / Desk accounts never get it.']},
    'gc_daily_account_update': {'purpose': [
        'Evening digest: tell a doctor how many counselling updates for their MCC / state were posted today.'],
        'trigger_text': [
        'Automatic, after every news publish batch (once nothing new was published for 15 minutes): one message per '
        'batch to registered doctors AND team members (name + mobile; untick Team in "Who gets it" to leave the team '
        'out) whose MCC or state is in it — 2–3 batches a day = 2–3 messages, max 3 a day. "Stop updates" / STOP → '
        'never again.',
        'Automatic, after every news publish batch (once nothing new was published for 15 minutes): one message per '
        'batch to registered doctors (name + mobile, not team / Desk) whose MCC or state is in it — 2–3 batches a day = '
        '2–3 messages, max 3 a day. "Stop updates" / STOP → never again.',
        'Automatic at 8:00 pm IST, at most once a day, to all registered doctors (name + mobile, not team / Desk) '
        'whose MCC or state news was posted that day. No news → no message. "Stop updates" / STOP → never again.']},
    'gc_profile_incomplete': {          # retired 2026-11-18 → v2
        'purpose': ['Remind a new FREE doctor to add name + state so the full dashboard opens.',
                    'Remind a new doctor (free or invited) to add name + state so the full dashboard opens.'],
        'used_in': ['goocampus.in Admin → Registered Doctors → 💬 WhatsApp (message 2, sign-up switch)'],
        'trigger_text': [
            'Automatic: free doctors still missing name or state 1 hour after sign-up, and again at 24 hours (max 2). '
            'Paid / invited / team / Desk accounts never get it.',
            'Automatic: any new doctor (free or invited) still missing name or state 15 minutes after sign-up, and '
            'again at 24 hours (max 2). Team / Desk accounts never get it.']},
}
# Purposes for older templates (filled only where empty).
KNOWN_PURPOSE = {
    'communitylink2': ('Invite NEET PG doctors to the GooCampus NEET PG WhatsApp community.',
                       'WhatsApp → Quick Send / Campaigns (sent by hand)', 'Manual', '{{1}} = name'),
    'joincommunity': ('Tell doctors a state\'s cut-off data is live, with the link.',
                      'WhatsApp → Quick Send / Campaigns (sent by hand)', 'Manual',
                      '{{1}} = name · {{2}} = state / exam · {{3}} = link'),
    'ug_community_link': ('Invite UG students & parents to the GooCampus UG community (approved on the OTHER sender '
                          '15558640596 — must be sent from it).', 'WhatsApp → Quick Send (sent by hand)', 'Manual',
                          '{{1}} = "Students & Parents" (fixed greeting)'),
}


def prepare(conn):
    """Add the register columns (once per process) and fill known details where empty. Never overwrites edits."""
    if _READY['done']:
        return
    _READY['done'] = True
    try:
        conn.execute("SET LOCAL lock_timeout = '3s'")
        have = {r['column_name'] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'wa_templates'").fetchall()}
        for c in DETAIL_COLS + ('updated_by', 'updated_at'):
            if c not in have:
                conn.execute(f"ALTER TABLE wa_templates ADD COLUMN IF NOT EXISTS {c} "
                             f"{'TIMESTAMP' if c == 'updated_at' else 'TEXT'}")
        conn.commit()
        for t in KNOWN:
            row = conn.execute("SELECT * FROM wa_templates WHERE name = ? ORDER BY id LIMIT 1", (t['name'],)).fetchone()
            if not row:
                cols = list(t.keys())
                conn.execute(f"INSERT INTO wa_templates ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                             [t[c] for c in cols])
            else:
                row = dict(row)
                sets = [(c, t[c]) for c in t if c != 'name' and not (row.get(c) or '').strip()]
                if sets:
                    conn.execute("UPDATE wa_templates SET " + ', '.join(f"{c} = ?" for c, _ in sets) + " WHERE id = ?",
                                 [v for _, v in sets] + [row['id']])
        known = {t['name']: t for t in KNOWN}
        for name, cols in OLD_SEED.items():
            for c, olds in cols.items():
                for old in olds:
                    conn.execute(f"UPDATE wa_templates SET {c} = ? WHERE name = ? AND {c} = ?",
                                 (known[name][c], name, old))
        for name, (purpose, used, trig, var) in KNOWN_PURPOSE.items():
            conn.execute("UPDATE wa_templates SET purpose = COALESCE(NULLIF(purpose,''), ?), "
                         "used_in = COALESCE(NULLIF(used_in,''), ?), trigger_text = COALESCE(NULLIF(trigger_text,''), ?), "
                         "variables = COALESCE(NULLIF(variables,''), ?) WHERE name = ?", (purpose, used, trig, var, name))
        conn.commit()
    except Exception as e:
        logger.warning("wa_registry.prepare: %s", e)
        try: conn.rollback()
        except Exception: pass


EDITABLE = ('name', 'language', 'category', 'status', 'header_text', 'body_text', 'footer_text', 'buttons',
            'infobip_template_id', 'sender') + DETAIL_COLS


def save(form, who, tpl_id=None):
    """Create (tpl_id None) or update one template from the drawer form. Returns (ok, message)."""
    vals = {c: (form.get(c) or '').strip() for c in EDITABLE}
    if not vals['name'] or not vals['body_text']:
        return False, 'Name and the approved message text are required.'
    vals['status'] = (vals['status'] or 'APPROVED').upper()
    vals['language'] = vals['language'] or 'en'
    conn = get_db()
    try:
        prepare(conn)
        if tpl_id:
            conn.execute("UPDATE wa_templates SET " + ', '.join(f"{c} = ?" for c in EDITABLE) +
                         ", updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         [vals[c] for c in EDITABLE] + [who, tpl_id])
        else:
            if conn.execute("SELECT 1 FROM wa_templates WHERE name = ? AND language = ?",
                            (vals['name'], vals['language'])).fetchone():
                return False, 'A template with this name and language is already listed — edit it instead.'
            conn.execute("INSERT INTO wa_templates (" + ', '.join(EDITABLE) + ", updated_by, updated_at) VALUES (" +
                         ', '.join('?' * len(EDITABLE)) + ", ?, CURRENT_TIMESTAMP)", [vals[c] for c in EDITABLE] + [who])
        conn.commit()
        return True, 'Saved.'
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("wa_registry.save: %s", e)
        return False, 'Could not save.'
    finally:
        conn.close()
