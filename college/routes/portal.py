"""College module — portal routes. Extracted from app.py (modularization)."""
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
def colleges_list():
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

    if category == 'indian':
        query += " AND category = 'indian'"
    elif category == 'international':
        query += " AND category = 'international'"

    if country:
        query += " AND country = ?"
        params.append(country)

    if state_filter:
        query += " AND state_or_region = ?"
        params.append(state_filter)

    if search:
        query += " AND (LOWER(name) LIKE ? OR LOWER(city) LIKE ?)"
        params.extend([f'%{search.lower()}%', f'%{search.lower()}%'])

    # Fee range filtering is done post-query using live conversion
    query += " ORDER BY is_featured DESC, name ASC"
    colleges = conn.execute(query, params).fetchall()

    # Get unique countries for filter (international only)
    countries = conn.execute(
        "SELECT DISTINCT country FROM colleges WHERE is_active = TRUE AND category = 'international' ORDER BY country"
    ).fetchall()

    # Get unique states for Indian colleges filter
    states = conn.execute(
        "SELECT DISTINCT state_or_region FROM colleges WHERE is_active = TRUE AND category = 'indian' AND state_or_region != '' ORDER BY state_or_region"
    ).fetchall()

    # Get unique courses for Indian filter
    courses_list = conn.execute(
        "SELECT DISTINCT cc.course_name FROM college_courses cc JOIN colleges c ON cc.college_id = c.id WHERE c.is_active = TRUE AND c.category = 'indian' AND cc.is_active = TRUE ORDER BY cc.course_name"
    ).fetchall()

    # Get course count per college
    course_counts = {}
    for c in colleges:
        cnt = conn.execute(
            "SELECT COUNT(*) as cnt FROM college_courses WHERE college_id = ? AND is_active = TRUE",
            (c['id'],)
        ).fetchone()
        course_counts[c['id']] = cnt['cnt'] if cnt else 0

    # Filter by course (post-query since it requires join)
    if course_filter:
        college_ids_with_course = conn.execute(
            "SELECT DISTINCT cc.college_id FROM college_courses cc WHERE cc.is_active = TRUE AND LOWER(cc.course_name) LIKE ?",
            (f'%{course_filter.lower()}%',)
        ).fetchall()
        valid_ids = {r['college_id'] for r in college_ids_with_course}
        colleges = [c for c in colleges if c['id'] in valid_ids]

    # Get exchange rates for INR display
    rates = _get_exchange_rates()

    # Compute live full_package_inr_lakhs for international colleges
    # Sum all fee structure row totals (each year/sem is its own row), convert to INR
    live_package = {}
    for c in colleges:
        if c['category'] == 'international' and c['currency'] and c['currency'] != 'INR':
            fee_sum = conn.execute(
                """SELECT COALESCE(SUM(fs.total), 0) as grand_total
                   FROM college_fee_structure fs
                   JOIN college_courses cc ON fs.course_id = cc.id
                   WHERE cc.college_id = ? AND cc.is_active = TRUE""",
                (c['id'],)
            ).fetchone()
            total_foreign = float(fee_sum['grand_total'] or 0)
            if total_foreign > 0:
                total_inr = _to_inr(total_foreign, c['currency'], rates)
                live_package[c['id']] = round(total_inr / 100000, 2)
            else:
                live_package[c['id']] = float(c['full_package_inr_lakhs'] or 0)
        else:
            live_package[c['id']] = float(c['full_package_inr_lakhs'] or 0)

    # Apply fee range filter on live computed values
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

    # All college names for autocomplete
    all_names = conn.execute(
        "SELECT name FROM colleges WHERE is_active = TRUE ORDER BY name"
    ).fetchall()

    conn.close()
    return render_template('college/colleges_list.html',
        colleges=colleges,
        countries=[c['country'] for c in countries],
        states=[s['state_or_region'] for s in states],
        courses_list=[c['course_name'] for c in courses_list],
        all_college_names=[n['name'] for n in all_names],
        course_counts=course_counts,
        live_package=live_package,
        category=category,
        search=search,
        country_filter=country,
        state_filter=state_filter,
        course_filter=course_filter,
        fee_min=fee_min,
        fee_max=fee_max,
        rates=rates,
        to_inr=_to_inr,
                    active_section='colleges')


@admin_required
def college_profile(slug):
    conn = get_db()
    college = conn.execute("SELECT * FROM colleges WHERE slug = ?", (slug,)).fetchone()
    if not college:
        conn.close()
        flash("College not found.", "danger")
        return redirect('/colleges')

    courses = conn.execute(
        "SELECT * FROM college_courses WHERE college_id = ? AND is_active = TRUE ORDER BY course_name",
        (college['id'],)
    ).fetchall()

    # Get fee structure for each course
    fees_by_course = {}
    for course in courses:
        fees = conn.execute(
            "SELECT * FROM college_fee_structure WHERE course_id = ? ORDER BY year_label, semester",
            (course['id'],)
        ).fetchall()
        fees_by_course[course['id']] = fees

    rates = _get_exchange_rates()

    # Compute live full package in INR lakhs (sum all fee rows, convert to INR)
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

    # Fetch MBBS cut-off data for this college (matching by name)
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
        college=college,
        courses=courses,
        fees_by_course=fees_by_course,
        live_package_lakhs=live_package_lakhs,
        rates=rates,
        to_inr=_to_inr,
        currency_sym=_currency_sym,
        cutoffs=cutoffs,
        cutoff_years=cutoff_years,
                    active_section='colleges')


@admin_required
def college_add():
    if request.method == 'POST':
        conn = get_db()
        name = request.form.get('name', '').strip()
        if not name:
            flash("College name is required.", "danger")
            return redirect('/colleges/admin/add')

        slug = _make_slug(name)
        # Check unique slug
        existing = conn.execute("SELECT id FROM colleges WHERE slug = ?", (slug,)).fetchone()
        if existing:
            slug = slug + '-' + str(int(_time.time()) % 10000)

        category = request.form.get('category', 'international')
        # City: from dropdown or free text
        city = request.form.get('city', '').strip() or request.form.get('city_text', '').strip()
        try:
            conn.execute('''INSERT INTO colleges (name, slug, category, country, state_or_region, city,
                established_year, university_type, medium_of_instruction, nmc_approved, who_approved,
                indian_passouts, description, eligibility, facilities, ranking_info, website_url,
                contact_phone, contact_email, currency, full_package_inr_lakhs,
                mess_charges, consultancy_fee_inr, admin_fee, travel_cost_inr,
                hostel_included, is_featured, logo_url, cover_image_url,
                university_name, annual_intake, counselling_authority, opd, ipd, bond_penalty, bed_count, prospects_url)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (name, slug, category,
                 request.form.get('country', ''),
                 request.form.get('state_or_region', ''),
                 city,
                 int(request.form.get('established_year') or 0),
                 request.form.get('university_type', 'Government'),
                 request.form.get('medium_of_instruction', 'English'),
                 1 if request.form.get('nmc_approved') else 0,
                 1 if request.form.get('who_approved') else 0,
                 request.form.get('indian_passouts', ''),
                 request.form.get('description', ''),
                 request.form.get('eligibility', ''),
                 request.form.get('facilities', ''),
                 request.form.get('ranking_info', ''),
                 request.form.get('website_url', ''),
                 request.form.get('contact_phone', ''),
                 request.form.get('contact_email', ''),
                 request.form.get('currency', 'INR'),
                 float(request.form.get('full_package_inr_lakhs') or 0),
                 request.form.get('mess_charges', ''),
                 float(request.form.get('consultancy_fee_inr') or 0),
                 request.form.get('admin_fee', ''),
                 float(request.form.get('travel_cost_inr') or 0),
                 1 if request.form.get('hostel_included') else 0,
                 1 if request.form.get('is_featured') else 0,
                 request.form.get('logo_url', ''),
                 request.form.get('cover_image_url', ''),
                 request.form.get('university_name', ''),
                 int(request.form.get('annual_intake') or 0),
                 request.form.get('counselling_authority', ''),
                 int(request.form.get('opd') or 0),
                 int(request.form.get('ipd') or 0),
                 request.form.get('bond_penalty', ''),
                 int(request.form.get('bed_count') or 0),
                 request.form.get('prospects_url', '')))
            conn.commit()
            flash(f"College '{name}' added successfully!", "success")
        except Exception as e:
            logging.error(f"College add error: {e}")
            flash(f"Error adding college: {e}", "danger")
        finally:
            conn.close()
        return redirect('/colleges')

    conn = get_db()
    countries = conn.execute("SELECT id, name FROM countries WHERE is_active = TRUE ORDER BY name").fetchall()
    states = conn.execute("SELECT id, name FROM states WHERE is_active = TRUE ORDER BY name").fetchall()
    conn.close()
    return render_template('college/college_form.html', college=None, mode='add',
                           countries=countries, states=states,
                    active_section='colleges')


@admin_required
def college_edit(college_id):
    conn = get_db()
    college = conn.execute("SELECT * FROM colleges WHERE id = ?", (college_id,)).fetchone()
    if not college:
        conn.close()
        flash("College not found.", "danger")
        return redirect('/colleges')

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        is_intl_editor = request.form.get('fee_editor') == '1'
        try:
            city = request.form.get('city', '').strip() or request.form.get('city_text', '').strip()
            if is_intl_editor:
                # Targeted update — only the fields the smart international editor has,
                # so unrelated columns (contact, state, intake, counselling, hospital…)
                # are preserved. Full package is auto-derived from the fee rows below.
                conn.execute('''UPDATE colleges SET name=?, category='international', country=?, city=?,
                    established_year=?, university_type=?, medium_of_instruction=?, nmc_approved=?, who_approved=?,
                    indian_passouts=?, description=?, eligibility=?, website_url=?, currency=?,
                    mess_charges=?, consultancy_fee_inr=?, admin_fee=?, travel_cost_inr=?,
                    hostel_included=?, is_featured=?, logo_url=?, cover_image_url=?,
                    university_name=?, prospects_url=?, updated_at=CURRENT_TIMESTAMP WHERE id=?''',
                    (name,
                     request.form.get('country', ''), city,
                     int(request.form.get('established_year') or 0),
                     request.form.get('university_type', 'Government'),
                     request.form.get('medium_of_instruction', 'English'),
                     1 if request.form.get('nmc_approved') else 0,
                     1 if request.form.get('who_approved') else 0,
                     request.form.get('indian_passouts', ''),
                     request.form.get('description', ''),
                     request.form.get('eligibility', ''),
                     request.form.get('website_url', ''),
                     request.form.get('currency', 'INR'),
                     request.form.get('mess_charges', ''),
                     float(request.form.get('consultancy_fee_inr') or 0),
                     request.form.get('admin_fee', ''),
                     float(request.form.get('travel_cost_inr') or 0),
                     1 if request.form.get('hostel_included') else 0,
                     1 if request.form.get('is_featured') else 0,
                     request.form.get('logo_url', ''),
                     request.form.get('cover_image_url', ''),
                     request.form.get('university_name', ''),
                     request.form.get('prospects_url', ''),
                     college_id))
            else:
                conn.execute('''UPDATE colleges SET name=?, category=?, country=?, state_or_region=?, city=?,
                    established_year=?, university_type=?, medium_of_instruction=?, nmc_approved=?, who_approved=?,
                    indian_passouts=?, description=?, eligibility=?, facilities=?, ranking_info=?, website_url=?,
                    contact_phone=?, contact_email=?, currency=?, full_package_inr_lakhs=?,
                    mess_charges=?, consultancy_fee_inr=?, admin_fee=?, travel_cost_inr=?,
                    hostel_included=?, is_featured=?, logo_url=?, cover_image_url=?,
                    university_name=?, annual_intake=?, counselling_authority=?, opd=?, ipd=?,
                    bond_penalty=?, bed_count=?, prospects_url=?,
                    updated_at=CURRENT_TIMESTAMP WHERE id=?''',
                    (name,
                     request.form.get('category', 'international'),
                     request.form.get('country', ''),
                     request.form.get('state_or_region', ''),
                     city,
                     int(request.form.get('established_year') or 0),
                     request.form.get('university_type', 'Government'),
                     request.form.get('medium_of_instruction', 'English'),
                     1 if request.form.get('nmc_approved') else 0,
                     1 if request.form.get('who_approved') else 0,
                     request.form.get('indian_passouts', ''),
                     request.form.get('description', ''),
                     request.form.get('eligibility', ''),
                     request.form.get('facilities', ''),
                     request.form.get('ranking_info', ''),
                     request.form.get('website_url', ''),
                     request.form.get('contact_phone', ''),
                     request.form.get('contact_email', ''),
                     request.form.get('currency', 'INR'),
                     float(request.form.get('full_package_inr_lakhs') or 0),
                     request.form.get('mess_charges', ''),
                     float(request.form.get('consultancy_fee_inr') or 0),
                     request.form.get('admin_fee', ''),
                     float(request.form.get('travel_cost_inr') or 0),
                     1 if request.form.get('hostel_included') else 0,
                     1 if request.form.get('is_featured') else 0,
                     request.form.get('logo_url', ''),
                     request.form.get('cover_image_url', ''),
                     request.form.get('university_name', ''),
                     int(request.form.get('annual_intake') or 0),
                     request.form.get('counselling_authority', ''),
                     int(request.form.get('opd') or 0),
                     int(request.form.get('ipd') or 0),
                     request.form.get('bond_penalty', ''),
                     int(request.form.get('bed_count') or 0),
                     request.form.get('prospects_url', ''),
                     college_id))
            conn.commit()

            # ── Smart international editor: rebuild courses + fee rows, auto-derive full package ──
            if is_intl_editor:
                currency = request.form.get('currency', 'INR')
                rates = _get_exchange_rates()
                course_ids = [r['id'] for r in conn.execute(
                    "SELECT id FROM college_courses WHERE college_id = ?", (college_id,)).fetchall()]

                # Update each course's own fields (name / duration / intake)
                for cid in course_ids:
                    cn = request.form.get(f'course_name_{cid}')
                    if cn is not None:
                        conn.execute(
                            "UPDATE college_courses SET course_name=?, degree=?, duration_years=?, duration_includes=?, intake_season=? WHERE id=?",
                            (cn.strip() or 'MBBS', cn.strip() or 'MBBS',
                             int(request.form.get(f'duration_years_{cid}') or 6),
                             request.form.get(f'duration_includes_{cid}', 'Including Internship'),
                             request.form.get(f'intake_season_{cid}', 'Summer'), cid))

                # Replace all fee rows from the submitted table
                for cid in course_ids:
                    conn.execute("DELETE FROM college_fee_structure WHERE course_id = ?", (cid,))
                fcid = request.form.getlist('fee_course_id')
                fyear = request.form.getlist('fee_year')
                fsem = request.form.getlist('fee_sem')
                ftui = request.form.getlist('fee_tuition')
                fhos = request.form.getlist('fee_hostel')
                fdoc = request.form.getlist('fee_docs')
                fvisa = request.form.getlist('fee_visa')

                def _num(lst, i):
                    try:
                        return float(lst[i] or 0)
                    except (ValueError, IndexError):
                        return 0.0

                grand_inr = 0.0
                for i in range(len(fcid)):
                    try:
                        cid = int(fcid[i])
                    except (ValueError, TypeError):
                        continue
                    if cid not in course_ids:
                        continue
                    tui, hos = _num(ftui, i), _num(fhos, i)
                    doc, visa = _num(fdoc, i), _num(fvisa, i)
                    total = tui + hos + doc + visa
                    if total <= 0 and not (fyear[i:i + 1] and fyear[i].strip()):
                        continue  # skip empty rows
                    total_inr = _to_inr(total, currency, rates)
                    grand_inr += total_inr
                    conn.execute(
                        "INSERT INTO college_fee_structure (course_id, year_label, semester, tuition_fee, hostel_fee, docs_med_checkup, visa_med_insurance, total, total_inr) VALUES (?,?,?,?,?,?,?,?,?)",
                        (cid, (fyear[i] if i < len(fyear) else '1st Year'),
                         (fsem[i] if i < len(fsem) else '1st Sem'),
                         tui, hos, doc, visa, total, total_inr))

                # Auto-derive the full package (INR lakhs) from the fee rows
                conn.execute("UPDATE colleges SET full_package_inr_lakhs = ? WHERE id = ?",
                             (round(grand_inr / 100000, 2), college_id))
                conn.commit()

            flash(f"College '{name}' updated!", "success")
        except Exception as e:
            logging.error(f"College edit error: {e}")
            flash(f"Error: {e}", "danger")
        finally:
            conn.close()
        return redirect(f'/colleges/{college["slug"]}')

    # ── GET: international colleges use the smart profile-style editor ──
    if college['category'] == 'international':
        courses = conn.execute(
            "SELECT * FROM college_courses WHERE college_id = ? AND is_active = TRUE ORDER BY id", (college_id,)
        ).fetchall()
        fees_by_course = {}
        for course in courses:
            fees_by_course[course['id']] = conn.execute(
                "SELECT * FROM college_fee_structure WHERE course_id = ? ORDER BY year_label, semester", (course['id'],)
            ).fetchall()
        rates = _get_exchange_rates()
        countries = conn.execute("SELECT id, name FROM countries WHERE is_active = TRUE ORDER BY name").fetchall()
        conn.close()
        return render_template('college/college_edit_intl.html', college=college, courses=courses,
                               fees_by_course=fees_by_course, countries=countries, rates=rates,
                               currency_sym=_currency_sym, active_section='colleges')

    countries = conn.execute("SELECT id, name FROM countries WHERE is_active = TRUE ORDER BY name").fetchall()
    states = conn.execute("SELECT id, name FROM states WHERE is_active = TRUE ORDER BY name").fetchall()
    conn.close()
    return render_template('college/college_form.html', college=college, mode='edit',
                           countries=countries, states=states,
                    active_section='colleges')


@admin_required
def college_delete(college_id):
    conn = get_db()
    try:
        conn.execute("UPDATE colleges SET is_active = FALSE WHERE id = ?", (college_id,))
        conn.commit()
        flash("College removed.", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect('/colleges')


@admin_required
def college_course_add(college_id):
    conn = get_db()
    try:
        course_name = request.form.get('course_name', 'MBBS').strip()
        conn.execute('''INSERT INTO college_courses (college_id, course_name, degree, duration_years,
            duration_includes, intake_season, seats_available, description, eligibility)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            (college_id, course_name,
             request.form.get('degree', 'MBBS'),
             int(request.form.get('duration_years') or 6),
             request.form.get('duration_includes', 'Including Internship'),
             request.form.get('intake_season', 'Summer'),
             int(request.form.get('seats_available') or 0),
             request.form.get('course_description', ''),
             request.form.get('course_eligibility', '')))
        conn.commit()
        flash(f"Course '{course_name}' added!", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    college = conn.execute("SELECT slug FROM colleges WHERE id = ?", (college_id,)).fetchone()
    return redirect(f'/colleges/{college["slug"]}' if college else '/colleges')


@admin_required
def college_fee_add(course_id):
    conn = get_db()
    try:
        conn.execute('''INSERT INTO college_fee_structure (course_id, year_label, semester,
            tuition_fee, hostel_fee, docs_med_checkup, visa_med_insurance, total, total_inr, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (course_id,
             request.form.get('year_label', '1st Year'),
             request.form.get('semester', '1st Sem'),
             float(request.form.get('tuition_fee') or 0),
             float(request.form.get('hostel_fee') or 0),
             float(request.form.get('docs_med_checkup') or 0),
             float(request.form.get('visa_med_insurance') or 0),
             float(request.form.get('total') or 0),
             float(request.form.get('total_inr') or 0),
             request.form.get('fee_notes', '')))
        conn.commit()
        flash("Fee row added!", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect(request.referrer or '/colleges')


@admin_required
def college_fee_delete(fee_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM college_fee_structure WHERE id = ?", (fee_id,))
        conn.commit()
        flash("Fee row deleted.", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect(request.referrer or '/colleges')


@admin_required
def college_seed():
    """Seed colleges from the built-in Russian college data."""
    conn = get_db()
    added = 0
    skipped = 0
    try:
        from college_seed_data import RUSSIAN_COLLEGES
        for c in RUSSIAN_COLLEGES:
            slug = _make_slug(c['name'])
            existing = conn.execute("SELECT id FROM colleges WHERE slug = ?", (slug,)).fetchone()
            if existing:
                skipped += 1
                continue

            conn.execute('''INSERT INTO colleges (name, slug, category, country, city,
                established_year, university_type, medium_of_instruction, nmc_approved, who_approved,
                indian_passouts, currency, full_package_inr_lakhs,
                mess_charges, consultancy_fee_inr, admin_fee, travel_cost_inr,
                hostel_included, eligibility)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (c['name'], slug, 'international', c.get('country', 'Russia'), c.get('city', ''),
                 c.get('established_year', 0), c.get('university_type', 'Government'),
                 c.get('medium', 'English'),
                 1 if c.get('nmc_approved') else 0,
                 1 if c.get('who_approved') else 0,
                 c.get('indian_passouts', ''),
                 c.get('currency', 'RUB'),
                 c.get('full_package_inr_lakhs', 0),
                 c.get('mess_charges', ''),
                 c.get('consultancy_fee_inr', 125000),
                 c.get('admin_fee', '1500 $'),
                 c.get('travel_cost_inr', 75000),
                 1 if c.get('hostel_included') else 0,
                 c.get('eligibility', '')))

            # Get the new college ID
            new_college = conn.execute("SELECT id FROM colleges WHERE slug = ?", (slug,)).fetchone()
            if new_college:
                # Add default MBBS course
                conn.execute('''INSERT INTO college_courses (college_id, course_name, degree,
                    duration_years, duration_includes, intake_season)
                    VALUES (?, 'MBBS', 'MBBS', ?, 'Including Internship', 'Summer')''',
                    (new_college['id'], c.get('duration_years', 6)))

                course = conn.execute(
                    "SELECT id FROM college_courses WHERE college_id = ? ORDER BY id DESC LIMIT 1",
                    (new_college['id'],)
                ).fetchone()

                if course and c.get('fees'):
                    for fee in c['fees']:
                        conn.execute('''INSERT INTO college_fee_structure
                            (course_id, year_label, semester, tuition_fee, hostel_fee,
                             docs_med_checkup, visa_med_insurance, total, total_inr)
                            VALUES (?,?,?,?,?,?,?,?,?)''',
                            (course['id'], fee['year_label'], fee['semester'],
                             fee.get('tuition', 0), fee.get('hostel', 0),
                             fee.get('docs', 0), fee.get('visa', 0),
                             fee.get('total', 0), fee.get('total_inr', 0)))
            added += 1

        conn.commit()
        flash(f"Seeded {added} colleges ({skipped} already existed).", "success")
    except ImportError:
        flash("Seed data file not found. Upload college_seed_data.py first.", "danger")
    except Exception as e:
        logging.error(f"College seed error: {e}")
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect('/colleges')


@admin_required
def college_debug_import():
    """Debug route: try inserting one Russian college and return detailed error."""
    conn = get_db()
    try:
        # Check if tables exist
        tables_info = {}
        for tbl in ['colleges', 'college_courses', 'college_fee_structure', 'countries', 'states', 'cities']:
            try:
                cnt = conn.execute(f"SELECT COUNT(*) as cnt FROM {tbl}").fetchone()
                tables_info[tbl] = cnt['cnt']
            except Exception as e:
                tables_info[tbl] = f"ERROR: {e}"

        # Try to import college_seed_data
        seed_info = "not loaded"
        try:
            from college_seed_data import RUSSIAN_COLLEGES
            seed_info = f"loaded, {len(RUSSIAN_COLLEGES)} colleges"
        except ImportError as e:
            seed_info = f"ImportError: {e}"

        # Check indian_colleges_data.json
        import json as _json
        json_path = os.path.join(os.path.dirname(__file__), 'indian_colleges_data.json')
        json_info = f"exists={os.path.exists(json_path)}"
        if os.path.exists(json_path):
            with open(json_path, 'r') as f:
                data = _json.load(f)
            json_info += f", rows={len(data)}"

        # Try inserting one test college
        test_result = "not attempted"
        try:
            test_slug = 'debug-test-college-' + str(int(_time.time()))
            conn.execute('''INSERT INTO colleges (name, slug, category, country, city,
                established_year, university_type, medium_of_instruction, nmc_approved, who_approved,
                currency)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                ('Debug Test College', test_slug, 'international', 'Russia', 'Moscow',
                 2000, 'Government', 'English', 1, 1, 'RUB'))
            conn.commit()
            test_result = "SUCCESS - inserted"
            # Clean up
            conn.execute("DELETE FROM colleges WHERE slug = ?", (test_slug,))
            conn.commit()
            test_result += " and cleaned up"
        except Exception as e:
            test_result = f"FAILED: {e}"
            try:
                conn.rollback()
            except:
                pass

        conn.close()
        return jsonify({
            'tables': tables_info,
            'seed_data': seed_info,
            'json_data': json_info,
            'test_insert': test_result
        })
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)})


@admin_required
def college_import_all():
    """Import Russian + Indian colleges with per-row error handling."""
    conn = get_db()
    results = {'russian_added': 0, 'russian_errors': 0, 'indian_added': 0, 'indian_errors': 0}

    # ── Russian colleges ──
    try:
        from college_seed_data import RUSSIAN_COLLEGES
        for c in RUSSIAN_COLLEGES:
            try:
                slug = _make_slug(c['name'])
                ex = conn.execute("SELECT id FROM colleges WHERE slug = ?", (slug,)).fetchone()
                if ex:
                    continue

                conn.execute('''INSERT INTO colleges (name, slug, category, country, city,
                    established_year, university_type, medium_of_instruction, nmc_approved, who_approved,
                    indian_passouts, currency, full_package_inr_lakhs,
                    mess_charges, consultancy_fee_inr, admin_fee, travel_cost_inr,
                    hostel_included, eligibility)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (c['name'], slug, 'international', c.get('country', 'Russia'), c.get('city', ''),
                     c.get('established_year', 0), c.get('university_type', 'Government'),
                     c.get('medium', 'English'),
                     1 if c.get('nmc_approved') else 0,
                     1 if c.get('who_approved') else 0,
                     c.get('indian_passouts', ''),
                     c.get('currency', 'RUB'),
                     c.get('full_package_inr_lakhs', 0),
                     c.get('mess_charges', ''),
                     c.get('consultancy_fee_inr', 125000),
                     c.get('admin_fee', '1500 $'),
                     c.get('travel_cost_inr', 75000),
                     1 if c.get('hostel_included') else 0,
                     c.get('eligibility', '')))

                new_college = conn.execute("SELECT id FROM colleges WHERE slug = ?", (slug,)).fetchone()
                if new_college:
                    conn.execute('''INSERT INTO college_courses (college_id, course_name, degree,
                        duration_years, duration_includes, intake_season)
                        VALUES (?, 'MBBS', 'MBBS', ?, 'Including Internship', 'Summer')''',
                        (new_college['id'], c.get('duration_years', 6)))

                    course = conn.execute(
                        "SELECT id FROM college_courses WHERE college_id = ? ORDER BY id DESC LIMIT 1",
                        (new_college['id'],)).fetchone()

                    if course and c.get('fees'):
                        for fee in c['fees']:
                            conn.execute('''INSERT INTO college_fee_structure
                                (course_id, year_label, semester, tuition_fee, hostel_fee,
                                 docs_med_checkup, visa_med_insurance, total, total_inr)
                                VALUES (?,?,?,?,?,?,?,?,?)''',
                                (course['id'], fee['year_label'], fee['semester'],
                                 fee.get('tuition', 0), fee.get('hostel', 0),
                                 fee.get('docs', 0), fee.get('visa', 0),
                                 fee.get('total', 0), fee.get('total_inr', 0)))

                conn.commit()
                results['russian_added'] += 1
            except Exception as e:
                results['russian_errors'] += 1
                logging.warning(f"Russian import error ({c.get('name', '?')}): {e}")
                try:
                    conn.rollback()
                except Exception:
                    pass
    except ImportError:
        logging.warning("college_seed_data.py not found")

    # ── Indian colleges ──
    import json
    json_path = os.path.join(os.path.dirname(__file__), 'indian_colleges_data.json')
    if os.path.exists(json_path):
        def safe_int(v):
            try:
                if v is None or v == '':
                    return 0
                return int(float(str(v).replace(',', '')))
            except (ValueError, TypeError):
                return 0

        with open(json_path, 'r') as f:
            colleges_data = json.load(f)

        # Backfill states/cities first
        seen_states = set()
        seen_cities = set()
        for row in colleges_data:
            state_name = str(row.get('state') or '').strip()
            city_name = str(row.get('city') or '').strip()
            if state_name and state_name not in seen_states:
                seen_states.add(state_name)
                exists_st = conn.execute("SELECT id FROM states WHERE name = ?", (state_name,)).fetchone()
                if not exists_st:
                    try:
                        conn.execute("INSERT INTO states (name, is_active) VALUES (?, TRUE)", (state_name,))
                        conn.commit()
                    except Exception:
                        try: conn.rollback()
                        except: pass

            if city_name and state_name and (city_name, state_name) not in seen_cities:
                seen_cities.add((city_name, state_name))
                state_row = conn.execute("SELECT id FROM states WHERE name = ?", (state_name,)).fetchone()
                if state_row:
                    exists_city = conn.execute("SELECT id FROM cities WHERE name = ? AND state_id = ?",
                                               (city_name, state_row['id'])).fetchone()
                    if not exists_city:
                        try:
                            conn.execute("INSERT INTO cities (name, state_id, is_active) VALUES (?, ?, TRUE)",
                                         (city_name, state_row['id']))
                            conn.commit()
                        except Exception:
                            try: conn.rollback()
                            except: pass

        # Insert colleges
        for row in colleges_data:
            name = str(row.get('college_name') or '').strip()
            if not name:
                continue
            try:
                slug = _make_slug(name)
                ex = conn.execute("SELECT id FROM colleges WHERE slug = ?", (slug,)).fetchone()
                if ex:
                    continue

                state_name = str(row.get('state') or '').strip()
                city_name = str(row.get('city') or '').strip()
                college_type = str(row.get('college_type') or 'Government Institute').strip()

                conn.execute('''INSERT INTO colleges (name, slug, category, country, state_or_region, city,
                    established_year, university_type, nmc_approved, who_approved, currency,
                    medium_of_instruction, website_url,
                    university_name, annual_intake, counselling_authority, opd, ipd,
                    bond_penalty, bed_count, prospects_url)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (name, slug, 'indian', 'India', state_name, city_name,
                     safe_int(row.get('year_of_inception')),
                     college_type,
                     1, 0, 'INR', 'English',
                     str(row.get('official_website') or '').strip(),
                     str(row.get('university_name') or '').strip(),
                     safe_int(row.get('annual_intake')),
                     str(row.get('counselling_authority') or '').strip(),
                     safe_int(row.get('opd')),
                     safe_int(row.get('ipd')),
                     str(row.get('bond_penalty') or '').strip(),
                     safe_int(row.get('bed_count')),
                     str(row.get('prospects') or '').strip()))

                new_college = conn.execute("SELECT id FROM colleges WHERE slug = ?", (slug,)).fetchone()
                if new_college:
                    course_name = str(row.get('course') or 'MBBS').strip()
                    course_level = str(row.get('course_level') or 'UG').strip()
                    conn.execute('''INSERT INTO college_courses (college_id, course_name, degree,
                        duration_years, duration_includes, intake_season)
                        VALUES (?, ?, ?, 5, 'Including Internship', 'Summer')''',
                        (new_college['id'], course_name, course_level))

                conn.commit()
                results['indian_added'] += 1
            except Exception as e:
                results['indian_errors'] += 1
                logging.warning(f"Indian import error ({name}): {e}")
                try:
                    conn.rollback()
                except Exception:
                    pass

    conn.close()
    flash(f"Import complete: {results['russian_added']} Russian + {results['indian_added']} Indian colleges added. "
          f"Errors: {results['russian_errors']} Russian, {results['indian_errors']} Indian.", "success")
    return redirect('/colleges')
