"""Admin tool: clean up messy free-text doctor states → the canonical state list.

goocampus.in's early signup took the state as free text, so pg_users.state has variants
and typos ("karnataka", "Karnatka", "Tamilnadu", "Orissa", "Panipat haryana"…). This tool
AUDITS every distinct non-canonical value, proposes a best-guess canonical mapping in a
dropdown, and — only on the admin's confirm (Apply) — rewrites those rows. Nothing is
auto-changed; the admin reviews each mapping first. (founder 2026-10-06)

Writes pg_users.state (and any pg_doctor_states rows holding the same old value, so the
locked counselling home stays in step). Values left as "— leave as-is —" are untouched.
"""
import re
import difflib
import logging
from flask import render_template, request, redirect, url_for, flash
from db import get_db
from core.users import get_user
from core.auth import login_required
from pg_admin.routes.users_admin import _canonical_states


def _admin():
    u = get_user()
    return u if (u and u.get('is_admin')) else None


def _norm(s):
    return re.sub(r'[^a-z0-9]+', ' ', str(s or '').lower()).strip()


# Common NEET-PG state aliases → canonical (normalised key → canonical name).
_ALIASES = {
    'orissa': 'Odisha',
    'pondicherry': 'Puducherry', 'pondichery': 'Puducherry', 'pondy': 'Puducherry',
    'tamilnadu': 'Tamil Nadu', 'tamil nadu': 'Tamil Nadu',
    'jammu kashmir': 'Jammu and Kashmir', 'j k': 'Jammu and Kashmir',
    'jk': 'Jammu and Kashmir', 'jammu': 'Jammu and Kashmir',
    'new delhi': 'Delhi', 'delhi ncr': 'Delhi', 'ncr': 'Delhi',
    'uttaranchal': 'Uttarakhand',
    'chattisgarh': 'Chhattisgarh', 'chhatisgarh': 'Chhattisgarh',
    'telengana': 'Telangana', 'telagana': 'Telangana',
    'andaman': 'Andaman and Nicobar Islands',
    'andaman nicobar': 'Andaman and Nicobar Islands',
    'andaman and nicobar': 'Andaman and Nicobar Islands',
    'dadra and nagar haveli': 'Dadra and Nagar Haveli and Daman and Diu',
    'daman and diu': 'Dadra and Nagar Haveli and Daman and Diu',
    'daman': 'Dadra and Nagar Haveli and Daman and Diu',
}


def _guess(raw, canon):
    """Best-guess canonical state for a raw value, or '' if none is confident."""
    n = _norm(raw)
    if not n:
        return ''
    by_norm = {_norm(c): c for c in canon}
    if n in by_norm:
        return by_norm[n]                     # same state, just case/punctuation
    if n in _ALIASES:
        return _ALIASES[n]
    # a canonical state name sits inside the value, e.g. "panipat haryana" → Haryana
    for c in canon:
        cn = _norm(c)
        if cn and (f' {cn} ' in f' {n} ' or n == cn):
            return c
    # typo tolerance
    m = difflib.get_close_matches(n, list(by_norm.keys()), n=1, cutoff=0.84)
    if m:
        return by_norm[m[0]]
    return ''


def _audit(conn, canon):
    canon_set = set(canon)
    rows = [dict(r) for r in conn.execute(
        "SELECT COALESCE(state,'') AS state, COUNT(*) AS n FROM pg_users "
        "WHERE COALESCE(state,'') <> '' GROUP BY state ORDER BY n DESC").fetchall()]
    dirty, clean_n = [], 0
    for r in rows:
        if r['state'] in canon_set:
            clean_n += r['n']
            continue
        dirty.append({'raw': r['state'], 'count': r['n'], 'guess': _guess(r['state'], canon)})
    # confident first (has a guess), then by count
    dirty.sort(key=lambda d: (d['guess'] == '', -d['count']))
    return dirty, clean_n


@login_required
def pg_states_cleanup():
    admin = _admin()
    if not admin:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        canon = _canonical_states()
        if request.method == 'POST':
            updated = rows_doctors = rows_home = 0
            # Each row posted as raw_<i> (old value) + to_<i> (chosen canonical, or blank).
            for key in list(request.form.keys()):
                if not key.startswith('raw_'):
                    continue
                idx = key[4:]
                raw = request.form.get(f'raw_{idx}') or ''
                to = (request.form.get(f'to_{idx}') or '').strip()
                if not raw or not to or to == raw or to not in canon:
                    continue
                cur = conn.execute("UPDATE pg_users SET state = ? WHERE state = ?", (to, raw))
                rows_doctors += (cur.rowcount or 0) if hasattr(cur, 'rowcount') else 0
                conn.execute("UPDATE pg_doctor_states SET state = ? WHERE state = ?", (to, raw))
                updated += 1
            conn.commit()
            flash(f'Corrected {updated} state value(s) across {rows_doctors} doctor record(s). '
                  f'Home counselling states synced where they matched. '
                  f'Run "Home-state backfill" next if any home states still need locking.',
                  'success')
            return redirect(url_for('pg_states_cleanup'))

        dirty, clean_n = _audit(conn, canon)
        return render_template('pg_admin/diag_states.html', user=admin,
                               active_section='goocampus_in', canon=canon,
                               dirty=dirty, clean_n=clean_n)
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("pg_states_cleanup: %s", e)
        flash(f'State cleanup error: {e}', 'error')
        return redirect(url_for('pg_users_admin'))
    finally:
        try: conn.close()
        except Exception: pass
