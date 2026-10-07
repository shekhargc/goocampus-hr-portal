"""Admin: review / correct the Clinical · Para-clinical · Pre-clinical grouping of every
speciality in the predictor data (founder 2026-10-07). Auto-grouped by rules; any row can be
overridden (stored in pg_course_branch, every change logged). Drives the predictor's optional
"Clinical / Non-clinical" filter.
"""
import logging
from flask import render_template, request, redirect, url_for, flash, session
from db import get_db
from core.users import get_user
from core.auth import login_required
from pg_admin.data import specialty_groups as SG


def _admin():
    return bool(session.get('is_admin'))


@login_required
def specialty_groups_admin():
    if not _admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    show = (request.args.get('show') or '').strip()      # '' | clinical | para_clinical | pre_clinical | none | overridden
    q = (request.args.get('q') or '').strip()
    conn = get_db()
    items, counts, year = [], {'clinical': 0, 'para_clinical': 0, 'pre_clinical': 0, '': 0, 'overridden': 0}, None
    try:
        SG.ensure_course_branch_table(conn)
        yr = conn.execute("SELECT COALESCE(MAX(year),0) AS y FROM pg_cutoffs").fetchone()
        year = int(yr['y']) if yr and yr['y'] else None
        ovr_rows = {r['course_key']: dict(r) for r in conn.execute(
            "SELECT course_key, branch_group, updated_by, updated_at FROM pg_course_branch").fetchall()}
        rows = conn.execute(
            "SELECT course, COUNT(*) AS n, MAX(year) AS last_year FROM pg_cutoffs "
            "WHERE COALESCE(course,'') <> '' AND COALESCE(is_reference,0) = 0 "
            "GROUP BY course ORDER BY course").fetchall()
        for r in rows:
            k = SG.course_key(r['course'])
            auto = SG.classify(r['course'])
            o = ovr_rows.get(k)
            eff = (o['branch_group'] or '') if o else auto
            counts[eff] = counts.get(eff, 0) + 1
            if o:
                counts['overridden'] += 1
            items.append({'course': r['course'], 'key': k, 'n': r['n'], 'last_year': r['last_year'],
                          'auto': auto, 'group': eff, 'overridden': bool(o),
                          'by': (o or {}).get('updated_by') or '',
                          'at': str((o or {}).get('updated_at') or '')[:16]})
    except Exception as e:
        logging.error("specialty_groups_admin: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()
    total = len(items)
    if show == 'overridden':
        items = [i for i in items if i['overridden']]
    elif show == 'none':
        items = [i for i in items if not i['group']]
    elif show in SG.GROUPS:
        items = [i for i in items if i['group'] == show]
    if q:
        ql = q.lower()
        items = [i for i in items if ql in i['course'].lower()]
    return render_template('pg_admin/specialty_groups.html', items=items, counts=counts, total=total,
                           show=show, q=q, year=year, labels=SG.GROUP_LABELS, groups=SG.GROUPS,
                           active_section='goocampus_in')


@login_required
def specialty_groups_set():
    """Set (or reset to automatic) one course's group. group='' + reset=1 → back to the rule."""
    if not _admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    course = (request.form.get('course') or '').strip()
    group = (request.form.get('group') or '').strip()
    back = {k: v for k, v in (('show', request.form.get('show') or ''), ('q', request.form.get('q') or '')) if v}
    k = SG.course_key(course)
    if not k:
        flash('Missing speciality.', 'error'); return redirect(url_for('pg_specialty_groups', **back))
    if group not in SG.GROUPS + ('', 'auto'):
        flash('Pick Clinical, Para-clinical, Pre-clinical or Automatic.', 'error')
        return redirect(url_for('pg_specialty_groups', **back))
    who = (get_user() or {}).get('name') or (get_user() or {}).get('emp_code') or 'admin'
    conn = get_db()
    try:
        SG.ensure_course_branch_table(conn)
        old = conn.execute("SELECT branch_group FROM pg_course_branch WHERE course_key = ?", (k,)).fetchone()
        old_g = (old['branch_group'] or '') if old else ('auto:' + SG.classify(course))
        if group == 'auto':
            conn.execute("DELETE FROM pg_course_branch WHERE course_key = ?", (k,))
            new_g = 'auto:' + SG.classify(course)
        else:
            conn.execute(
                "INSERT INTO pg_course_branch (course_key, course_label, branch_group, updated_by, updated_at) "
                "VALUES (?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT (course_key) DO UPDATE SET "
                "branch_group = EXCLUDED.branch_group, course_label = EXCLUDED.course_label, "
                "updated_by = EXCLUDED.updated_by, updated_at = CURRENT_TIMESTAMP",
                (k, course, group, who))
            new_g = group
        if old_g != new_g:
            conn.execute("INSERT INTO pg_course_branch_log (course_key, old_group, new_group, changed_by) "
                         "VALUES (?,?,?,?)", (k, old_g, new_g, who))
        conn.commit()
        flash(f'"{course}" → {SG.GROUP_LABELS.get(group, "Automatic")}' if group != 'auto'
              else f'"{course}" reset to automatic grouping.', 'success')
    except Exception as e:
        logging.error("specialty_groups_set: %s", e)
        try: conn.rollback()
        except Exception: pass
        flash('Could not save. Please try again.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_specialty_groups', **back))
