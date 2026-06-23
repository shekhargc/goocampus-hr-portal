"""College module — partner routes. Extracted from app.py (modularization)."""
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


def get_partner_visible_sections(*a, **k):
    """Shared Partner-portal helper — kept in app.py, called lazily to avoid a circular import."""
    from app import get_partner_visible_sections as _g
    return _g(*a, **k)


def partner_colleges():
    """College portal for partners (read-only, no admin actions)."""
    if not session.get('is_partner'):
        flash('Please log in as a partner', 'error')
        return redirect(url_for('login'))
    partner_id = session.get('user_id')
    visible = get_partner_visible_sections(partner_id)
    if 'partner_college_portal' not in visible:
        flash('You do not have access to this section', 'error')
        return redirect(url_for('partner_dashboard_view'))

    conn = get_db()
    category = request.args.get('category', 'all')
    search = request.args.get('search', '').strip()
    country = request.args.get('country', '')
    state_filter = request.args.get('state', '')
    course_filter = request.args.get('course', '').strip()
    fee_min = request.args.get('fee_min', '')
    fee_max = request.args.get('fee_max', '')

    query = "SELECT * FROM colleges WHERE is_active = TRUE"
    params = []
    if category and category != 'all':
        query += " AND category = ?"
        params.append(category)
    if country:
        query += " AND country = ?"
        params.append(country)
    if state_filter:
        query += " AND state_or_region = ?"
        params.append(state_filter)
    if search:
        query += " AND (LOWER(name) LIKE ? OR LOWER(city) LIKE ?)"
        params.extend([f'%{search.lower()}%', f'%{search.lower()}%'])

    query += " ORDER BY is_featured DESC, name ASC"
    colleges = conn.execute(query, params).fetchall()

    countries = conn.execute(
        "SELECT DISTINCT country FROM colleges WHERE is_active = TRUE AND category = 'international' ORDER BY country"
    ).fetchall()
    states = conn.execute(
        "SELECT DISTINCT state_or_region FROM colleges WHERE is_active = TRUE AND category = 'indian' AND state_or_region != '' ORDER BY state_or_region"
    ).fetchall()
    courses_list = conn.execute(
        "SELECT DISTINCT cc.course_name FROM college_courses cc JOIN colleges c ON cc.college_id = c.id WHERE c.is_active = TRUE AND c.category = 'indian' AND cc.is_active = TRUE ORDER BY cc.course_name"
    ).fetchall()

    course_counts = {}
    for c in colleges:
        cnt = conn.execute("SELECT COUNT(*) as cnt FROM college_courses WHERE college_id = ? AND is_active = TRUE", (c['id'],)).fetchone()
        course_counts[c['id']] = cnt['cnt'] if cnt else 0

    if course_filter:
        college_ids_with_course = conn.execute(
            "SELECT DISTINCT cc.college_id FROM college_courses cc WHERE cc.is_active = TRUE AND LOWER(cc.course_name) LIKE ?",
            (f'%{course_filter.lower()}%',)
        ).fetchall()
        valid_ids = {r['college_id'] for r in college_ids_with_course}
        colleges = [c for c in colleges if c['id'] in valid_ids]

    rates = _get_exchange_rates()
    live_package = {}
    for c in colleges:
        if c['category'] == 'international' and c['currency'] and c['currency'] != 'INR':
            fee_sum = conn.execute(
                """SELECT COALESCE(SUM(fs.total), 0) as grand_total
                   FROM college_fee_structure fs
                   JOIN college_courses cc ON fs.course_id = cc.id
                   WHERE cc.college_id = ? AND cc.is_active = TRUE""", (c['id'],)
            ).fetchone()
            total_foreign = float(fee_sum['grand_total'] or 0)
            if total_foreign > 0:
                total_inr = _to_inr(total_foreign, c['currency'], rates)
                live_package[c['id']] = round(total_inr / 100000, 2)
            else:
                live_package[c['id']] = float(c['full_package_inr_lakhs'] or 0)
        else:
            live_package[c['id']] = float(c['full_package_inr_lakhs'] or 0)

    if fee_min:
        try:
            mn = float(fee_min)
            colleges = [c for c in colleges if live_package.get(c['id'], 0) >= mn]
        except ValueError:
            pass
    if fee_max:
        try:
            mx = float(fee_max)
            colleges = [c for c in colleges if live_package.get(c['id'], 0) <= mx]
        except ValueError:
            pass

    all_names = conn.execute("SELECT name FROM colleges WHERE is_active = TRUE ORDER BY name").fetchall()
    conn.close()

    return render_template('college/colleges_list.html',
        colleges=colleges,
        countries=[c['country'] for c in countries],
        states=[s['state_or_region'] for s in states],
        courses_list=[c['course_name'] for c in courses_list],
        all_college_names=[n['name'] for n in all_names],
        course_counts=course_counts,
        live_package=live_package,
        category=category, search=search, country_filter=country,
        state_filter=state_filter, course_filter=course_filter,
        fee_min=fee_min, fee_max=fee_max,
        rates=rates, to_inr=_to_inr,
        is_partner=True,
        visible_sections=get_partner_visible_sections(partner_id),
                    active_section='colleges')


def partner_college_profile(slug):
    """Individual college profile for partners (read-only)."""
    if not session.get('is_partner'):
        flash('Please log in as a partner', 'error')
        return redirect(url_for('login'))
    partner_id = session.get('user_id')
    visible = get_partner_visible_sections(partner_id)
    if 'partner_college_portal' not in visible:
        flash('You do not have access to this section', 'error')
        return redirect(url_for('partner_dashboard_view'))

    conn = get_db()
    college = conn.execute("SELECT * FROM colleges WHERE slug = ?", (slug,)).fetchone()
    if not college:
        conn.close()
        flash("College not found.", "danger")
        return redirect(url_for('partner_colleges'))

    courses = conn.execute(
        "SELECT * FROM college_courses WHERE college_id = ? AND is_active = TRUE ORDER BY course_name",
        (college['id'],)
    ).fetchall()

    fees_by_course = {}
    for course in courses:
        fees = conn.execute(
            "SELECT * FROM college_fee_structure WHERE course_id = ? ORDER BY year_label, semester",
            (course['id'],)
        ).fetchall()
        fees_by_course[course['id']] = fees

    rates = _get_exchange_rates()
    live_package_lakhs = 0
    if college['category'] == 'international' and college['currency'] and college['currency'] != 'INR':
        total_foreign = sum(float(f['total'] or 0) for flist in fees_by_course.values() for f in flist)
        if total_foreign > 0:
            total_inr = _to_inr(total_foreign, college['currency'], rates)
            live_package_lakhs = round(total_inr / 100000, 2)
        else:
            live_package_lakhs = float(college['full_package_inr_lakhs'] or 0)
    else:
        live_package_lakhs = float(college['full_package_inr_lakhs'] or 0)

    cutoffs = []
    cutoff_years = []
    try:
        cutoff_rows = conn.execute(
            "SELECT * FROM mbbs_cutoffs WHERE institute_name = ? ORDER BY year DESC, quota, category",
            (college['name'],)
        ).fetchall()
        cutoffs = [dict(r) for r in cutoff_rows]
        cutoff_years = sorted(set(c['year'] for c in cutoffs), reverse=True)
    except Exception:
        pass

    conn.close()
    return render_template('college/college_profile.html',
        college=college, courses=courses, fees_by_course=fees_by_course,
        live_package_lakhs=live_package_lakhs, rates=rates,
        to_inr=_to_inr, currency_sym=_currency_sym,
        cutoffs=cutoffs, cutoff_years=cutoff_years,
        is_partner=True,
        visible_sections=get_partner_visible_sections(partner_id),
                    active_section='colleges')


def partner_medical_predictor():
    """Medical predictor for partners."""
    if not session.get('is_partner'):
        flash('Please log in as a partner', 'error')
        return redirect(url_for('login'))
    partner_id = session.get('user_id')
    visible = get_partner_visible_sections(partner_id)
    if 'partner_medical_predictor' not in visible:
        flash('You do not have access to this section', 'error')
        return redirect(url_for('partner_dashboard_view'))

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
        logging.error(f"partner_medical_predictor route: {e}")

    return render_template('college/medical_predictor.html',
        user=None, states=states, years=year_list,
        is_partner=True,
        visible_sections=get_partner_visible_sections(partner_id),
                    active_section='colleges')
