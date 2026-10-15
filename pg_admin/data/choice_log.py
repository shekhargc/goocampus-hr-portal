"""Audit trail for GooCampus-team choice lists (owner='team').

Every change to a team-prepared list is recorded — by the team (build / rebuild / add /
move / reorder / remove / delete list / email) AND by the doctor (add / move / reorder /
remove / acknowledge) — with who, what college, which round and when. The founder wants
to know exactly what a doctor changed in a list the team sent, so GooCampus is never
held responsible for a list the doctor altered. (founder 2026-10-15)

Also holds the short "suggestion only — your final decision" note shown on the
dashboard, the PDF and the email, and the doctor's acknowledgement of it.
"""
import json
import logging

DISCLAIMER = ("This list is a suggestion prepared by the GooCampus team from last year's cut-offs "
              "and your preferences. Please verify every choice before you lock your choices with "
              "the counselling authority — the final decision, and responsibility for it, is yours.")
DISCLAIMER_VERSION = '2026-10-15'

_READY = False


def ensure_choice_log(conn, force=False):
    global _READY
    if _READY and not force:
        return
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_choice_edit_log (
            id SERIAL PRIMARY KEY,
            set_id INTEGER NOT NULL,
            user_id INTEGER,                    -- the doctor who owns the list
            actor TEXT DEFAULT '',              -- 'team' | 'client'
            actor_name TEXT DEFAULT '',
            action TEXT DEFAULT '',             -- build|rebuild|add|move|reorder|remove|delete_list|email|acknowledge
            round INTEGER,
            institute TEXT DEFAULT '',
            course TEXT DEFAULT '',
            quota TEXT DEFAULT '',
            category TEXT DEFAULT '',
            from_pos INTEGER,
            to_pos INTEGER,
            detail TEXT DEFAULT '',             -- JSON / free text (e.g. old vs new order)
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_choice_edit_log_set ON pg_choice_edit_log (set_id, id)")
        conn.execute("ALTER TABLE pg_choice_sets ADD COLUMN IF NOT EXISTS client_ack_at TIMESTAMP")
        conn.execute("ALTER TABLE pg_choice_sets ADD COLUMN IF NOT EXISTS client_ack_version TEXT DEFAULT ''")
        conn.execute("ALTER TABLE pg_choice_sets ADD COLUMN IF NOT EXISTS client_edited_at TIMESTAMP")
        conn.commit()
        _READY = True
    except Exception as e:
        logging.warning("ensure_choice_log: %s", e)
        try: conn.rollback()
        except Exception: pass


def ensure_choice_log_boot():
    """Boot-time variant (own connection) so the table exists before the first edit."""
    from db import get_db
    conn = get_db()
    try:
        ensure_choice_log(conn, force=True)
    finally:
        conn.close()


def log(conn, set_id, action, actor, actor_name='', item=None, rnd=None,
        from_pos=None, to_pos=None, detail='', user_id=None):
    """Append one entry. Never raises — a logging problem must not block the edit
    (but it runs in the caller's transaction, so it commits with the edit)."""
    try:
        ensure_choice_log(conn)
        it = item or {}
        if user_id is None:
            r = conn.execute("SELECT user_id FROM pg_choice_sets WHERE id = ?", [set_id]).fetchone()
            user_id = r['user_id'] if r else None
        if not isinstance(detail, str):
            detail = json.dumps(detail, ensure_ascii=False)
        conn.execute(
            "INSERT INTO pg_choice_edit_log (set_id, user_id, actor, actor_name, action, round, "
            "institute, course, quota, category, from_pos, to_pos, detail) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [set_id, user_id, actor, actor_name or '', action,
             rnd if rnd is not None else it.get('round'),
             it.get('institute') or '', it.get('course') or '', it.get('quota') or '',
             it.get('category') or '', from_pos, to_pos, detail or ''])
    except Exception as e:
        logging.warning("choice_log.log: %s", e)


def is_team_list(conn, set_id):
    r = conn.execute("SELECT COALESCE(owner,'client') AS o FROM pg_choice_sets WHERE id = ?",
                     [set_id]).fetchone()
    return bool(r and r['o'] == 'team')


def round_order(conn, set_id, rnd):
    return [dict(r) for r in conn.execute(
        "SELECT id, position, institute, course FROM pg_choice_items WHERE set_id = ? AND round = ? "
        "ORDER BY position, id", [set_id, rnd]).fetchall()]


def order_detail(before, after):
    """Compact old→new order for a reorder entry (names only, 1-based)."""
    name = lambda r: f"{r.get('institute') or ''} — {r.get('course') or ''}".strip(' —')
    return {'before': [name(r) for r in before], 'after': [name(r) for r in after]}


_ACTION_LABEL = {'build': 'Built the list', 'rebuild': 'Rebuilt the list', 'add': 'Added',
                 'move': 'Moved', 'reorder': 'Reordered', 'remove': 'Removed',
                 'delete_list': 'Deleted the list', 'email': 'Emailed the PDF',
                 'acknowledge': 'Confirmed they read the note'}


def history(conn, set_id, limit=300):
    ensure_choice_log(conn)
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM pg_choice_edit_log WHERE set_id = ? ORDER BY id DESC LIMIT ?",
        [set_id, limit]).fetchall()]
    for r in rows:
        r['created_at'] = str(r['created_at'])[:19] if r.get('created_at') else ''
        r['action_label'] = _ACTION_LABEL.get(r.get('action'), r.get('action'))
        r['who'] = ('GooCampus team' if r.get('actor') == 'team' else 'Doctor') + \
                   (f" ({r['actor_name']})" if r.get('actor_name') else '')
        try:
            r['detail_json'] = json.loads(r['detail']) if (r.get('detail') or '').startswith(('{', '[')) else None
        except Exception:
            r['detail_json'] = None
    return rows


def ack_state(s):
    """For a set dict: does the doctor still need to confirm the note?"""
    if (s.get('owner') or 'client') != 'team':
        return False
    ack, team = s.get('client_ack_at'), s.get('team_edited_at')
    if not ack:
        return True
    return bool(team and str(team) > str(ack))
