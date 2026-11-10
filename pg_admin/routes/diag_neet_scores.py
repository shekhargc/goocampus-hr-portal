"""Admin tool: check doctors' NEET-PG rank + score against the official result sheet (founder 2026-11-10).

AUDIT (read-only): for every registered doctor with an All-India rank, look up the score the
NBEMS master result (pg_neet_result) shows for that rank and sort them into:
  fill      — rank entered, score blank → the result's score can be filled in
  mismatch  — the entered score is not the score for that rank (one of the two is wrong)
  ok        — score matches the rank
  not_found — the rank is not in the result sheet
  score_only— score but no rank (shows the rank band that score falls in; nothing to fill)

APPLY (admin confirm only): writes pg_users.neet_pg_score for the ticked doctors, using the
score the server looks up again for the doctor's CURRENT rank (posted values are never trusted).
"fill" rows are ticked by default; "mismatch" rows are not. Every change is logged in
pg_profile_edit_log (source 'result_sheet'), visible in the doctor's profile.
"""
import logging
from flask import render_template, request, redirect, url_for, flash
from db import get_db
from core.users import get_user
from core.auth import login_required
from pg_admin import neet_qualify as NQ


def _admin():
    u = get_user()
    return u if (u and u.get('is_admin')) else None


def _audit(conn):
    users = [dict(r) for r in conn.execute(
        "SELECT id, name, mobile, neet_pg_rank, neet_pg_score FROM pg_users "
        "WHERE COALESCE(neet_pg_rank,0) > 0 OR COALESCE(neet_pg_score,0) > 0 ORDER BY id DESC").fetchall()]
    by_rank = NQ.score_for_ranks(conn, [u['neet_pg_rank'] for u in users])
    bands = NQ.ranks_for_scores(conn, [u['neet_pg_score'] for u in users if (u['neet_pg_score'] or 0) > 0])
    groups = {k: [] for k in ('fill', 'mismatch', 'not_found', 'score_only', 'ok')}
    for u in users:
        rank, score = u['neet_pg_rank'] or 0, u['neet_pg_score'] or 0
        u['band'] = bands.get(score) if score > 0 else None
        if rank <= 0:
            groups['score_only'].append(u)
            continue
        hit = by_rank.get(rank)
        if not hit:
            groups['not_found'].append(u)
            continue
        lo, hi, n = hit
        u['result_score'] = lo if lo == hi else None
        u['result_range'] = (lo, hi)
        if score <= 0:
            groups['fill' if lo == hi else 'not_found'].append(u)
        elif lo <= score <= hi:
            groups['ok'].append(u)
        else:
            groups['mismatch'].append(u)
    return groups


@login_required
def pg_scores_check():
    admin = _admin()
    if not admin:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        if request.method == 'POST':
            ids = sorted({int(x) for x in request.form.getlist('uid') if str(x).isdigit()})
            done = 0
            if ids:
                ph = ','.join(['?'] * len(ids))
                rows = [dict(r) for r in conn.execute(
                    f"SELECT id, neet_pg_rank, neet_pg_score FROM pg_users WHERE id IN ({ph})", tuple(ids)).fetchall()]
                by_rank = NQ.score_for_ranks(conn, [r['neet_pg_rank'] for r in rows])
                for r in rows:
                    hit = by_rank.get(r['neet_pg_rank'] or 0)
                    if not hit or hit[0] != hit[1] or hit[0] == r['neet_pg_score']:
                        continue
                    new = hit[0]
                    conn.execute("UPDATE pg_users SET neet_pg_score = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                 (new, r['id']))
                    conn.execute("INSERT INTO pg_profile_edit_log (user_id, field, old_value, new_value, changed_by, source) "
                                 "VALUES (?,?,?,?,?,?)",
                                 (r['id'], 'neet_pg_score', '' if r['neet_pg_score'] is None else str(r['neet_pg_score']),
                                  str(new), admin.get('name') or 'admin', 'result_sheet'))
                    done += 1
                conn.commit()
            flash(f'Updated the NEET-PG score for {done} doctor(s) from the {NQ.NEET_YEAR} result sheet '
                  f'(logged in each profile).', 'success')
            return redirect(url_for('pg_scores_check'))

        groups = _audit(conn)
        return render_template('pg_admin/diag_neet_scores.html', user=admin, active_section='goocampus_in',
                               groups=groups, cut=NQ.cutoff_rank(conn), qualify=NQ.QUALIFY_SCORE,
                               year=NQ.NEET_YEAR)
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("pg_scores_check: %s", e)
        flash(f'Score check error: {e}', 'error')
        return redirect(url_for('pg_users_admin'))
    finally:
        try: conn.close()
        except Exception: pass
