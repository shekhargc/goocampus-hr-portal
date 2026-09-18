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
    # Fixed master column order (so every college inserts with the same shape and
    # we can BULK-insert instead of one round-trip per row → no request timeout).
    master_attrs = list(_MASTER_COLS.values()) + list(_MASTER_NUM.values())
    conn = get_db()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(fs.read()), read_only=True, data_only=True)
        # --- Pass 1: parse both sheets in memory (no DB yet) ---
        masters = {}       # (kind, master_key) -> [name, *fixed-order values]
        courses_raw = []   # list of ((kind, master_key), [course values])
        for sheet, kind in _SHEET_KIND.items():
            if sheet not in wb.sheetnames:
                continue
            ws = wb[sheet]
            rows = ws.iter_rows(values_only=True)
            idx = {h: i for i, h in enumerate([_s(h) for h in next(rows)])}
            for r in rows:
                if not r:
                    continue
                name = _s(r[idx['College Name']]) if 'College Name' in idx else ''
                if not name:
                    continue
                state = _s(r[idx['State']]) if 'State' in idx else ''
                mkey = _norm(name) + '|' + _norm(state)
                gkey = (kind, mkey)
                if gkey not in masters:
                    vals = [name]
                    for hdr in _MASTER_COLS:
                        vals.append(_s(r[idx[hdr]]) if hdr in idx else '')
                    for hdr in _MASTER_NUM:
                        vals.append(_num(r[idx[hdr]]) if hdr in idx else None)
                    masters[gkey] = vals
                cv = [_s(r[idx[hdr]]) if hdr in idx else '' for hdr in _COURSE_COLS]
                if any(cv):
                    courses_raw.append((gkey, cv))
        wb.close()

        # --- Clean rebuild, then bulk write (few round-trips total) ---
        conn.execute("DELETE FROM pg_college_alias")
        conn.execute("DELETE FROM pg_college_course")
        conn.execute("DELETE FROM pg_college_master")

        mcols = 'kind,master_key,' + ','.join(master_attrs)
        mph = ','.join(['?'] * (2 + len(master_attrs)))
        master_batch = [[k[0], k[1]] + v[1:] for k, v in masters.items()]
        conn.execute_batch(f"INSERT INTO pg_college_master ({mcols}) VALUES ({mph})",
                           master_batch, page_size=1000)

        idmap = {(row['kind'], row['master_key']): row['id']
                 for row in conn.execute("SELECT id, kind, master_key FROM pg_college_master").fetchall()}

        alias_rows = [(idmap[k], v[0], _norm(v[0]), 'canonical') for k, v in masters.items()]
        conn.execute_batch(
            "INSERT INTO pg_college_alias (master_id, alias_name, alias_key, alias_source) "
            "VALUES (?,?,?,?)", alias_rows, page_size=1000)

        course_batch = [[idmap[gkey]] + cv for gkey, cv in courses_raw]
        ccols = 'master_id,' + ','.join(_COURSE_COLS.values())
        cph = ','.join(['?'] * (1 + len(_COURSE_COLS)))
        conn.execute_batch(f"INSERT INTO pg_college_course ({ccols}) VALUES ({cph})",
                           course_batch, page_size=1000)
        conn.commit()
        flash(f'Imported {len(master_batch)} colleges + {len(course_batch)} courses. '
              'Now upload the matching list to link cut-offs.', 'success')
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
