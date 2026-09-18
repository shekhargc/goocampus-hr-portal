"""Admin: import + browse the unified college master (founder 2026-09-18).

Upload the College DB workbook (Medical & Healthcare + DNB Hospitals sheets) →
pg_college_master (one row per college, per kind) + pg_college_course (course
catalogue) + a canonical alias per college. Then upload the audited matching
list → cut-off-name aliases so the already-uploaded pg_cutoffs (incl. stipend/
bond/penalty) resolve to one master college. True-admin gated. Re-uploading is
a clean rebuild (workbook first, then matching).
"""
import io
import re
import logging
import openpyxl
from flask import render_template, request, redirect, url_for, flash
from db import get_db
from core.users import get_user
from core.auth import login_required

_MASTER_COLS = {
    'College Name': 'college_name', 'University': 'university', 'Logo URL': 'logo_url',
    'City': 'city', 'State': 'state', 'District': 'district', 'Country': 'country',
    'College Type': 'college_type', 'Accreditation': 'accreditation', 'College Stream': 'college_stream',
    'Established Year': 'established_year', 'Nearest Airport': 'nearest_airport',
    'Winter Min Temp': 'winter_min_temp', 'Summer Max Temp': 'summer_max_temp',
    'Latitude': 'latitude', 'Longitude': 'longitude',
    'Mess Fee Currency': 'mess_fee_currency', 'Hostel Fee Currency': 'hostel_fee_currency',
    'OPD': 'opd', 'IPD': 'ipd', 'Bed Count': 'bed_count', 'Official Website': 'official_website',
}
_MASTER_NUM = {'Mess Fee (Min)': 'mess_fee_min', 'Mess Fee (Max)': 'mess_fee_max',
               'Hostel Fee (Min)': 'hostel_fee_min', 'Hostel Fee (Max)': 'hostel_fee_max'}
_COURSE_COLS = {'Course': 'course', 'Course Level': 'course_level', 'Course Stream': 'course_stream',
    'Seat Intake': 'seat_intake', 'Exam Type': 'exam_type', 'Entrance Exams': 'entrance_exams',
    'Entrance Exam Eligibility': 'entrance_exam_eligibility', 'Academic Eligibility': 'academic_eligibility',
    'Duration (Total Months)': 'duration_total_months', 'Duration (Years)': 'duration_years',
    'Duration (Months)': 'duration_months'}
_SHEET_KIND = {'Medical & Healthcare': 'medical', 'DNB Hospitals': 'dnb'}

# Cut-off → DB-name links NOT in the matching file (founder-confirmed 2026-09-18).
_SPECIAL_CUTOFF = {
    'Government Institute of Medical Sciences, Greater Noida':
        'Government Institute of Medical Sciences, Kasna, Greater Noida',
    'Autonomous State Medical College, Ayodhya':
        'Government Medical College, Faizabad (Ayodhya)',
}


def _s(v):
    return (str(v).strip() if v is not None else '')


def _norm(v):
    return re.sub(r'[^a-z0-9]+', ' ', _s(v).lower()).strip()


def _num(v):
    try:
        return float(str(v).replace(',', '').strip()) if _s(v) else None
    except Exception:
        return None


def _require_admin():
    u = get_user()
    return u if (u and u.get('is_admin')) else None


def _stats(conn):
    st = {}
    def c(q, *p):
        try: return conn.execute(q, p).fetchone()['n']
        except Exception: return 0
    st['medical'] = c("SELECT COUNT(*) AS n FROM pg_college_master WHERE kind='medical'")
    st['dnb'] = c("SELECT COUNT(*) AS n FROM pg_college_master WHERE kind='dnb'")
    st['master'] = st['medical'] + st['dnb']
    st['courses'] = c("SELECT COUNT(*) AS n FROM pg_college_course")
    st['aliases'] = c("SELECT COUNT(*) AS n FROM pg_college_alias")
    st['cutoff_aliases'] = c("SELECT COUNT(*) AS n FROM pg_college_alias WHERE alias_source='cutoff'")
    st['cutoff_colleges'] = c("SELECT COUNT(DISTINCT institute) AS n FROM pg_cutoffs "
                              "WHERE COALESCE(institute,'') <> ''")
    return st


@login_required
def college_master_admin():
    u = _require_admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        stats = _stats(conn)
    finally:
        conn.close()
    return render_template('pg_admin/college_master.html', stats=stats, active_section='goocampus_in')


@login_required
def college_master_upload_workbook():
    u = _require_admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    fs = request.files.get('workbook')
    if not fs or not fs.filename:
        flash('Choose the college DB workbook (.xlsx) first.', 'error')
        return redirect(url_for('pg_college_master_admin'))
    conn = get_db()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(fs.read()), read_only=True, data_only=True)
        # Clean rebuild (master ids reset, so aliases + courses go too; re-run matching after).
        conn.execute("DELETE FROM pg_college_alias")
        conn.execute("DELETE FROM pg_college_course")
        conn.execute("DELETE FROM pg_college_master")
        conn.commit()
        n_master = n_course = 0
        alias_rows = []
        for sheet, kind in _SHEET_KIND.items():
            if sheet not in wb.sheetnames:
                continue
            ws = wb[sheet]
            rows = ws.iter_rows(values_only=True)
            header = [_s(h) for h in next(rows)]
            idx = {h: i for i, h in enumerate(header)}
            seen = {}   # master_key -> master_id
            course_batch = []
            for r in rows:
                if not r:
                    continue
                name = _s(r[idx['College Name']]) if 'College Name' in idx else ''
                if not name:
                    continue
                state = _s(r[idx['State']]) if 'State' in idx else ''
                key = _norm(name) + '|' + _norm(state)
                mid = seen.get(key)
                if mid is None:
                    cols = ['kind', 'master_key']
                    vals = [kind, key]
                    for hdr, attr in _MASTER_COLS.items():
                        if hdr in idx:
                            cols.append(attr); vals.append(_s(r[idx[hdr]]))
                    for hdr, attr in _MASTER_NUM.items():
                        if hdr in idx:
                            cols.append(attr); vals.append(_num(r[idx[hdr]]))
                    ph = ','.join(['?'] * len(cols))
                    mid = conn.execute(
                        f"INSERT INTO pg_college_master ({','.join(cols)}) VALUES ({ph}) RETURNING id",
                        vals).fetchone()['id']
                    seen[key] = mid
                    n_master += 1
                    alias_rows.append((mid, name, _norm(name), 'canonical'))
                # course row
                cv = [mid]
                for hdr, attr in _COURSE_COLS.items():
                    cv.append(_s(r[idx[hdr]]) if hdr in idx else '')
                if any(cv[1:]):
                    course_batch.append(cv)
            if course_batch:
                ccols = 'master_id,' + ','.join(_COURSE_COLS.values())
                cph = ','.join(['?'] * (1 + len(_COURSE_COLS)))
                conn.execute_batch(f"INSERT INTO pg_college_course ({ccols}) VALUES ({cph})",
                                   course_batch, page_size=1000)
                n_course += len(course_batch)
        wb.close()
        if alias_rows:
            conn.execute_batch(
                "INSERT INTO pg_college_alias (master_id, alias_name, alias_key, alias_source) "
                "VALUES (?,?,?,?)", alias_rows, page_size=1000)
        conn.commit()
        flash(f'Imported {n_master} colleges + {n_course} courses. Now upload the matching list to link cut-offs.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"college_master_upload_workbook: {e}")
        flash(f'Import failed: {e}', 'error')
    finally:
        try: conn.close()
        except Exception: pass
    return redirect(url_for('pg_college_master_admin'))


@login_required
def college_master_upload_matching():
    u = _require_admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    fs = request.files.get('matching')
    if not fs or not fs.filename:
        flash('Choose the matching list (.xlsx) first.', 'error')
        return redirect(url_for('pg_college_master_admin'))
    conn = get_db()
    try:
        # canonical name -> master_id (prefer medical when a name is in both kinds)
        name2mid = {}
        for row in conn.execute("SELECT master_id, alias_key, "
                                "(SELECT kind FROM pg_college_master m WHERE m.id = a.master_id) AS kind "
                                "FROM pg_college_alias a WHERE alias_source='canonical'").fetchall():
            k = row['alias_key']
            if k not in name2mid or row['kind'] == 'medical':
                name2mid[k] = row['master_id']
        if not name2mid:
            conn.close()
            flash('Upload the college DB workbook first.', 'error')
            return redirect(url_for('pg_college_master_admin'))

        wb = openpyxl.load_workbook(io.BytesIO(fs.read()), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True)); wb.close()
        hr = next(i for i, r in enumerate(rows[:6]) if r and any(_s(c) == 'Match Type' for c in r))
        hdr = [_s(c) for c in rows[hr]]
        ci = hdr.index('Cut-off (Master) College Name'); di = hdr.index('DB Matched College Name')
        pairs = {}   # cut-off name -> DB name
        for r in rows[hr + 1:]:
            if r and _s(r[ci]):
                pairs[_s(r[ci])] = _s(r[di])
        for cut, db in _SPECIAL_CUTOFF.items():
            pairs.setdefault(cut, db)

        # distinct cut-off institutes actually in the cut-off data
        cut_names = [r['institute'] for r in
                     conn.execute("SELECT DISTINCT institute FROM pg_cutoffs "
                                  "WHERE COALESCE(institute,'') <> ''").fetchall()]
        conn.execute("DELETE FROM pg_college_alias WHERE alias_source='cutoff'")
        linked, leftover = [], []
        for cut in cut_names:
            db = pairs.get(cut, cut)          # matching-file DB name, else the cut-off name itself
            mid = name2mid.get(_norm(db)) or name2mid.get(_norm(cut))
            if mid:
                linked.append((mid, cut, _norm(cut), 'cutoff'))
            else:
                leftover.append(cut)
        if linked:
            conn.execute_batch(
                "INSERT INTO pg_college_alias (master_id, alias_name, alias_key, alias_source) "
                "VALUES (?,?,?,?)", linked, page_size=1000)
        conn.commit()
        msg = f'Linked {len(linked)} of {len(cut_names)} cut-off colleges to the master.'
        if leftover:
            msg += ' Unlinked: ' + '; '.join(leftover[:8]) + (' …' if len(leftover) > 8 else '')
            flash(msg, 'info')
        else:
            flash(msg + ' 100% linked ✓', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"college_master_upload_matching: {e}")
        flash(f'Matching import failed: {e}', 'error')
    finally:
        try: conn.close()
        except Exception: pass
    return redirect(url_for('pg_college_master_admin'))
