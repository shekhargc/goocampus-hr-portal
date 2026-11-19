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


def _stage_out(s, titles, ph):
    return {'id': s['id'], 'no': s['stage_no'], 'route': s['route'], 'title': s['title'], 'what': s['what'],
            'needs': _needs(s['needs']), 'typical_time': s['typical_time'] or '',
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


def plan(conn, user_id, country):
    prof = conn.execute("SELECT * FROM pg_pathway_profile WHERE user_id = ? AND country = ?", (user_id, country)).fetchone()
    prof = dict(prof) if prof else None
    route = (prof or {}).get('route') or suggested_route(prof)
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
                       'target_date': p['target_date'].isoformat() if p.get('target_date') else None,
                       'done_date': p['done_date'].isoformat() if p.get('done_date') else None,
                       'note': p.get('note') or ''})
    counted = [s for s in stages if s['status'] != 'na']
    done = sum(1 for s in counted if s['status'] == 'done')
    nxt = next((s for s in stages if s['status'] in ('todo', 'doing')), None)
    if prof:
        for k in ('target_date', 'updated_at'):
            if prof.get(k):
                prof[k] = prof[k].isoformat()
        prof['experience_years'] = float(prof.get('experience_years') or 0)
    return {'country': country, 'profile': prof, 'route': route, 'routes': _routes(conn, country),
            'phases': [{'phase_no': n, 'label': l} for n, l in ph.items()], 'journey': journey(conn, country),
            'stages': stages, 'progress': {'done': done, 'total': len(counted),
                                           'percent': round(100 * done / len(counted)) if counted else 0},
            'next_stage': nxt['id'] if nxt else None}


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
    conn = get_db()
    try:
        ensure(conn)
        u, err = _doctor_gated(conn)
        if err:
            return err
        if cid:                                   # the College Database name wins over typed text
            m = conn.execute("SELECT college_name FROM pg_college_master WHERE id = ?", (cid,)).fetchone()
            if not m:
                return jsonify({'ok': False, 'error': 'bad_college'}), 400
            cname = m['college_name']
        conn.execute("INSERT INTO pg_pathway_profile (user_id, country, route, mbbs_done, internship_done, has_pg, "
                     "experience_years, target_date, mbbs_college_id, mbbs_college) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?::date, ?, ?) ON CONFLICT (user_id, country) "
                     "DO UPDATE SET route = EXCLUDED.route, mbbs_done = EXCLUDED.mbbs_done, internship_done = "
                     "EXCLUDED.internship_done, has_pg = EXCLUDED.has_pg, experience_years = EXCLUDED.experience_years, "
                     "target_date = EXCLUDED.target_date, mbbs_college_id = EXCLUDED.mbbs_college_id, "
                     "mbbs_college = EXCLUDED.mbbs_college, updated_at = CURRENT_TIMESTAMP",
                     (u['id'], country, route, bool(d.get('mbbs_done', True)), bool(d.get('internship_done')),
                      bool(d.get('has_pg')), exp, td, cid, cname))
        conn.commit()
        return jsonify({'ok': True, **plan(conn, u['id'], country)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("api pathway profile: %s", e)
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
        conn.execute("INSERT INTO pg_pathway_progress (user_id, stage_id, country, status, target_date, done_date, note) "
                     "VALUES (?, ?, ?, ?, ?::date, CASE WHEN ? = 'done' THEN CURRENT_DATE END, ?) "
                     "ON CONFLICT (user_id, stage_id) DO UPDATE SET status = EXCLUDED.status, target_date = "
                     "EXCLUDED.target_date, done_date = CASE WHEN EXCLUDED.status = 'done' THEN "
                     "COALESCE(pg_pathway_progress.done_date, CURRENT_DATE) END, note = EXCLUDED.note, "
                     "updated_at = CURRENT_TIMESTAMP",
                     (u['id'], sid, st['country'], status, td, status, str(d.get('note') or '')[:1000]))
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
