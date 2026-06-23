"""College module — predictor routes. Extracted from app.py (modularization)."""
import os, re, io, csv, json, time, random, hashlib, logging, threading, traceback
from io import BytesIO
from datetime import datetime, timedelta
import requests
import requests as http_requests
import json as _json
import time as _time
from flask import (render_template, request, session, redirect, url_for, flash,
                   jsonify, make_response, send_file, abort, Response)
from db import get_db
from core.auth import admin_required, login_required
from core.users import get_user
try:
    import pytz
except Exception:
    pytz = None
try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
except Exception:
    Workbook = Font = PatternFill = Alignment = Border = Side = None
from college.utils import _make_slug, _to_inr, _get_exchange_rates, _currency_sym, _currency_cache


@admin_required
def medical_predictor():
    user = get_user()
    states = []
    year_list = []
    try:
        conn = get_db()
        authorities = conn.execute(
            "SELECT DISTINCT counselling_authority FROM mbbs_cutoffs ORDER BY counselling_authority"
        ).fetchall()
        years = conn.execute(
            "SELECT DISTINCT year FROM mbbs_cutoffs ORDER BY year DESC"
        ).fetchall()
        conn.close()
        states = [a['counselling_authority'] for a in authorities if a['counselling_authority'] != 'All India / MCC']
        year_list = [y['year'] for y in years]
    except Exception as e:
        logging.error(f"medical_predictor route: {e}")
    return render_template('college/medical_predictor.html', user=user,
                           states=states, years=year_list,
                    active_section='colleges')


@admin_required
def predictor_import():
    """Manually trigger MBBS cutoff data import from JSON."""
    try:
        conn = get_db()
        # Ensure table exists
        conn.execute('''CREATE TABLE IF NOT EXISTS mbbs_cutoffs (
            id SERIAL PRIMARY KEY,
            year INTEGER NOT NULL,
            institute_name TEXT NOT NULL,
            quota TEXT DEFAULT '',
            category TEXT DEFAULT '',
            course TEXT DEFAULT 'MBBS',
            fees NUMERIC(12,2) DEFAULT 0,
            counselling_authority TEXT DEFAULT '',
            counselling_body TEXT DEFAULT '',
            round1_rank INTEGER,
            round2_rank INTEGER,
            round3_rank INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()

        existing = conn.execute("SELECT COUNT(*) as c FROM mbbs_cutoffs").fetchone()['c']
        if existing > 0:
            conn.execute("DELETE FROM mbbs_cutoffs")
            conn.commit()

        import json as _json
        json_path = os.path.join(os.path.dirname(__file__), 'mbbs_cutoff_data.json')
        if not os.path.exists(json_path):
            conn.close()
            return jsonify({'success': False, 'error': 'mbbs_cutoff_data.json not found on server'}), 404

        with open(json_path, 'r') as f:
            rows = _json.load(f)

        all_tuples = [tuple(r) for r in rows]
        insert_sql = '''INSERT INTO mbbs_cutoffs
            (year, institute_name, quota, category, course, fees,
             counselling_authority, counselling_body,
             round1_rank, round2_rank, round3_rank)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)'''
        conn.execute_batch(insert_sql, all_tuples, page_size=500)
        conn.commit()
        conn.close()
        logging.info(f"Manual import: {len(all_tuples)} MBBS cutoff rows imported")
        return jsonify({'success': True, 'imported': len(all_tuples)})
    except Exception as e:
        logging.error(f"predictor_import: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


def predictor_filters():
    """Return dynamic filter options based on selected authority + year. Accessible by admin and partners."""
    if not session.get('user_id'):
        return jsonify({'error': 'Login required'}), 401
    if not session.get('is_partner'):
        # Admin check
        conn_check = get_db()
        u = conn_check.execute('SELECT is_admin FROM employees WHERE id = ?', (session['user_id'],)).fetchone()
        conn_check.close()
        if not u or u['is_admin'] != 1:
            return jsonify({'error': 'Access denied'}), 403
    conn = get_db()
    authority = request.args.get('authority', '').strip()
    year = request.args.get('year', '').strip()

    conditions = []
    params = []
    if authority:
        conditions.append("counselling_authority = ?")
        params.append(authority)
    if year:
        conditions.append("year = ?")
        params.append(int(year))

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    quotas = conn.execute(
        f"SELECT DISTINCT quota FROM mbbs_cutoffs {where} ORDER BY quota", params
    ).fetchall()
    categories = conn.execute(
        f"SELECT DISTINCT category FROM mbbs_cutoffs {where} ORDER BY category", params
    ).fetchall()
    institutes = conn.execute(
        f"SELECT DISTINCT institute_name FROM mbbs_cutoffs {where} ORDER BY institute_name", params
    ).fetchall()
    conn.close()

    return jsonify({
        'quotas': [q['quota'] for q in quotas],
        'categories': [c['category'] for c in categories],
        'institutes': [i['institute_name'] for i in institutes],
    })


def predictor_search():
    """Search cut-off data with filters. Returns JSON. Accessible by admin and partners."""
    if not session.get('user_id'):
        return jsonify({'error': 'Login required'}), 401
    if not session.get('is_partner'):
        conn_check = get_db()
        u = conn_check.execute('SELECT is_admin FROM employees WHERE id = ?', (session['user_id'],)).fetchone()
        conn_check.close()
        if not u or u['is_admin'] != 1:
            return jsonify({'error': 'Access denied'}), 403
    conn = get_db()
    authority = request.args.get('authority', '').strip()
    year = request.args.get('year', '').strip()
    quota = request.args.get('quota', '').strip()
    category = request.args.get('category', '').strip()
    institute = request.args.get('institute', '').strip()
    rank = request.args.get('rank', '').strip()
    fee_min = request.args.get('fee_min', '').strip()
    fee_max = request.args.get('fee_max', '').strip()
    page = int(request.args.get('page', 1))
    per_page = 50

    conditions = []
    params = []

    if authority:
        conditions.append("counselling_authority = ?")
        params.append(authority)
    if year:
        conditions.append("year = ?")
        params.append(int(year))
    if quota:
        conditions.append("quota = ?")
        params.append(quota)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if institute:
        conditions.append("LOWER(institute_name) LIKE LOWER(?)")
        params.append(f"%{institute}%")
    if rank:
        # Show colleges where user's rank is <= any round's cutoff rank
        rank_val = int(rank)
        conditions.append("(round1_rank >= ? OR round2_rank >= ? OR round3_rank >= ?)")
        params.extend([rank_val, rank_val, rank_val])
    if fee_min:
        conditions.append("fees >= ?")
        params.append(float(fee_min))
    if fee_max:
        conditions.append("fees <= ?")
        params.append(float(fee_max))

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    # Count total
    count_params = list(params)
    total = conn.execute(f"SELECT COUNT(*) as c FROM mbbs_cutoffs {where}", count_params).fetchone()['c']

    # Fetch page
    offset = (page - 1) * per_page
    query_params = list(params)
    query_params.extend([per_page, offset])
    rows = conn.execute(f'''
        SELECT institute_name, quota, category, fees, counselling_authority,
               counselling_body, round1_rank, round2_rank, round3_rank, year
        FROM mbbs_cutoffs {where}
        ORDER BY round1_rank ASC NULLS LAST, institute_name ASC
        LIMIT ? OFFSET ?
    ''', query_params).fetchall()

    # Build slug lookup for linking to college profiles
    inst_names = list(set(r['institute_name'] for r in rows))
    slug_map = {}
    if inst_names:
        for name in inst_names:
            slug_row = conn.execute(
                "SELECT slug FROM colleges WHERE name = ? LIMIT 1", (name,)
            ).fetchone()
            if slug_row:
                slug_map[name] = slug_row['slug']

    conn.close()

    results = []
    for r in rows:
        results.append({
            'institute': r['institute_name'],
            'slug': slug_map.get(r['institute_name'], ''),
            'quota': r['quota'],
            'category': r['category'],
            'fees': float(r['fees'] or 0),
            'authority': r['counselling_authority'],
            'body': r['counselling_body'],
            'r1': r['round1_rank'],
            'r2': r['round2_rank'],
            'r3': r['round3_rank'],
            'year': r['year'],
        })

    return jsonify({
        'results': results,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page,
    })
