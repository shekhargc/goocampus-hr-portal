"""International Career dashboard: Phase 2 + 3 (founder 2026-11-19).

Phase 2: the doctor's own career file, shared by every country pathway.
  · "What are you planning?": NEET-PG / international / both / undecided + target countries (pg_career_plan)
  · My Documents: the doctor uploads passport, degree, internship, registration, experience letters…
    (pg_doctor_documents; files in R2 under career-docs/<user_id>/…, never on Render's disk; download = a
    120-second signed link). A doctor removing a document only hides it (deleted_at); the file is kept.
  · Portfolio: structured entries per section (education, experience, licences, exams, publications,
    conferences, courses, skills, languages, awards) in pg_portfolio. The section blueprint (fields + types)
    is served with the data, so the website renders the forms generically (same idea as the profile blueprint).
  · CV: GET /api/pg/my/cv assembles profile + portfolio into one CV object; the website renders/prints it.
Phase 3: Conferences & Events: team-managed list (pg_conferences, admin page /admin/pg/conferences);
  doctors filter by country / speciality and mark interested / attending / attended (pg_conference_saves).
  "Attended" can be copied into the portfolio's Conferences section.

Same doctor login (X-PG-Key + Bearer) and the same International gate as the e-books / planner.
"""
import hashlib
import json
import logging
import re
import uuid
from datetime import date

from flask import request, jsonify

from db import get_db

logger = logging.getLogger(__name__)
_READY = {'done': False}

PLANS = {'neet_pg': 'NEET-PG in India', 'international': 'Work or train abroad',
         'both': 'Both: NEET-PG and abroad', 'undecided': 'Not sure yet'}
COUNTRIES = {'uae': 'UAE', 'saudi': 'Saudi Arabia', 'australia': 'Australia', 'uk': 'United Kingdom',
             'qatar': 'Qatar', 'oman': 'Oman', 'other': 'Other'}

# What a doctor typically needs for licensing / PSV abroad. 'core' = shown as the checklist.
DOC_TYPES = [
    ('passport', 'Passport (first + last page)', True),
    ('photo', 'Passport-size photo (white background)', True),
    ('mbbs_degree', 'MBBS degree certificate', True),
    ('mbbs_marks', 'MBBS mark sheets / transcript', True),
    ('internship', 'Internship completion certificate', True),
    ('registration', 'Medical council registration (NMC / State)', True),
    ('good_standing', 'Good Standing certificate', True),
    ('experience', 'Experience letters (each job)', True),
    ('pg_degree', 'PG degree (MD / MS / DNB)', False),
    ('pg_registration', 'PG registration (additional qualification)', False),
    ('bls', 'BLS / life-support certificate (valid)', False),
    ('english_test', 'English test result (OET / IELTS)', False),
    ('licence_exam', 'Licensing exam result (e.g. DHA / Prometric)', False),
    ('dataflow', 'DataFlow (PSV) verification report', False),
    ('cv', 'CV (signed)', False),
    ('contract', 'Job offer / employment contract', False),
    ('police', 'Police clearance certificate', False),
    ('other', 'Other document', False),
]
_DOC_CODES = {c for c, _l, _k in DOC_TYPES}
_ALLOWED = {'application/pdf': 'pdf', 'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}
MAX_DOC_BYTES = 10 * 1024 * 1024

# Portfolio blueprint: field types text | textarea | month (YYYY-MM) | year | number | url | select | tags
PORTFOLIO = [
    {'key': 'education', 'label': 'Education', 'fields': [
        {'key': 'degree', 'label': 'Degree', 'type': 'select', 'options': ['MBBS', 'MD', 'MS', 'DNB', 'DM', 'MCh', 'Diploma', 'Fellowship', 'Other'], 'required': True},
        {'key': 'speciality', 'label': 'Speciality (for PG)', 'type': 'text'},
        {'key': 'institution', 'label': 'College / institution', 'type': 'text', 'required': True},
        {'key': 'university', 'label': 'University', 'type': 'text'},
        {'key': 'from', 'label': 'From', 'type': 'month'}, {'key': 'to', 'label': 'To', 'type': 'month'},
        {'key': 'note', 'label': 'Notes (thesis, distinctions)', 'type': 'textarea'}]},
    {'key': 'experience', 'label': 'Clinical experience', 'fields': [
        {'key': 'role', 'label': 'Role / designation', 'type': 'text', 'required': True},
        {'key': 'department', 'label': 'Department', 'type': 'text'},
        {'key': 'hospital', 'label': 'Hospital', 'type': 'text', 'required': True},
        {'key': 'city', 'label': 'City', 'type': 'text'},
        {'key': 'from', 'label': 'From', 'type': 'month', 'required': True},
        {'key': 'to', 'label': 'To (blank = current)', 'type': 'month'},
        {'key': 'duties', 'label': 'Main duties / procedures', 'type': 'textarea'}]},
    {'key': 'licences', 'label': 'Registrations & licences', 'fields': [
        {'key': 'body', 'label': 'Council / regulator', 'type': 'text', 'required': True},
        {'key': 'number', 'label': 'Registration no.', 'type': 'text'},
        {'key': 'kind', 'label': 'Type', 'type': 'select', 'options': ['Permanent', 'Provisional', 'Eligibility letter', 'Licence', 'Other']},
        {'key': 'issued', 'label': 'Issued', 'type': 'month'}, {'key': 'valid_to', 'label': 'Valid until', 'type': 'month'}]},
    {'key': 'exams', 'label': 'Exams & English tests', 'fields': [
        {'key': 'exam', 'label': 'Exam', 'type': 'text', 'required': True},
        {'key': 'result', 'label': 'Score / result', 'type': 'text'},
        {'key': 'date', 'label': 'Date', 'type': 'month'}, {'key': 'valid_to', 'label': 'Valid until', 'type': 'month'}]},
    {'key': 'publications', 'label': 'Publications & research', 'fields': [
        {'key': 'title', 'label': 'Title', 'type': 'text', 'required': True},
        {'key': 'journal', 'label': 'Journal / venue', 'type': 'text'},
        {'key': 'year', 'label': 'Year', 'type': 'year'}, {'key': 'role', 'label': 'Your role (author no.)', 'type': 'text'},
        {'key': 'link', 'label': 'Link / DOI', 'type': 'url'}]},
    {'key': 'conferences', 'label': 'Conferences & presentations', 'fields': [
        {'key': 'name', 'label': 'Conference', 'type': 'text', 'required': True},
        {'key': 'kind', 'label': 'Participation', 'type': 'select', 'options': ['Attended', 'Poster', 'Oral paper', 'Speaker', 'Organiser']},
        {'key': 'place', 'label': 'City / country', 'type': 'text'}, {'key': 'date', 'label': 'Date', 'type': 'month'},
        {'key': 'cpd', 'label': 'CPD / CME points', 'type': 'number'}]},
    {'key': 'courses', 'label': 'Courses & certifications', 'fields': [
        {'key': 'name', 'label': 'Course (BLS, ACLS, …)', 'type': 'text', 'required': True},
        {'key': 'provider', 'label': 'Provider', 'type': 'text'},
        {'key': 'date', 'label': 'Completed', 'type': 'month'}, {'key': 'valid_to', 'label': 'Valid until', 'type': 'month'}]},
    {'key': 'skills', 'label': 'Clinical skills & procedures', 'fields': [
        {'key': 'skill', 'label': 'Skill / procedure', 'type': 'text', 'required': True},
        {'key': 'level', 'label': 'Level', 'type': 'select', 'options': ['Observed', 'Assisted', 'Performed under supervision', 'Independent']},
        {'key': 'count', 'label': 'Approx. number done', 'type': 'number'}]},
    {'key': 'languages', 'label': 'Languages', 'fields': [
        {'key': 'language', 'label': 'Language', 'type': 'text', 'required': True},
        {'key': 'level', 'label': 'Level', 'type': 'select', 'options': ['Basic', 'Conversational', 'Fluent', 'Native']}]},
    {'key': 'awards', 'label': 'Awards & achievements', 'fields': [
        {'key': 'title', 'label': 'Award', 'type': 'text', 'required': True},
        {'key': 'by', 'label': 'Given by', 'type': 'text'}, {'key': 'year', 'label': 'Year', 'type': 'year'}]},
]
_SECTIONS = {s['key']: s for s in PORTFOLIO}
CONF_STATUSES = ('interested', 'attending', 'attended')


def ensure(conn):
    if _READY['done']:
        return
    conn.execute("SET LOCAL lock_timeout = '3s'")
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_career_plan (
        user_id INTEGER PRIMARY KEY, plan TEXT DEFAULT '', countries TEXT DEFAULT '[]', note TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_doctor_documents (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, doc_type TEXT NOT NULL, title TEXT DEFAULT '',
        r2_key TEXT NOT NULL, file_name TEXT DEFAULT '', content_type TEXT DEFAULT '', size INTEGER DEFAULT 0,
        sha256 TEXT DEFAULT '', issued_on DATE, expires_on DATE, note TEXT DEFAULT '', deleted_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_doctor_documents_user ON pg_doctor_documents (user_id)")
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_portfolio (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, section TEXT NOT NULL, data TEXT DEFAULT '{}',
        sort_order INTEGER DEFAULT 0, deleted_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_portfolio_user ON pg_portfolio (user_id)")
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_conferences (
        id SERIAL PRIMARY KEY, title TEXT NOT NULL, country TEXT DEFAULT '', city TEXT DEFAULT '', venue TEXT DEFAULT '',
        start_date DATE, end_date DATE, speciality TEXT DEFAULT '', organiser TEXT DEFAULT '', url TEXT DEFAULT '',
        cpd_points TEXT DEFAULT '', fee TEXT DEFAULT '', mode TEXT DEFAULT 'in_person', abstract_deadline DATE,
        description TEXT DEFAULT '', is_active BOOLEAN DEFAULT TRUE, created_by TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_conference_saves (
        user_id INTEGER NOT NULL, conference_id INTEGER NOT NULL, status TEXT DEFAULT 'interested',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (user_id, conference_id))''')
    conn.commit()
    _READY['done'] = True


def _gated(conn):
    from pg_admin import ebooks as EB
    u, err = EB._doctor(conn)
    if err:
        return None, err
    if not EB.gate(conn, u)[0]:
        return None, (jsonify({'ok': False, 'error': 'not_found'}), 404)
    return u, None


def _run(fn):
    """Open a connection, ensure tables, check the doctor + gate, run fn(conn, u) → response."""
    conn = get_db()
    try:
        ensure(conn)
        u, err = _gated(conn)
        if err:
            return err
        return fn(conn, u)
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("career api %s: %s", request.path, e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def _d(v):
    s = str(v or '').strip()[:10]
    return s if re.match(r'^\d{4}-\d{2}-\d{2}$', s) else None


def _iso(v):
    return v.isoformat() if hasattr(v, 'isoformat') else (str(v) if v else None)


# ── "What are you planning?" ─────────────────────────────────────────────────
def api_plan():
    """GET/POST /api/pg/career/plan {plan: neet_pg|international|both|undecided, countries:[uae,…], note?}"""
    def go(conn, u):
        if request.method == 'POST':
            d = request.get_json(silent=True) or {}
            plan = str(d.get('plan') or '')
            if plan not in PLANS:
                return jsonify({'ok': False, 'error': 'bad_plan'}), 400
            cs = [c for c in (d.get('countries') or []) if c in COUNTRIES][:7]
            conn.execute("INSERT INTO pg_career_plan (user_id, plan, countries, note) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT (user_id) DO UPDATE SET plan = EXCLUDED.plan, countries = EXCLUDED.countries, "
                         "note = EXCLUDED.note, updated_at = CURRENT_TIMESTAMP",
                         (u['id'], plan, json.dumps(cs), str(d.get('note') or '')[:500]))
            conn.commit()
        r = conn.execute("SELECT * FROM pg_career_plan WHERE user_id = ?", (u['id'],)).fetchone()
        return jsonify({'ok': True, 'options': [{'code': k, 'label': v} for k, v in PLANS.items()],
                        'countries_options': [{'code': k, 'label': v} for k, v in COUNTRIES.items()],
                        'plan': r['plan'] if r else None, 'countries': json.loads(r['countries'] or '[]') if r else [],
                        'note': r['note'] if r else '', 'updated_at': _iso(r['updated_at']) if r else None})
    return _run(go)


# ── My Documents ─────────────────────────────────────────────────────────────
def _doc_out(r):
    return {'id': r['id'], 'doc_type': r['doc_type'], 'title': r['title'], 'file_name': r['file_name'],
            'content_type': r['content_type'], 'size': r['size'], 'issued_on': _iso(r['issued_on']),
            'expires_on': _iso(r['expires_on']), 'note': r['note'] or '', 'uploaded_at': _iso(r['created_at']),
            'expired': bool(r['expires_on'] and r['expires_on'] < date.today())}


def api_documents():
    """GET /api/pg/my/documents → {doc_types, documents, checklist}.
    POST (multipart: file, doc_type, title?, issued_on?, expires_on?, note?) → stores one document (≤10 MB, PDF/JPG/PNG/WEBP)."""
    def go(conn, u):
        if request.method == 'POST':
            f = request.files.get('file')
            dt = (request.form.get('doc_type') or '').strip()
            if dt not in _DOC_CODES:
                return jsonify({'ok': False, 'error': 'bad_doc_type'}), 400
            if not f:
                return jsonify({'ok': False, 'error': 'no_file'}), 400
            data = f.read(MAX_DOC_BYTES + 1)
            if len(data) > MAX_DOC_BYTES:
                return jsonify({'ok': False, 'error': 'too_big', 'max_mb': MAX_DOC_BYTES // (1024 * 1024)}), 400
            ctype = _sniff(data)
            if not ctype:
                return jsonify({'ok': False, 'error': 'bad_file_type', 'allowed': ['pdf', 'jpg', 'png', 'webp']}), 400
            from core import storage
            if not storage.is_configured():
                return jsonify({'ok': False, 'error': 'storage_unavailable'}), 503
            key = f"career-docs/{u['id']}/{dt}/{uuid.uuid4().hex}.{_ALLOWED[ctype]}"
            if not storage.upload_bytes(key, data, ctype):
                return jsonify({'ok': False, 'error': 'upload_failed'}), 502
            name = re.sub(r'[^\w.\- ()]+', '_', f.filename or f'{dt}.{_ALLOWED[ctype]}')[:150]
            label = dict((c, l) for c, l, _k in DOC_TYPES)[dt]
            new_id = conn.execute(
                "INSERT INTO pg_doctor_documents (user_id, doc_type, title, r2_key, file_name, content_type, size, sha256, "
                "issued_on, expires_on, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?::date, ?::date, ?) RETURNING id",
                (u['id'], dt, (request.form.get('title') or label).strip()[:200], key, name, ctype, len(data),
                 hashlib.sha256(data).hexdigest(), _d(request.form.get('issued_on')), _d(request.form.get('expires_on')),
                 (request.form.get('note') or '').strip()[:500])).fetchone()['id']
            conn.commit()
            r = conn.execute("SELECT * FROM pg_doctor_documents WHERE id = ?", (new_id,)).fetchone()
            return jsonify({'ok': True, 'document': _doc_out(r)})
        docs = [_doc_out(r) for r in conn.execute(
            "SELECT * FROM pg_doctor_documents WHERE user_id = ? AND deleted_at IS NULL ORDER BY doc_type, created_at DESC",
            (u['id'],)).fetchall()]
        have = {}
        for x in docs:
            have[x['doc_type']] = have.get(x['doc_type'], 0) + 1
        types = [{'code': c, 'label': l, 'core': k, 'count': have.get(c, 0)} for c, l, k in DOC_TYPES]
        core = [t for t in types if t['core']]
        return jsonify({'ok': True, 'doc_types': types, 'documents': docs,
                        'checklist': {'done': sum(1 for t in core if t['count']), 'total': len(core),
                                      'missing': [t['code'] for t in core if not t['count']]},
                        'max_mb': MAX_DOC_BYTES // (1024 * 1024)})
    return _run(go)


def _sniff(b):
    if b[:5] == b'%PDF-':
        return 'application/pdf'
    if b[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if b[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if b[:4] == b'RIFF' and b[8:12] == b'WEBP':
        return 'image/webp'
    return None


def api_document(doc_id):
    """POST /api/pg/my/documents/<id> {title?, doc_type?, issued_on?, expires_on?, note?} edit details;
    DELETE → removed from the doctor's list (the stored file is kept)."""
    def go(conn, u):
        r = conn.execute("SELECT * FROM pg_doctor_documents WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
                         (doc_id, u['id'])).fetchone()
        if not r:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        if request.method == 'DELETE':
            conn.execute("UPDATE pg_doctor_documents SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?", (doc_id,))
            conn.commit()
            return jsonify({'ok': True})
        d = request.get_json(silent=True) or {}
        dt = d.get('doc_type') if d.get('doc_type') in _DOC_CODES else r['doc_type']
        conn.execute("UPDATE pg_doctor_documents SET doc_type = ?, title = ?, issued_on = ?::date, expires_on = ?::date, "
                     "note = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (dt, str(d.get('title') if 'title' in d else r['title'])[:200],
                      _d(d['issued_on']) if 'issued_on' in d else _iso(r['issued_on']),
                      _d(d['expires_on']) if 'expires_on' in d else _iso(r['expires_on']),
                      str(d.get('note') if 'note' in d else r['note'] or '')[:500], doc_id))
        conn.commit()
        return jsonify({'ok': True, 'document': _doc_out(conn.execute(
            "SELECT * FROM pg_doctor_documents WHERE id = ?", (doc_id,)).fetchone())})
    return _run(go)


def api_document_file(doc_id):
    """GET /api/pg/my/documents/<id>/file → {url} a 120-second signed link to the doctor's own file."""
    def go(conn, u):
        r = conn.execute("SELECT r2_key, file_name FROM pg_doctor_documents WHERE id = ? AND user_id = ? "
                         "AND deleted_at IS NULL", (doc_id, u['id'])).fetchone()
        if not r:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        from core import storage
        url = storage.presigned_get_url(r['r2_key'], ttl_seconds=120)
        if not url:
            return jsonify({'ok': False, 'error': 'storage_unavailable'}), 503
        return jsonify({'ok': True, 'url': url, 'file_name': r['file_name'], 'expires_in': 120})
    return _run(go)


# ── Portfolio ────────────────────────────────────────────────────────────────
def _clean(section, data):
    """Keep only blueprint fields, trimmed; returns (clean, missing_required)."""
    out, missing = {}, []
    for f in _SECTIONS[section]['fields']:
        v = data.get(f['key'])
        if f['type'] == 'number':
            try:
                v = float(v) if str(v).strip() != '' else None
                v = int(v) if v is not None and v.is_integer() else v
            except (TypeError, ValueError):
                v = None
        elif f['type'] == 'select':
            v = v if v in f.get('options', []) else None
        else:
            v = str(v or '').strip()[:2000 if f['type'] == 'textarea' else 250] or None
            if v and f['type'] == 'month' and not re.match(r'^\d{4}-\d{2}$', v):
                v = None
            if v and f['type'] == 'year' and not re.match(r'^\d{4}$', v):
                v = None
        if v is not None:
            out[f['key']] = v
        elif f.get('required'):
            missing.append(f['key'])
    return out, missing


def _items(conn, uid):
    items = {s['key']: [] for s in PORTFOLIO}
    for r in conn.execute("SELECT id, section, data, sort_order, updated_at FROM pg_portfolio WHERE user_id = ? "
                          "AND deleted_at IS NULL ORDER BY section, sort_order, id", (uid,)).fetchall():
        if r['section'] in items:
            items[r['section']].append({'id': r['id'], **json.loads(r['data'] or '{}')})
    return items


def api_portfolio():
    """GET /api/pg/my/portfolio → {sections:[blueprint], items:{section:[{id,…}]}}.
    POST {id?, section, data:{…}, sort_order?} → add or edit one entry."""
    def go(conn, u):
        if request.method == 'POST':
            d = request.get_json(silent=True) or {}
            sec = d.get('section')
            if sec not in _SECTIONS:
                return jsonify({'ok': False, 'error': 'bad_section'}), 400
            clean, missing = _clean(sec, d.get('data') or {})
            if missing:
                return jsonify({'ok': False, 'error': 'missing_fields', 'fields': missing}), 400
            so = int(d.get('sort_order') or 0) if str(d.get('sort_order') or '0').lstrip('-').isdigit() else 0
            if d.get('id'):
                n = conn.execute("UPDATE pg_portfolio SET data = ?, sort_order = ?, updated_at = CURRENT_TIMESTAMP "
                                 "WHERE id = ? AND user_id = ? AND section = ? AND deleted_at IS NULL RETURNING id",
                                 (json.dumps(clean), so, int(d['id']), u['id'], sec)).fetchone()
                if not n:
                    return jsonify({'ok': False, 'error': 'not_found'}), 404
            else:
                if conn.execute("SELECT COUNT(*) AS n FROM pg_portfolio WHERE user_id = ? AND deleted_at IS NULL",
                                (u['id'],)).fetchone()['n'] >= 300:
                    return jsonify({'ok': False, 'error': 'too_many'}), 400
                conn.execute("INSERT INTO pg_portfolio (user_id, section, data, sort_order) VALUES (?, ?, ?, ?)",
                             (u['id'], sec, json.dumps(clean), so))
            conn.commit()
        return jsonify({'ok': True, 'sections': PORTFOLIO, 'items': _items(conn, u['id'])})
    return _run(go)


def api_portfolio_item(item_id):
    """DELETE /api/pg/my/portfolio/<id> → removes the entry from the doctor's portfolio."""
    def go(conn, u):
        n = conn.execute("UPDATE pg_portfolio SET deleted_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ? "
                         "AND deleted_at IS NULL RETURNING id", (item_id, u['id'])).fetchone()
        conn.commit()
        if not n:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        return jsonify({'ok': True, 'items': _items(conn, u['id'])})
    return _run(go)


# ── CV ───────────────────────────────────────────────────────────────────────
def _sort_dated(rows):
    """Newest first; an entry with no end month (current job / course) counts as ongoing."""
    return sorted(rows, key=lambda x: (x.get('to') or '9999-99', x.get('from') or ''), reverse=True)


def api_cv():
    """GET /api/pg/my/cv → one CV object (profile + portfolio, newest first) for the website's CV builder."""
    def go(conn, u):
        from core.helpers import format_dr_name
        items = _items(conn, u['id'])
        for k in ('education', 'experience'):
            items[k] = _sort_dated(items[k])
        plan = conn.execute("SELECT plan, countries FROM pg_career_plan WHERE user_id = ?", (u['id'],)).fetchone()
        prof = {
            'name': format_dr_name(u.get('name') or ''), 'email': u.get('email') or '', 'mobile': u.get('mobile') or '',
            'city': u.get('city') or '', 'state': u.get('state') or '', 'photo_url': u.get('photo_url') or '',
            'mbbs_college': u.get('college') or '', 'mbbs_year': u.get('mbbs_year') or '',
            'internship_done': u.get('internship_done'), 'neet_pg_year': u.get('neet_pg_year') or '',
            'target_speciality': u.get('target_speciality') or ''}
        sections = [{'key': s['key'], 'label': s['label'], 'items': items[s['key']]} for s in PORTFOLIO if items[s['key']]]
        return jsonify({'ok': True, 'profile': prof, 'sections': sections,
                        'target_countries': [COUNTRIES.get(c, c) for c in json.loads(plan['countries'] or '[]')] if plan else [],
                        'empty': not sections})
    return _run(go)


# ── Conferences & Events ─────────────────────────────────────────────────────
def _conf_out(r, mine=None):
    return {'id': r['id'], 'title': r['title'], 'country': r['country'], 'city': r['city'], 'venue': r['venue'],
            'start_date': _iso(r['start_date']), 'end_date': _iso(r['end_date']), 'speciality': r['speciality'],
            'organiser': r['organiser'], 'url': r['url'], 'cpd_points': r['cpd_points'], 'fee': r['fee'],
            'mode': r['mode'], 'abstract_deadline': _iso(r['abstract_deadline']), 'description': r['description'],
            'my_status': mine}


def api_conferences():
    """GET /api/pg/career/conferences?country=&speciality=&past=1 → upcoming (or past) events + the doctor's marks."""
    def go(conn, u):
        where, p = ["is_active"], []
        if request.args.get('past') in ('1', 'true'):
            where.append("COALESCE(end_date, start_date) < CURRENT_DATE")
        else:
            where.append("(COALESCE(end_date, start_date) IS NULL OR COALESCE(end_date, start_date) >= CURRENT_DATE)")
        if request.args.get('country'):
            where.append("country = ?"); p.append(request.args['country'].strip().lower())
        if request.args.get('speciality'):
            where.append("speciality ILIKE ?"); p.append('%' + request.args['speciality'].strip()[:60] + '%')
        mine = {r['conference_id']: r['status'] for r in conn.execute(
            "SELECT conference_id, status FROM pg_conference_saves WHERE user_id = ?", (u['id'],)).fetchall()}
        rows = conn.execute("SELECT * FROM pg_conferences WHERE " + " AND ".join(where) +
                            " ORDER BY start_date NULLS LAST, id LIMIT 300", p).fetchall()
        return jsonify({'ok': True, 'conferences': [_conf_out(r, mine.get(r['id'])) for r in rows],
                        'countries': [{'code': k, 'label': v} for k, v in COUNTRIES.items()]})
    return _run(go)


def api_conference_mark(conf_id):
    """POST /api/pg/career/conferences/<id> {status: interested|attending|attended|'' (clear), add_to_portfolio?}"""
    def go(conn, u):
        c = conn.execute("SELECT * FROM pg_conferences WHERE id = ? AND is_active", (conf_id,)).fetchone()
        if not c:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        d = request.get_json(silent=True) or {}
        st = str(d.get('status') or '')
        if st and st not in CONF_STATUSES:
            return jsonify({'ok': False, 'error': 'bad_status'}), 400
        if st:
            conn.execute("INSERT INTO pg_conference_saves (user_id, conference_id, status) VALUES (?, ?, ?) "
                         "ON CONFLICT (user_id, conference_id) DO UPDATE SET status = EXCLUDED.status, "
                         "updated_at = CURRENT_TIMESTAMP", (u['id'], conf_id, st))
        else:
            conn.execute("DELETE FROM pg_conference_saves WHERE user_id = ? AND conference_id = ?", (u['id'], conf_id))
        added = False
        if st == 'attended' and d.get('add_to_portfolio'):
            entry = {'name': c['title'], 'kind': 'Attended',
                     'place': ', '.join(x for x in (c['city'], COUNTRIES.get(c['country'], c['country'])) if x),
                     'date': c['start_date'].strftime('%Y-%m') if c['start_date'] else None}
            try:
                entry['cpd'] = float(c['cpd_points']) if c['cpd_points'] else None
            except ValueError:
                entry['cpd'] = None
            clean, _m = _clean('conferences', entry)
            conn.execute("INSERT INTO pg_portfolio (user_id, section, data) VALUES (?, 'conferences', ?)",
                         (u['id'], json.dumps(clean)))
            added = True
        conn.commit()
        return jsonify({'ok': True, 'status': st or None, 'added_to_portfolio': added})
    return _run(go)


# ── admin: Conferences & Events ──────────────────────────────────────────────
def admin_conferences():
    from flask import render_template, redirect, url_for, flash
    from pg_admin.ebooks import _admin
    a = _admin()
    if not a:
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        ensure(conn)
        if request.method == 'POST':
            f = request.form
            vals = ((f.get('title') or '').strip()[:250], (f.get('country') or '').strip().lower()[:20],
                    (f.get('city') or '').strip()[:120], (f.get('venue') or '').strip()[:200], _d(f.get('start_date')),
                    _d(f.get('end_date')), (f.get('speciality') or '').strip()[:120], (f.get('organiser') or '').strip()[:200],
                    (f.get('url') or '').strip()[:500], (f.get('cpd_points') or '').strip()[:40],
                    (f.get('fee') or '').strip()[:120], f.get('mode') if f.get('mode') in ('in_person', 'online', 'hybrid') else 'in_person',
                    _d(f.get('abstract_deadline')), (f.get('description') or '').strip()[:2000], f.get('is_active') == '1',
                    a.get('name') or 'admin')
            if not vals[0]:
                flash('Title is required.', 'error')
            elif f.get('id'):
                conn.execute("UPDATE pg_conferences SET title=?, country=?, city=?, venue=?, start_date=?::date, "
                             "end_date=?::date, speciality=?, organiser=?, url=?, cpd_points=?, fee=?, mode=?, "
                             "abstract_deadline=?::date, description=?, is_active=?, created_by=?, "
                             "updated_at=CURRENT_TIMESTAMP WHERE id=?", vals + (int(f['id']),))
                conn.commit(); flash('Event saved.', 'success')
            else:
                conn.execute("INSERT INTO pg_conferences (title, country, city, venue, start_date, end_date, speciality, "
                             "organiser, url, cpd_points, fee, mode, abstract_deadline, description, is_active, created_by) "
                             "VALUES (?,?,?,?,?::date,?::date,?,?,?,?,?,?,?::date,?,?,?)", vals)
                conn.commit(); flash('Event added.', 'success')
            return redirect(url_for('pg_conferences_admin'))
        rows = [dict(r) for r in conn.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM pg_conference_saves s WHERE s.conference_id = c.id) AS saves "
            "FROM pg_conferences c ORDER BY (COALESCE(c.end_date, c.start_date) < CURRENT_DATE), c.start_date NULLS LAST, c.id"
        ).fetchall()]
        return render_template('pg_admin/conferences.html', rows=rows, countries=COUNTRIES,
                               today=date.today(), active_section='goocampus_in')
    finally:
        conn.close()


def register(app):
    from core.auth import login_required
    app.add_url_rule('/api/pg/career/plan', 'api_pg_career_plan', api_plan, methods=['GET', 'POST'])
    app.add_url_rule('/api/pg/my/documents', 'api_pg_my_documents', api_documents, methods=['GET', 'POST'])
    app.add_url_rule('/api/pg/my/documents/<int:doc_id>', 'api_pg_my_document', api_document, methods=['POST', 'DELETE'])
    app.add_url_rule('/api/pg/my/documents/<int:doc_id>/file', 'api_pg_my_document_file', api_document_file,
                     methods=['GET'])
    app.add_url_rule('/api/pg/my/portfolio', 'api_pg_my_portfolio', api_portfolio, methods=['GET', 'POST'])
    app.add_url_rule('/api/pg/my/portfolio/<int:item_id>', 'api_pg_my_portfolio_item', api_portfolio_item,
                     methods=['DELETE'])
    app.add_url_rule('/api/pg/my/cv', 'api_pg_my_cv', api_cv, methods=['GET'])
    app.add_url_rule('/api/pg/career/conferences', 'api_pg_career_conferences', api_conferences, methods=['GET'])
    app.add_url_rule('/api/pg/career/conferences/<int:conf_id>', 'api_pg_career_conference', api_conference_mark,
                     methods=['POST'])
    app.add_url_rule('/admin/pg/conferences', 'pg_conferences_admin', login_required(admin_conferences),
                     methods=['GET', 'POST'])
