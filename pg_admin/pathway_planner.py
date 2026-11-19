"""International Pathway Planner — the doctor's own checklist per country (founder 2026-11-18).

Each country has ordered STAGES (drafted from our e-book, corrected by the team in admin), each for a route:
'all' | 'gp' (MBBS + internship) | 'specialist' (Indian MD/MS/DNB) | 'residency'. A doctor sets their starting
point (route, MBBS / internship / PG done, years of experience) and marks each stage: todo / doing / done / na
(not needed), with an optional target date and note. Stages they finished before (e.g. an English test) are
simply marked done. Progress = done ÷ (stages that apply − na).

Same gate as the e-books (International dashboard pilot / everyone) — pg_admin.ebooks.gate().
Tables: pg_pathway_stages, pg_pathway_profile, pg_pathway_progress.
"""
import json
import logging

from flask import request, jsonify

from db import get_db

logger = logging.getLogger(__name__)

ROUTES = {'gp': 'General practitioner (MBBS)', 'specialist': 'Specialist (Indian MD / MS / DNB)',
          'residency': 'Residency training in the country'}
STATUSES = ('todo', 'doing', 'done', 'na')
DEFAULT_PHASES = [('uae', 1, 'Decide & prepare'), ('uae', 2, 'Verify & get licensed'),
                  ('uae', 3, 'Job & employer'), ('uae', 4, 'Visa & arrival')]
DEFAULT_JOURNEY = [  # from the printed "Your Journey to the GCC" brochure (founder 2026-11-19)
    ('uae', 1, 'Foundation & Preparation', 'Enrolment & document checklist review'),
    ('uae', 2, 'Exam Mastery & Booking Guidance', 'Live Prometric training'),
    ('uae', 3, 'Document Processing', 'DataFlow submission & verification tracking'),
    ('uae', 4, 'Licensing Applications', 'DHA / DoH / MOHAP / SHA applications filed & monitored'),
    ('uae', 5, 'Job Market Preparation', 'CV and profile optimisation'),
    ('uae', 6, 'Job Applications & Interview', 'Job search guidance & employer interview preparation'),
    ('uae', 7, 'Final Steps', 'Attestation / visa & relocation support')]
# where the doctor wants to work → which licensing authority (founder 2026-11-19: "where do they enter which emirate?")
TARGETS = {'uae': [('dubai', 'Dubai', 'dha'), ('abu_dhabi', 'Abu Dhabi (incl. Al Ain)', 'doh'), ('sharjah', 'Sharjah', 'sha'),
                   ('northern', 'Northern Emirates (Ajman, Umm Al Quwain, Ras Al Khaimah, Fujairah)', 'mohap'),
                   ('undecided', 'Not sure yet', '')]}
# where the MBBS was done (founder 2026-11-19): 'india' | 'abroad' (FMG). Details (dates, gaps) go to the profile's
# academic section later; the starting point only asks these.
ACADEMIC_COLS = (('mbbs_from', "TEXT DEFAULT ''"), ('mbbs_country', "TEXT DEFAULT ''"),
                 ('abroad_internship_done', 'BOOLEAN'), ('fmge_cleared', 'BOOLEAN'), ('india_internship_done', 'BOOLEAN'))
# overall "when do you want to be working there?" (founder 2026-11-19: one target at the start, not per step)
TIMELINES = [('6m', 'Within 6 months', 6), ('1y', 'In about 1 year', 12), ('18m', 'In about 1½ years', 18),
             ('2y', 'In about 2 years', 24), ('3y', 'In 3 years or more', 36), ('unsure', 'Not sure yet', None)]
# experience the route needs before applying (UAE PQR: GP 2 years after internship; Indian MD/MS/DNB 3 years after PG)
REQ_EXP_YEARS = {'gp': 2, 'specialist': 3, 'residency': 0}
REG_SHORT = {'dha': 'DHA', 'doh': 'DoH', 'sha': 'SHA', 'mohap': 'MOHAP'}
USD_TO_AED = 3.6725          # UAE dirham's official peg to the US dollar (for the approximate total only)
_READY = {'done': False}


def ensure(conn):
    if _READY['done']:
        return
    conn.execute("SET LOCAL lock_timeout = '3s'")
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_pathway_stages (
        id SERIAL PRIMARY KEY, country TEXT NOT NULL, stage_no INTEGER NOT NULL, route TEXT DEFAULT 'all',
        title TEXT DEFAULT '', what TEXT DEFAULT '', needs TEXT DEFAULT '[]', typical_time TEXT DEFAULT '',
        typical_cost TEXT DEFAULT '', chapter_no INTEGER, service_tag TEXT DEFAULT '', is_active BOOLEAN DEFAULT TRUE,
        admin_edited BOOLEAN DEFAULT FALSE, updated_by TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (country, stage_no))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_pathway_profile (
        user_id INTEGER NOT NULL, country TEXT NOT NULL, route TEXT DEFAULT '', mbbs_done BOOLEAN DEFAULT TRUE,
        internship_done BOOLEAN DEFAULT FALSE, has_pg BOOLEAN DEFAULT FALSE, experience_years NUMERIC(4,1) DEFAULT 0,
        target_date DATE, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (user_id, country))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_pathway_progress (
        user_id INTEGER NOT NULL, stage_id INTEGER NOT NULL, country TEXT NOT NULL, status TEXT DEFAULT 'todo',
        target_date DATE, done_date DATE, note TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, stage_id))''')
    # phases group the stages on the Overview (founder 2026-11-19); labels editable in admin
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_pathway_phases (
        country TEXT NOT NULL, phase_no INTEGER NOT NULL, label TEXT DEFAULT '', PRIMARY KEY (country, phase_no))''')
    conn.execute("ALTER TABLE pg_pathway_stages ADD COLUMN IF NOT EXISTS phase_no INTEGER")
    conn.execute("ALTER TABLE pg_pathway_profile ADD COLUMN IF NOT EXISTS mbbs_college_id INTEGER")
    conn.execute("ALTER TABLE pg_pathway_profile ADD COLUMN IF NOT EXISTS mbbs_college TEXT DEFAULT ''")
    # 2026-11-19 clean-up: real documents per stage (career_vault DOC_TYPES codes → one de-duplicated checklist that
    # ticks itself from My Documents), official approximate costs per authority, and the doctor's target emirate
    conn.execute("ALTER TABLE pg_pathway_stages ADD COLUMN IF NOT EXISTS doc_codes TEXT DEFAULT '[]'")
    conn.execute("ALTER TABLE pg_pathway_stages ADD COLUMN IF NOT EXISTS costs TEXT DEFAULT '[]'")
    conn.execute("ALTER TABLE pg_pathway_profile ADD COLUMN IF NOT EXISTS target_area TEXT DEFAULT ''")
    # founder 2026-11-19 (evening): no target dates — record when a stage was started and finished instead
    conn.execute("ALTER TABLE pg_pathway_progress ADD COLUMN IF NOT EXISTS started_date DATE")
    # onboarding (2026-11-19): typical duration per stage, an "already done?" question, auto-complete key; the doctor's
    # overall timeline, documents they say they already hold, and when onboarding was finished
    for col, ddl in (('duration', "TEXT DEFAULT '{}'"), ('done_q', "TEXT DEFAULT ''"), ('auto_key', "TEXT DEFAULT ''")):
        conn.execute(f"ALTER TABLE pg_pathway_stages ADD COLUMN IF NOT EXISTS {col} {ddl}")
    for col, ddl in (('target_timeline', "TEXT DEFAULT ''"), ('docs_ready', "TEXT DEFAULT '[]'"),
                     ('onboarded_at', 'TIMESTAMP')):
        conn.execute(f"ALTER TABLE pg_pathway_profile ADD COLUMN IF NOT EXISTS {col} {ddl}")
    # Indian graduate vs foreign medical graduate (FMG) — person-level, kept on pg_users so every dashboard shares it
    for col, ddl in ACADEMIC_COLS:
        conn.execute(f"ALTER TABLE pg_users ADD COLUMN IF NOT EXISTS {col} {ddl}")
    for c, n, lbl in DEFAULT_PHASES:
        conn.execute("INSERT INTO pg_pathway_phases (country, phase_no, label) VALUES (?, ?, ?) "
                     "ON CONFLICT (country, phase_no) DO NOTHING", (c, n, lbl))
    # the horizontal "Your journey" strip (our brochure's GooCampus steps), editable in admin (2026-11-19)
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_pathway_journey (
        country TEXT NOT NULL, step_no INTEGER NOT NULL, title TEXT DEFAULT '', detail TEXT DEFAULT '',
        PRIMARY KEY (country, step_no))''')
    for c, n, t, dt in DEFAULT_JOURNEY:
        conn.execute("INSERT INTO pg_pathway_journey (country, step_no, title, detail) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT (country, step_no) DO NOTHING", (c, n, t, dt))
    # licensing regulators per country (DHA / DoH / SHA / MOHAP …): one JSON card each, code '_meta' holds
    # verified_on + residency + gcc_note. Imported from the Mac (sourced research), editable in admin.
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_pathway_regulators (
        country TEXT NOT NULL, code TEXT NOT NULL, sort_order INTEGER DEFAULT 0, data TEXT DEFAULT '{}',
        is_active BOOLEAN DEFAULT TRUE, admin_edited BOOLEAN DEFAULT FALSE, updated_by TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (country, code))''')
    conn.commit()
    _READY['done'] = True


def _needs(v):
    try:
        x = json.loads(v or '[]')
        return [str(i) for i in x] if isinstance(x, list) else []
    except Exception:
        return [s.strip() for s in str(v or '').split(',') if s.strip()]


def _doctor_gated(conn):
    from pg_admin import ebooks as EB
    EB.ensure(conn)
    u, err = EB._doctor(conn)
    if err:
        return None, err
    if not EB.gate(conn, u)[0]:
        return None, (jsonify({'ok': False, 'error': 'not_found'}), 404)
    return u, None


def suggested_route(prof):
    if not prof:
        return 'gp'
    return 'specialist' if prof.get('has_pg') else 'gp'


def phases(conn, country):
    return {r['phase_no']: r['label'] for r in conn.execute(
        "SELECT phase_no, label FROM pg_pathway_phases WHERE country = ? ORDER BY phase_no", (country,)).fetchall()}


def _jl(v):
    try:
        x = json.loads(v or '[]')
        return x if isinstance(x, list) else []
    except Exception:
        return []


def _jd(v):
    try:
        x = json.loads(v or '{}')
        return x if isinstance(x, dict) else {}
    except Exception:
        return {}


def _estimate(stages, prof, route):
    """Months to start working from where the doctor is now: the still-open stages' typical durations (critical-path
    increments) plus any experience the route still needs. Approximate by design."""
    rem = [s for s in stages if s['status'] not in ('done', 'na')]
    lo = sum(float(s['duration'].get('min') or 0) for s in rem)
    hi = sum(float(s['duration'].get('max') or 0) for s in rem)
    exp = float((prof or {}).get('experience_years') or 0)
    gap = max(0.0, REQ_EXP_YEARS.get(route, 0) - exp) * 12
    # documents / verification can run during the last months of experience, so the gap and the steps overlap a little
    mn = max(gap, lo) if gap else lo
    mx = (gap + hi) if gap else hi
    return {'months_min': round(mn), 'months_max': round(max(mx, mn)), 'experience_gap_months': round(gap),
            'experience_needed_years': REQ_EXP_YEARS.get(route, 0), 'remaining_steps': len(rem),
            'note': 'Approximate: typical durations of the steps you still have (official processing times where '
                    'published, otherwise GooCampus estimates) plus any experience your route still needs.'}


def _timeline_options(est):
    out = []
    for code, label, months in TIMELINES:
        if months is None or months >= est['months_min'] or (code == '3y'):
            out.append({'code': code, 'label': label, 'months': months})
    return out


def _doc_labels():
    from pg_admin.career_vault import DOC_TYPES
    return {c: l for c, l, _k in DOC_TYPES}


def _stage_out(s, titles, ph):
    codes = [c for c in _jl(s.get('doc_codes')) if isinstance(c, str)]
    labels = _doc_labels() if codes else {}
    return {'id': s['id'], 'no': s['stage_no'], 'route': s['route'], 'title': s['title'], 'what': s['what'],
            # 'needs' = the real documents when mapped (one shared list), else the old free-text lines
            'needs': [labels.get(c, c) for c in codes] if codes else _needs(s['needs']),
            'doc_codes': codes, 'costs': _jl(s.get('costs')), 'typical_time': s['typical_time'] or '',
            'duration': _jd(s.get('duration')), 'done_question': s.get('done_q') or '', 'auto_key': s.get('auto_key') or '',
            'typical_cost': s['typical_cost'] or '', 'chapter_no': s['chapter_no'],
            'chapter_title': titles.get(s['chapter_no'], ''), 'service_tag': s['service_tag'] or '',
            'phase_no': s.get('phase_no'), 'phase': ph.get(s.get('phase_no'), '') if s.get('phase_no') else ''}


def journey(conn, country):
    return [{'no': r['step_no'], 'title': r['title'], 'detail': r['detail'] or ''} for r in conn.execute(
        "SELECT step_no, title, detail FROM pg_pathway_journey WHERE country = ? ORDER BY step_no", (country,)).fetchall()]


def regulators(conn, country, admin=False):
    """[(code, sort_order, data, is_active, admin_edited, updated_by)] → API shape. '_meta' row = verified_on etc."""
    regs, meta = [], {}
    for r in conn.execute("SELECT * FROM pg_pathway_regulators WHERE country = ? ORDER BY sort_order, code",
                          (country,)).fetchall():
        try:
            d = json.loads(r['data'] or '{}')
        except Exception:
            d = {}
        if r['code'] == '_meta':
            meta = d
            continue
        if not admin and not r['is_active']:
            continue
        if admin:
            regs.append({'code': r['code'], 'sort_order': r['sort_order'], 'is_active': r['is_active'],
                         'admin_edited': r['admin_edited'], 'updated_by': r['updated_by'], 'data': d,
                         'json': json.dumps(d, indent=1, ensure_ascii=False)})
        else:
            regs.append({**d, 'code': r['code']})
    return regs, meta


def _routes(conn, country):
    return [{'code': k, 'label': v} for k, v in ROUTES.items()
            if conn.execute("SELECT 1 FROM pg_pathway_stages WHERE country = ? AND route = ? AND is_active LIMIT 1",
                            (country, k)).fetchone()]


def generic(conn, country):
    """Explore-first Overview (founder 2026-11-19): every active stage of every route, with its phase; no statuses."""
    titles = {r['chapter_no']: r['title'] for r in conn.execute(
        "SELECT chapter_no, title FROM pg_ebook_chapters WHERE ebook_code = ?", (country,)).fetchall()}
    ph = phases(conn, country)
    stages = [_stage_out(dict(s), titles, ph) for s in conn.execute(
        "SELECT * FROM pg_pathway_stages WHERE country = ? AND is_active ORDER BY stage_no", (country,)).fetchall()]
    return {'country': country, 'generic': True, 'routes': _routes(conn, country),
            'phases': [{'phase_no': n, 'label': l} for n, l in ph.items()], 'journey': journey(conn, country),
            'stages': stages}


def _target(country, code):
    for c, label, reg in TARGETS.get(country, []):
        if c == code:
            return {'code': c, 'label': label, 'regulator': reg}
    return None


def _cost_view(items, reg):
    """This stage's costs for the doctor's authority (+ the 'all' ones); every authority's when not chosen yet."""
    return [i for i in items if i.get('reg') in ('all', '', None) or not reg or i.get('reg') == reg]


def _cost_total(stages, reg):
    """Approximate doctor-paid total for the chosen authority, in AED (USD at the official peg). None if no authority."""
    if not reg:
        return None
    aed, inr, lines = 0.0, 0.0, 0
    for s in stages:
        for i in s['costs']:
            # counted: what the doctor pays to GET licensed — not employer-paid items, not optional/conditional
            # ones (in_total false: e.g. oral exam, licence applied for by the facility) and not yearly renewals
            if i.get('payer') == 'employer' or i.get('in_total') is False or i.get('recurring') \
                    or not isinstance(i.get('amount'), (int, float)):
                continue
            cur = (i.get('currency') or 'AED').upper()
            if cur in ('AED', 'USD'):
                aed += i['amount'] * (USD_TO_AED if cur == 'USD' else 1)
            elif cur == 'INR':
                inr += i['amount']
            else:
                continue
            lines += 1
    return {'aed': round(aed), 'inr': round(inr), 'items': lines,
            'note': 'Approximate official fees you pay to get licensed: application, exam and Good Standing. Not included: '
                    'DataFlow verification (no official price list), the licence fee (applied for by the hiring '
                    'facility), visa and yearly renewal. USD fees converted at the official peg of AED 3.6725.'} \
        if lines else None


def _have_docs(conn, user_id):
    try:
        return {r['doc_type'] for r in conn.execute(
            "SELECT DISTINCT doc_type FROM pg_doctor_documents WHERE user_id = ? AND deleted_at IS NULL",
            (user_id,)).fetchall()}
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return set()


def _academic(conn, user_id):
    """Indian graduate / FMG answers from pg_users (shared by every dashboard). Booleans stay None = not answered."""
    try:
        r = conn.execute("SELECT " + ", ".join(c for c, _d in ACADEMIC_COLS) + " FROM pg_users WHERE id = ?",
                         (user_id,)).fetchone()
        return {c: (r[c] if r else None) for c, _d in ACADEMIC_COLS} if r else {}
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return {}


def _documents_needed(conn, user_id, stages, have=None, declared=None):
    """One de-duplicated checklist of real documents for this doctor's route, ticked from My Documents."""
    labels = _doc_labels()
    order, where = [], {}
    for s in stages:
        for c in s['doc_codes']:
            if c not in where:
                order.append(c); where[c] = []
            where[c].append(s['position'])
    if have is None:
        have = _have_docs(conn, user_id)
    declared = set(declared or [])
    # most documents are needed before DataFlow (PSV) — the first stage whose outcome is the PSV report
    psv = next((s['position'] for s in stages if 'dataflow' in s['doc_codes']), None)
    docs = [{'code': c, 'label': labels.get(c, c), 'stages': where[c], 'have': c in have,
             'ready': c in have or c in declared, 'before_psv': bool(psv and where[c][0] < psv)} for c in order]
    return {'items': docs, 'uploaded': sum(1 for d in docs if d['have']), 'ready': sum(1 for d in docs if d['ready']),
            'total': len(docs), 'before_psv_total': sum(1 for d in docs if d['before_psv'])}


def plan(conn, user_id, country):
    prof = conn.execute("SELECT * FROM pg_pathway_profile WHERE user_id = ? AND country = ?", (user_id, country)).fetchone()
    prof = dict(prof) if prof else None
    route = (prof or {}).get('route') or suggested_route(prof)
    tgt = _target(country, (prof or {}).get('target_area') or '')
    reg = (tgt or {}).get('regulator') or ''
    acad = _academic(conn, user_id)
    titles = {r['chapter_no']: r['title'] for r in conn.execute(
        "SELECT chapter_no, title FROM pg_ebook_chapters WHERE ebook_code = ?", (country,)).fetchall()}
    ph = phases(conn, country)
    mine = {r['stage_id']: dict(r) for r in conn.execute(
        "SELECT * FROM pg_pathway_progress WHERE user_id = ? AND country = ?", (user_id, country)).fetchall()}
    stages = []
    for s in conn.execute("SELECT * FROM pg_pathway_stages WHERE country = ? AND is_active AND route IN ('all', ?) "
                          "ORDER BY stage_no", (country, route)).fetchall():
        p = mine.get(s['id']) or {}
        stages.append({**_stage_out(dict(s), titles, ph),
                       'status': p.get('status') or 'todo',
                       'started_date': p['started_date'].isoformat() if p.get('started_date') else None,
                       'target_date': p['target_date'].isoformat() if p.get('target_date') else None,
                       'done_date': p['done_date'].isoformat() if p.get('done_date') else None,
                       'note': p.get('note') or ''})
    labels = _doc_labels()
    have = _have_docs(conn, user_id)
    rs = REG_SHORT.get(reg, 'your authority')
    for st in stages:
        st['done_question'] = st['done_question'].replace('{REG}', rs)
        # step 1 'Choose the emirate' completes itself once the doctor has picked one (founder 2026-11-19)
        if st['auto_key'] == 'target_area':
            if tgt and tgt['code'] != 'undecided':
                st['answer'] = tgt['label'] + (f" ({REG_SHORT.get(reg, '')})" if reg else '')
                if st['status'] == 'todo':
                    st['status'] = 'done'
            else:
                st['answer'] = ''
    for i, st in enumerate(stages, start=1):   # the doctor's own numbering 1..n (master stage_no skips other routes)
        st['position'] = i
        st['costs'] = _cost_view(st['costs'], reg)
        if acad.get('mbbs_from') == 'abroad' and 'internship' in st['doc_codes']:
            # FMG: also the internship done abroad + the FMGE pass (after the Indian internship line)
            k = st['doc_codes'].index('internship') + 1
            st['doc_codes'] = st['doc_codes'][:k] + [c for c in ('internship_abroad', 'fmge')
                                                     if c not in st['doc_codes']] + st['doc_codes'][k:]
            st['needs'] = [labels.get(c, c) for c in st['doc_codes']]
        # the step's own documents, ticked from My Documents — upload right inside the step
        st['documents'] = [{'code': c, 'label': labels.get(c, c), 'have': c in have} for c in st['doc_codes']]
    counted = [s for s in stages if s['status'] != 'na']
    done = sum(1 for s in counted if s['status'] == 'done')
    nxt = next((s for s in stages if s['status'] in ('todo', 'doing')), None)
    est = _estimate(stages, prof, route)
    tl = next(({'code': c, 'label': l, 'months': m} for c, l, m in TIMELINES if c == (prof or {}).get('target_timeline')),
              None)
    declared = _jl((prof or {}).get('docs_ready'))
    onboarding = {
        'done': bool((prof or {}).get('onboarded_at')),
        'questions': [{'stage_id': s['id'], 'position': s['position'], 'question': s['done_question'],
                       'done': s['status'] == 'done'} for s in stages if s['done_question']],
        'timeline_options': _timeline_options(est)}
    if prof is not None:
        prof.update(acad)
        prof['docs_ready'] = declared
    if prof:
        for k in ('target_date', 'updated_at', 'onboarded_at'):
            if prof.get(k):
                prof[k] = prof[k].isoformat()
        prof['experience_years'] = float(prof.get('experience_years') or 0)
    return {'country': country, 'profile': prof, 'route': route, 'routes': _routes(conn, country),
            'phases': [{'phase_no': n, 'label': l} for n, l in ph.items()], 'journey': journey(conn, country),
            'stages': stages, 'progress': {'done': done, 'total': len(counted),
                                           'percent': round(100 * done / len(counted)) if counted else 0},
            'next_stage': nxt['id'] if nxt else None,
            'target': tgt, 'targets': [{'code': c, 'label': l, 'regulator': r} for c, l, r in TARGETS.get(country, [])],
            'documents_needed': _documents_needed(conn, user_id, stages, have, declared),
            'estimate': est, 'timeline': tl, 'onboarding': onboarding,
            'academic': acad, 'mbbs_from_options': [{'code': 'india', 'label': 'India'},
                                                    {'code': 'abroad', 'label': 'Abroad (foreign medical graduate, FMG)'}],
            'cost_total': _cost_total(stages, reg)}


# ── doctor APIs (X-PG-Key + doctor Bearer token; International gate) ────────
def api_plan():
    """GET /api/pg/pathway?country=uae → the doctor's plan: profile, route, stages with their status, progress.
    &generic=1 → the general pathway (all routes, phases, no statuses; profile ignored) for the explore-first Overview."""
    country = (request.args.get('country') or '').strip().lower()
    conn = get_db()
    try:
        ensure(conn)
        u, err = _doctor_gated(conn)
        if err:
            return err
        if not conn.execute("SELECT 1 FROM pg_pathway_stages WHERE country = ? AND is_active LIMIT 1", (country,)).fetchone():
            return jsonify({'ok': False, 'error': 'no_stages'}), 404
        if (request.args.get('generic') or '') in ('1', 'true'):
            return jsonify({'ok': True, **generic(conn, country)})
        return jsonify({'ok': True, **plan(conn, u['id'], country)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("api pathway: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_profile():
    """POST /api/pg/pathway/profile {country, route?, mbbs_done, internship_done, has_pg, experience_years, target_date?,
    target_area? (uae: dubai | abu_dhabi | sharjah | northern | undecided; blank keeps the saved one),
    mbbs_college_id?, mbbs_college?}: the college id is pg_college_master.id from /api/pg/college-lookup?mbbs=1."""
    d = request.get_json(silent=True) or {}
    country = str(d.get('country') or '').strip().lower()
    route = str(d.get('route') or '').strip()
    if route and route not in ROUTES:
        return jsonify({'ok': False, 'error': 'bad_route'}), 400
    try:
        exp = max(0.0, min(60.0, float(d.get('experience_years') or 0)))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'bad_experience'}), 400
    td = str(d.get('target_date') or '').strip()[:10] or None
    try:
        cid = int(d.get('mbbs_college_id')) if d.get('mbbs_college_id') not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'bad_college'}), 400
    cname = str(d.get('mbbs_college') or '').strip()[:250]
    area = str(d.get('target_area') or '').strip()
    if area and not _target(country, area):
        return jsonify({'ok': False, 'error': 'bad_target_area'}), 400
    conn = get_db()
    try:
        ensure(conn)
        u, err = _doctor_gated(conn)
        if err:
            return err
        bad = _save_profile(conn, u, country, d, route, exp, td, cid, cname, area)
        if bad:
            return bad
        conn.commit()
        return jsonify({'ok': True, **plan(conn, u['id'], country)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("api pathway profile: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def _save_profile(conn, u, country, d, route, exp, td, cid, cname, area):
    """Upsert the pathway profile + the shared Indian-graduate / FMG answers (+ timeline / documents held).
    Blank college / target date keep what is saved (onboarding does not send them)."""
    if True:
        if cid:                                   # the College Database name wins over typed text
            m = conn.execute("SELECT college_name FROM pg_college_master WHERE id = ?", (cid,)).fetchone()
            if not m:
                return jsonify({'ok': False, 'error': 'bad_college'}), 400
            cname = m['college_name']
        conn.execute("INSERT INTO pg_pathway_profile (user_id, country, route, mbbs_done, internship_done, has_pg, "
                     "experience_years, target_date, mbbs_college_id, mbbs_college, target_area) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?::date, ?, ?, ?) ON CONFLICT (user_id, country) "
                     "DO UPDATE SET route = EXCLUDED.route, mbbs_done = EXCLUDED.mbbs_done, internship_done = "
                     "EXCLUDED.internship_done, has_pg = EXCLUDED.has_pg, experience_years = EXCLUDED.experience_years, "
                     "target_date = COALESCE(EXCLUDED.target_date, pg_pathway_profile.target_date), "
                     "mbbs_college_id = COALESCE(EXCLUDED.mbbs_college_id, pg_pathway_profile.mbbs_college_id), "
                     "mbbs_college = COALESCE(NULLIF(EXCLUDED.mbbs_college, ''), pg_pathway_profile.mbbs_college), "
                     "target_area = COALESCE(NULLIF(EXCLUDED.target_area, ''), pg_pathway_profile.target_area), "
                     "updated_at = CURRENT_TIMESTAMP",
                     (u['id'], country, route, bool(d.get('mbbs_done', True)), bool(d.get('internship_done')),
                      bool(d.get('has_pg')), exp, td, cid, cname, area))
        # Indian graduate / FMG answers (sent ones only; unanswered stays as it is)
        sets, vals = [], []
        mf = str(d.get('mbbs_from') or '').strip()
        if mf in ('india', 'abroad'):
            sets.append('mbbs_from = ?'); vals.append(mf)
        if 'mbbs_country' in d:
            sets.append('mbbs_country = ?'); vals.append(str(d.get('mbbs_country') or '').strip()[:80])
        for k in ('abroad_internship_done', 'fmge_cleared', 'india_internship_done'):
            if k in d:
                v = str(d.get(k)).strip().lower()
                sets.append(f'{k} = ?')
                vals.append(True if v in ('1', 'true', 'yes') else False if v in ('0', 'false', 'no') else None)
        if sets:
            conn.execute("UPDATE pg_users SET " + ", ".join(sets) + " WHERE id = ?", vals + [u['id']])
        if 'target_timeline' in d:
            tl = str(d.get('target_timeline') or '')
            if tl and tl not in {c for c, _l, _m in TIMELINES}:
                return jsonify({'ok': False, 'error': 'bad_target_timeline'}), 400
            conn.execute("UPDATE pg_pathway_profile SET target_timeline = ? WHERE user_id = ? AND country = ?",
                         (tl, u['id'], country))
        if 'docs_ready' in d:
            from pg_admin.career_vault import DOC_TYPES
            ok = {c for c, _l, _k in DOC_TYPES}
            dr = [c for c in (d.get('docs_ready') or []) if c in ok]
            conn.execute("UPDATE pg_pathway_profile SET docs_ready = ? WHERE user_id = ? AND country = ?",
                         (json.dumps(dr), u['id'], country))
        # picking an emirate completes the 'choose the emirate' stage for real (not only on screen)
        if area and area != 'undecided':
            for r in conn.execute("SELECT id FROM pg_pathway_stages WHERE country = ? AND auto_key = 'target_area'",
                                  (country,)).fetchall():
                conn.execute("INSERT INTO pg_pathway_progress (user_id, stage_id, country, status, started_date, done_date, "
                             "note) VALUES (?, ?, ?, 'done', CURRENT_DATE, CURRENT_DATE, '') ON CONFLICT (user_id, stage_id) "
                             "DO UPDATE SET status = 'done', done_date = COALESCE(pg_pathway_progress.done_date, CURRENT_DATE), "
                             "started_date = COALESCE(pg_pathway_progress.started_date, CURRENT_DATE)",
                             (u['id'], r['id'], country))
        return None


def api_onboard():
    """POST /api/pg/pathway/onboard {country, target_area, mbbs_from, mbbs_country?, abroad_internship_done?,
    fmge_cleared?, india_internship_done?, internship_done, has_pg, experience_years, route?, docs_ready:[codes],
    done_stage_ids:[ids already completed before starting], target_timeline} → saves everything in one go, marks
    those stages done ('already done before starting'), stamps onboarded_at, returns the plan (founder 2026-11-19)."""
    d = request.get_json(silent=True) or {}
    country = str(d.get('country') or '').strip().lower()
    route = str(d.get('route') or '').strip()
    if route and route not in ROUTES:
        return jsonify({'ok': False, 'error': 'bad_route'}), 400
    try:
        exp = max(0.0, min(60.0, float(d.get('experience_years') or 0)))
        ids = [int(x) for x in (d.get('done_stage_ids') or [])][:60]
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'bad_input'}), 400
    area = str(d.get('target_area') or '').strip()
    if area and not _target(country, area):
        return jsonify({'ok': False, 'error': 'bad_target_area'}), 400
    conn = get_db()
    try:
        ensure(conn)
        u, err = _doctor_gated(conn)
        if err:
            return err
        d.setdefault('docs_ready', [])
        bad = _save_profile(conn, u, country, d, route, exp, None, None, '', area)
        if bad:
            return bad
        valid = {r['id'] for r in conn.execute("SELECT id FROM pg_pathway_stages WHERE country = ? AND is_active",
                                               (country,)).fetchall()}
        for sid in [i for i in ids if i in valid]:
            conn.execute("INSERT INTO pg_pathway_progress (user_id, stage_id, country, status, done_date, note) "
                         "VALUES (?, ?, ?, 'done', CURRENT_DATE, 'Already done before starting') "
                         "ON CONFLICT (user_id, stage_id) DO UPDATE SET status = 'done', "
                         "done_date = COALESCE(pg_pathway_progress.done_date, CURRENT_DATE)", (u['id'], sid, country))
        conn.execute("UPDATE pg_pathway_profile SET onboarded_at = CURRENT_TIMESTAMP WHERE user_id = ? AND country = ?",
                     (u['id'], country))
        conn.commit()
        return jsonify({'ok': True, **plan(conn, u['id'], country)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("api pathway onboard: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_stage():
    """POST /api/pg/pathway/stage {stage_id, status (todo|doing|done|na), target_date?, note?} → updated plan."""
    d = request.get_json(silent=True) or {}
    status = str(d.get('status') or 'todo')
    if status not in STATUSES:
        return jsonify({'ok': False, 'error': 'bad_status'}), 400
    try:
        sid = int(d.get('stage_id'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'bad_stage'}), 400
    td = str(d.get('target_date') or '').strip()[:10] or None
    conn = get_db()
    try:
        ensure(conn)
        u, err = _doctor_gated(conn)
        if err:
            return err
        st = conn.execute("SELECT country FROM pg_pathway_stages WHERE id = ?", (sid,)).fetchone()
        if not st:
            return jsonify({'ok': False, 'error': 'bad_stage'}), 404
        # no target dates any more (founder 2026-11-19): started_date is stamped the first time a stage moves to
        # doing/done, done_date when it is done; an old target_date is left untouched unless one is sent
        conn.execute("INSERT INTO pg_pathway_progress (user_id, stage_id, country, status, target_date, done_date, "
                     "started_date, note) VALUES (?, ?, ?, ?, ?::date, CASE WHEN ? = 'done' THEN CURRENT_DATE END, "
                     "CASE WHEN ? IN ('doing', 'done') THEN CURRENT_DATE END, ?) "
                     "ON CONFLICT (user_id, stage_id) DO UPDATE SET status = EXCLUDED.status, target_date = "
                     "COALESCE(EXCLUDED.target_date, pg_pathway_progress.target_date), done_date = CASE WHEN "
                     "EXCLUDED.status = 'done' THEN COALESCE(pg_pathway_progress.done_date, CURRENT_DATE) END, "
                     "started_date = COALESCE(pg_pathway_progress.started_date, EXCLUDED.started_date), "
                     "note = EXCLUDED.note, updated_at = CURRENT_TIMESTAMP",
                     (u['id'], sid, st['country'], status, td, status, status, str(d.get('note') or '')[:1000]))
        conn.commit()
        return jsonify({'ok': True, **plan(conn, u['id'], st['country'])})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("api pathway stage: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_regulators():
    """GET /api/pg/pathway/regulators?country=uae → {regulators:[card…], verified_on, residency, gcc_note}
    (founder 2026-11-19: emirate-wise licensing exams; every field carries its source)."""
    country = (request.args.get('country') or '').strip().lower()
    conn = get_db()
    try:
        ensure(conn)
        u, err = _doctor_gated(conn)
        if err:
            return err
        regs, meta = regulators(conn, country)
        return jsonify({'ok': True, 'country': country, 'regulators': regs,
                        'verified_on': meta.get('verified_on'), 'residency': meta.get('residency') or {},
                        'gcc_note': meta.get('gcc_note') or [], 'within_uae': meta.get('within_uae') or [],
                        'gcc_summary': meta.get('gcc_summary') or '', 'gcc_wide': meta.get('gcc_wide') or {}})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("api pathway regulators: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_regulators_import():
    """POST /api/pg/pathway/regulators/import {country, verified_on, regulators:[{code, …}], residency, gcc_note}
    (X-News-Key). Upserts each card by code; cards the team edited in admin are never overwritten."""
    from pg_admin.routes.api_news_ingest import _ok
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    d = request.get_json(silent=True) or {}
    country = str(d.get('country') or '').strip().lower()
    regs = d.get('regulators') or []
    if not country or not regs:
        return jsonify({'ok': False, 'error': 'need country + regulators'}), 400
    conn = get_db()
    try:
        ensure(conn)
        rows = [(str(r.get('code') or '').strip().lower()[:40], i + 1, r) for i, r in enumerate(regs) if r.get('code')]
        rows.append(('_meta', 0, {'verified_on': d.get('verified_on'), 'residency': d.get('residency') or {},
                                  'gcc_note': d.get('gcc_note') or [], 'within_uae': d.get('within_uae') or [],
                                  'gcc_summary': d.get('gcc_summary') or '', 'gcc_wide': d.get('gcc_wide') or {}}))
        for code, order, data in rows:
            conn.execute("INSERT INTO pg_pathway_regulators (country, code, sort_order, data, updated_by) "
                         "VALUES (?, ?, ?, ?, 'import') ON CONFLICT (country, code) DO UPDATE SET "
                         "sort_order = EXCLUDED.sort_order, data = EXCLUDED.data, updated_by = 'import', "
                         "updated_at = CURRENT_TIMESTAMP WHERE NOT pg_pathway_regulators.admin_edited",
                         (country, code, order, json.dumps(data, ensure_ascii=False)))
        conn.commit()
        return jsonify({'ok': True, 'country': country, 'regulators': len(rows) - 1})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("api pathway regulators import: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── stage content: Mac import (X-News-Key) + admin editor ──────────────────
def api_import():
    """POST /api/pg/pathway/stages/import {country, stages:[{stage_no, route, title, what, needs[], typical_time,
    typical_cost, chapter_no, service_tag}]} (X-News-Key). Upserts by stage_no; stages the team edited in admin are
    never overwritten."""
    from pg_admin.routes.api_news_ingest import _ok
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    d = request.get_json(silent=True) or {}
    country = str(d.get('country') or '').strip().lower()
    stages = d.get('stages') or []
    if not country or not stages:
        return jsonify({'ok': False, 'error': 'need country + stages'}), 400
    conn = get_db()
    try:
        ensure(conn)
        # renumber first (founder 2026-11-19: new steps inserted mid-list): {old_stage_no → stage_no} moves the
        # SAME row (same id, so doctors' ticks stay), via a negative temp number to dodge the unique key
        moves = [(int(s['old_stage_no']), int(s['stage_no'])) for s in stages
                 if s.get('old_stage_no') and int(s['old_stage_no']) != int(s['stage_no'])]
        for old, _new in moves:
            conn.execute("UPDATE pg_pathway_stages SET stage_no = ? WHERE country = ? AND stage_no = ?", (-old, country, old))
        for old, new in moves:
            conn.execute("UPDATE pg_pathway_stages SET stage_no = ? WHERE country = ? AND stage_no = ?", (new, country, -old))
        n = 0
        for s in stages:
            route = s.get('route') if s.get('route') in list(ROUTES) + ['all'] else 'all'
            conn.execute("INSERT INTO pg_pathway_stages (country, stage_no, route, title, what, needs, typical_time, "
                         "typical_cost, chapter_no, service_tag, updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,'import') "
                         "ON CONFLICT (country, stage_no) DO UPDATE SET route = EXCLUDED.route, title = EXCLUDED.title, "
                         "what = EXCLUDED.what, needs = EXCLUDED.needs, typical_time = EXCLUDED.typical_time, "
                         "typical_cost = EXCLUDED.typical_cost, chapter_no = EXCLUDED.chapter_no, "
                         "service_tag = EXCLUDED.service_tag, updated_at = CURRENT_TIMESTAMP "
                         "WHERE NOT pg_pathway_stages.admin_edited",
                         (country, int(s['stage_no']), route, str(s.get('title') or '')[:200],
                          str(s.get('what') or '')[:1200], json.dumps(list(s.get('needs') or [])),
                          str(s.get('typical_time') or '')[:120], str(s.get('typical_cost') or '')[:120],
                          int(s['chapter_no']) if s.get('chapter_no') else None, str(s.get('service_tag') or '')[:200]))
            # documents / costs are data fields (not the team's wording) → always taken from the import when sent;
            # is_active only when sent (hide a stage without deleting it)
            if 'doc_codes' in s:
                conn.execute("UPDATE pg_pathway_stages SET doc_codes = ? WHERE country = ? AND stage_no = ?",
                             (json.dumps([str(c) for c in (s.get('doc_codes') or [])]), country, int(s['stage_no'])))
            if 'costs' in s:
                conn.execute("UPDATE pg_pathway_stages SET costs = ? WHERE country = ? AND stage_no = ?",
                             (json.dumps(list(s.get('costs') or [])), country, int(s['stage_no'])))
            for k, col in (('duration', 'duration'), ('done_q', 'done_q'), ('auto_key', 'auto_key')):
                if k in s:
                    v = json.dumps(s[k] or {}) if k == 'duration' else str(s[k] or '')[:300]
                    conn.execute(f"UPDATE pg_pathway_stages SET {col} = ? WHERE country = ? AND stage_no = ?",
                                 (v, country, int(s['stage_no'])))
            if 'is_active' in s:
                conn.execute("UPDATE pg_pathway_stages SET is_active = ? WHERE country = ? AND stage_no = ?",
                             (bool(s['is_active']), country, int(s['stage_no'])))
            if s.get('phase_no'):                 # phase: fills only a blank (an admin's choice is kept)
                conn.execute("UPDATE pg_pathway_stages SET phase_no = ? WHERE country = ? AND stage_no = ? "
                             "AND phase_no IS NULL", (int(s['phase_no']), country, int(s['stage_no'])))
            n += 1
        conn.commit()
        return jsonify({'ok': True, 'country': country, 'stages': n})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("api pathway import: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def stages_for_admin(conn, country):
    ensure(conn)
    out = []
    for r in conn.execute("SELECT * FROM pg_pathway_stages WHERE country = ? ORDER BY stage_no", (country,)).fetchall():
        r = dict(r)
        r['needs_text'] = ', '.join(_needs(r['needs']))
        r['doc_codes_text'] = ', '.join(c for c in _jl(r.get('doc_codes')) if isinstance(c, str))
        r['costs_json'] = json.dumps(_jl(r.get('costs')), ensure_ascii=False) if _jl(r.get('costs')) else ''
        out.append(r)
    return out


def admin_save_stage():
    from flask import redirect, url_for, flash
    from pg_admin.ebooks import _admin
    a = _admin()
    if not a:
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    f = request.form
    country = (f.get('country') or '').strip().lower()
    route = f.get('route') if f.get('route') in list(ROUTES) + ['all'] else 'all'
    needs = [x.strip() for x in (f.get('needs') or '').split(',') if x.strip()]
    conn = get_db()
    try:
        ensure(conn)
        sid = f.get('id')
        vals = (route, (f.get('title') or '').strip()[:200], (f.get('what') or '').strip()[:1200], json.dumps(needs),
                (f.get('typical_time') or '').strip()[:120], (f.get('typical_cost') or '').strip()[:120],
                int(f.get('chapter_no')) if (f.get('chapter_no') or '').strip().isdigit() else None,
                (f.get('service_tag') or '').strip()[:200], f.get('is_active') == '1', a.get('name') or 'admin',
                int(f.get('phase_no')) if (f.get('phase_no') or '').strip().isdigit() else None)
        if sid:
            conn.execute("UPDATE pg_pathway_stages SET route = ?, title = ?, what = ?, needs = ?, typical_time = ?, "
                         "typical_cost = ?, chapter_no = ?, service_tag = ?, is_active = ?, updated_by = ?, phase_no = ?, "
                         "admin_edited = TRUE, updated_at = CURRENT_TIMESTAMP WHERE id = ?", vals + (int(sid),))
        else:
            nxt = conn.execute("SELECT COALESCE(MAX(stage_no), 0) + 1 AS n FROM pg_pathway_stages WHERE country = ?",
                               (country,)).fetchone()['n']
            conn.execute("INSERT INTO pg_pathway_stages (route, title, what, needs, typical_time, typical_cost, chapter_no, "
                         "service_tag, is_active, updated_by, phase_no, admin_edited, country, stage_no) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,TRUE,?,?)", vals + (country, nxt))
        # documents (codes) + costs (JSON list) — optional fields of the stage form (2026-11-19)
        tgt_id = int(sid) if sid else conn.execute(
            "SELECT id FROM pg_pathway_stages WHERE country = ? ORDER BY stage_no DESC LIMIT 1", (country,)).fetchone()['id']
        if 'doc_codes' in f:
            from pg_admin.career_vault import DOC_TYPES
            ok = {c for c, _l, _k in DOC_TYPES}
            codes = [c.strip() for c in (f.get('doc_codes') or '').split(',') if c.strip() in ok]
            conn.execute("UPDATE pg_pathway_stages SET doc_codes = ? WHERE id = ?", (json.dumps(codes), tgt_id))
        if (f.get('costs') or '').strip():
            try:
                cl = json.loads(f.get('costs'))
                assert isinstance(cl, list)
                conn.execute("UPDATE pg_pathway_stages SET costs = ? WHERE id = ?", (json.dumps(cl), tgt_id))
            except Exception:
                flash('Costs were not valid JSON — the rest was saved.', 'error')
        conn.commit()
        flash('Stage saved.', 'success')
    finally:
        conn.close()
    return redirect(url_for('pg_ebooks_admin', book=country) + '#stages')


def admin_save_phases():
    """POST /admin/pg/pathway/phases {country, label_1..label_8}: rename / add phases; a blank label removes an unused one."""
    from flask import redirect, url_for, flash
    from pg_admin.ebooks import _admin
    if not _admin():
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    f = request.form
    country = (f.get('country') or '').strip().lower()
    conn = get_db()
    try:
        ensure(conn)
        for n in range(1, 9):
            if f'label_{n}' not in f:
                continue
            lbl = (f.get(f'label_{n}') or '').strip()[:80]
            if lbl:
                conn.execute("INSERT INTO pg_pathway_phases (country, phase_no, label) VALUES (?, ?, ?) "
                             "ON CONFLICT (country, phase_no) DO UPDATE SET label = EXCLUDED.label", (country, n, lbl))
            elif not conn.execute("SELECT 1 FROM pg_pathway_stages WHERE country = ? AND phase_no = ? LIMIT 1",
                                  (country, n)).fetchone():
                conn.execute("DELETE FROM pg_pathway_phases WHERE country = ? AND phase_no = ?", (country, n))
        conn.commit()
        flash('Phases saved.', 'success')
    finally:
        conn.close()
    return redirect(url_for('pg_ebooks_admin', book=country) + '#stages')


def admin_save_journey():
    """POST /admin/pg/pathway/journey {country, title_N, detail_N}: the horizontal journey strip; blank title removes a step."""
    from flask import redirect, url_for, flash
    from pg_admin.ebooks import _admin
    if not _admin():
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    f = request.form
    country = (f.get('country') or '').strip().lower()
    conn = get_db()
    try:
        ensure(conn)
        for n in range(1, 13):
            if f'title_{n}' not in f:
                continue
            t = (f.get(f'title_{n}') or '').strip()[:120]
            if t:
                conn.execute("INSERT INTO pg_pathway_journey (country, step_no, title, detail) VALUES (?, ?, ?, ?) "
                             "ON CONFLICT (country, step_no) DO UPDATE SET title = EXCLUDED.title, detail = EXCLUDED.detail",
                             (country, n, t, (f.get(f'detail_{n}') or '').strip()[:240]))
            else:
                conn.execute("DELETE FROM pg_pathway_journey WHERE country = ? AND step_no = ?", (country, n))
        conn.commit()
        flash('Journey saved.', 'success')
    finally:
        conn.close()
    return redirect(url_for('pg_ebooks_admin', book=country) + '#journey')


def admin_save_regulator():
    """POST /admin/pg/pathway/regulator {country, code, json, is_active}: edit one licensing card (kept on re-import)."""
    from flask import redirect, url_for, flash
    from pg_admin.ebooks import _admin
    a = _admin()
    if not a:
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    f = request.form
    country = (f.get('country') or '').strip().lower()
    code = (f.get('code') or '').strip().lower()[:40]
    try:
        data = json.loads(f.get('json') or '{}')
        assert isinstance(data, dict)
    except Exception:
        flash('That card is not valid JSON — nothing saved. Check commas and quotes.', 'error')
        return redirect(url_for('pg_ebooks_admin', book=country) + '#regulators')
    conn = get_db()
    try:
        ensure(conn)
        conn.execute("UPDATE pg_pathway_regulators SET data = ?, is_active = ?, admin_edited = TRUE, updated_by = ?, "
                     "updated_at = CURRENT_TIMESTAMP WHERE country = ? AND code = ?",
                     (json.dumps(data, ensure_ascii=False), f.get('is_active') == '1', a.get('name') or 'admin',
                      country, code))
        conn.commit()
        flash('Licensing card saved.', 'success')
    finally:
        conn.close()
    return redirect(url_for('pg_ebooks_admin', book=country) + '#regulators')


def register(app):
    from core.auth import login_required
    app.add_url_rule('/api/pg/pathway', 'api_pg_pathway', api_plan, methods=['GET'])
    app.add_url_rule('/api/pg/pathway/profile', 'api_pg_pathway_profile', api_profile, methods=['POST'])
    app.add_url_rule('/api/pg/pathway/onboard', 'api_pg_pathway_onboard', api_onboard, methods=['POST'])
    app.add_url_rule('/api/pg/pathway/stage', 'api_pg_pathway_stage', api_stage, methods=['POST'])
    app.add_url_rule('/api/pg/pathway/stages/import', 'api_pg_pathway_import', api_import, methods=['POST'])
    app.add_url_rule('/admin/pg/pathway/stage', 'pg_pathway_save_stage', login_required(admin_save_stage),
                     methods=['POST'])
    app.add_url_rule('/admin/pg/pathway/phases', 'pg_pathway_save_phases', login_required(admin_save_phases),
                     methods=['POST'])
    app.add_url_rule('/admin/pg/pathway/journey', 'pg_pathway_save_journey', login_required(admin_save_journey),
                     methods=['POST'])
    app.add_url_rule('/admin/pg/pathway/regulator', 'pg_pathway_save_regulator', login_required(admin_save_regulator),
                     methods=['POST'])
    app.add_url_rule('/api/pg/pathway/regulators', 'api_pg_pathway_regulators', api_regulators, methods=['GET'])
    app.add_url_rule('/api/pg/pathway/regulators/import', 'api_pg_pathway_regulators_import', api_regulators_import,
                     methods=['POST'])
