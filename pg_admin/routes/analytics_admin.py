"""goocampus.in usage analytics — admin dashboard over pg_user_events. Shows the most-used
sections, top searches, specialities, colleges opened, quota/category and fee-range interest,
plus a recent-activity feed. (founder 2026-09-24)"""
import logging
from flask import render_template, request, redirect, url_for, flash
from db import get_db
from core.users import get_user
from core.auth import login_required


def _admin():
    u = get_user()
    return u if (u and u.get('is_admin')) else None


@login_required
def analytics_admin():
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    days = (request.args.get('days') or '30').strip()
    if days == 'all':
        TW = "1=1"
    else:
        try:
            d = max(1, min(int(days), 3650))
        except (TypeError, ValueError):
            d = 30; days = '30'
        TW = f"created_at >= CURRENT_TIMESTAMP - INTERVAL '{d} days'"
    conn = get_db()
    data = {'days': days}
    try:
        def rows(sql):
            return [dict(r) for r in conn.execute(sql).fetchall()]
        def one(sql):
            return conn.execute(sql).fetchone()
        base = f"FROM pg_user_events WHERE {TW}"
        data['total'] = one(f"SELECT COUNT(*) AS c {base}")['c']
        data['users'] = one(f"SELECT COUNT(DISTINCT user_id) AS c {base} AND user_id IS NOT NULL")['c']
        data['days_active'] = one(f"SELECT COUNT(DISTINCT DATE(created_at)) AS c {base}")['c']

        def top(col, extra=''):
            return rows(f"SELECT {col} AS v, COUNT(*) AS c {base} AND COALESCE(TRIM({col}),'')<>'' "
                        f"{extra} GROUP BY {col} ORDER BY c DESC LIMIT 15")
        data['sections'] = rows(
            f"SELECT COALESCE(NULLIF(TRIM(section),''),'(unlabelled)') AS v, COUNT(*) AS c "
            f"{base} GROUP BY 1 ORDER BY c DESC LIMIT 15")
        data['searches'] = top('q')
        data['specialities'] = top('speciality')
        data['colleges'] = top('college_name')
        data['quotas'] = top('quota')
        data['categories'] = top('category')
        data['states'] = top('state')
        # Fee interest
        fr = one(f"SELECT COUNT(*) AS c, MIN(fee_min) AS lo, MAX(fee_max) AS hi, "
                 f"ROUND(AVG(fee_min)) AS avg_lo, ROUND(AVG(fee_max)) AS avg_hi {base} "
                 f"AND (fee_min IS NOT NULL OR fee_max IS NOT NULL)")
        data['fees'] = dict(fr) if fr else {}
        # Predictor rank interest
        rr = one(f"SELECT COUNT(*) AS c, ROUND(AVG(rank)) AS avg_rank, MIN(rank) AS lo, MAX(rank) AS hi "
                 f"{base} AND rank IS NOT NULL")
        data['ranks'] = dict(rr) if rr else {}
        # Recent activity feed — qualify the time clause (both tables have created_at)
        TW_E = TW.replace('created_at', 'e.created_at')
        data['recent'] = rows(
            "SELECT e.created_at, e.section, e.event_type, e.q, e.college_name, e.speciality, "
            "e.quota, e.category, e.state, e.fee_min, e.fee_max, e.rank, "
            "COALESCE(pu.name, pu.mobile, '—') AS who "
            "FROM pg_user_events e LEFT JOIN pg_users pu ON pu.id = e.user_id "
            f"WHERE {TW_E} ORDER BY e.id DESC LIMIT 60")
    except Exception as e:
        logging.error("analytics_admin: %s", e)
        flash(f'Analytics query failed: {e}', 'error')
    finally:
        conn.close()
    return render_template('pg_admin/analytics.html', d=data, active_section='goocampus_in')
