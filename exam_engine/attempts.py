"""A doctor's attempt at a paper: the server-side clock, autosave, section changes, submission, scoring.

The clock lives here, never in the browser:
  - each section has its own window (started_at → ends_at, UTC);
  - when a window ends, that section closes and the next one opens AT THAT MOMENT — even if nobody is
    looking (the doctor closed the tab, lost network, switched device);
  - when the last section ends, the attempt is submitted ("time_up") — by the next request that touches
    it, or by the background sweep every 2 minutes, whichever comes first;
  - a closed section can never be reopened (NBEMS rule) — its questions aren't even sent again.
Saves that arrive a few seconds after a section closed (network delay) are still accepted (GRACE_SECONDS).
Every save carries the device's own timestamp per question, so the newest answer wins across devices.
"""
import json
import logging
import random
from datetime import datetime, timedelta

from db import get_db

GRACE_SECONDS = 20
EVENT_KINDS = {'tab_hidden', 'tab_visible', 'fullscreen_exit', 'fullscreen_enter', 'offline', 'online',
               'resumed', 'copy_attempt', 'right_click', 'devtools'}
MAX_EVENTS_PER_SAVE = 50


def utcnow():
    return datetime.utcnow().replace(microsecond=0)


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None


def _dt(s):
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ') if s else None


# ── creating / loading ──────────────────────────────────────────────────────────────────────────────

_ITEMS_CACHE = {}       # (paper_id, locked_at) → items — a locked paper never changes, so autosaves skip the DB


def paper_items(conn, paper):
    key = (paper['id'], str(paper.get('locked_at')))
    if paper.get('locked_at') and key in _ITEMS_CACHE:
        return _ITEMS_CACHE[key]
    rows = [dict(r) for r in conn.execute(
        "SELECT id, section_code, position, question_id, snapshot_json FROM ex_paper_items WHERE paper_id=? "
        "ORDER BY section_code, position", (paper['id'],)).fetchall()]
    for r in rows:
        r['snap'] = json.loads(r['snapshot_json']) if r.get('snapshot_json') else None
        r.pop('snapshot_json', None)
    if paper.get('locked_at') and all(r['snap'] for r in rows):
        if len(_ITEMS_CACHE) > 200:
            _ITEMS_CACHE.clear()
        _ITEMS_CACHE[key] = rows
    return rows


def open_attempt(conn, user_id, paper_id):
    r = conn.execute("SELECT id FROM ex_attempts WHERE user_id=? AND paper_id=? AND status='in_progress' "
                     "ORDER BY id DESC LIMIT 1", (user_id, paper_id)).fetchone()
    return r['id'] if r else None


def attempts_used(conn, user_id, paper_id):
    return conn.execute("SELECT COUNT(*) AS n FROM ex_attempts WHERE user_id=? AND paper_id=?",
                        (user_id, paper_id)).fetchone()['n']


def create(conn, paper, user_id, access, client_info='', now=None):
    """Starts a new attempt (the caller has already checked access + attempts left)."""
    now = now or utcnow()
    pat = paper['pattern']
    secs = pat.get('sections') or []
    items = paper_items(conn, paper)
    if not items or any(i['snap'] is None for i in items):
        raise ValueError('paper is not locked')
    rng = random.Random()
    order = {'questions': {}, 'options': {}}
    for s in secs:
        ids = [i['id'] for i in items if i['section_code'] == s['code']]
        if pat.get('shuffle_questions'):
            rng.shuffle(ids)
        order['questions'][s['code']] = ids
    if pat.get('shuffle_options'):
        for i in items:
            keys = [o[0] for o in i['snap']['options']]
            rng.shuffle(keys)
            order['options'][str(i['id'])] = keys
    first_end = now + timedelta(minutes=int(secs[0]['minutes']))
    sections = [{'code': s['code'], 'started_at': None, 'ends_at': None, 'closed_at': None, 'close_reason': None}
                for s in secs]
    sections[0]['started_at'], sections[0]['ends_at'] = _iso(now), _iso(first_end)
    deadline = first_end + timedelta(minutes=sum(int(s['minutes']) for s in secs[1:]))
    n = attempts_used(conn, user_id, paper['id']) + 1
    aid = conn.execute(
        "INSERT INTO ex_attempts (tenant_id, exam_code, paper_id, user_id, attempt_no, access, started_at, deadline_at, "
        "cur_section, sections_json, order_json, last_seen_at, max_score, client_info) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?) RETURNING id",
        (paper['tenant_id'], paper['exam_code'], paper['id'], user_id, n, access, now, deadline,
         json.dumps(sections), json.dumps(order), now, int(pat.get('max_marks') or 0), (client_info or '')[:300])
    ).fetchone()['id']
    conn.execute_batch(
        "INSERT INTO ex_attempt_answers (attempt_id, item_id, question_id, section_code, subject) VALUES (?, ?, ?, ?, ?)",
        [(aid, i['id'], i['question_id'], i['section_code'], (i['snap'] or {}).get('subject') or '') for i in items])
    log_event(conn, aid, 'started', '')
    return aid


def load(conn, aid):
    r = conn.execute("SELECT * FROM ex_attempts WHERE id=?", (aid,)).fetchone()
    if not r:
        return None
    a = dict(r)
    a['sections'] = json.loads(a['sections_json'])
    a['order'] = json.loads(a.get('order_json') or '{}')
    return a


def _persist(conn, a):
    conn.execute("UPDATE ex_attempts SET cur_section=?, sections_json=?, deadline_at=? WHERE id=?",
                 (a['cur_section'], json.dumps(a['sections']), a['deadline_at'], a['id']))


def log_event(conn, aid, kind, detail='', client_ts=None):
    conn.execute("INSERT INTO ex_attempt_events (attempt_id, kind, detail, client_ts) VALUES (?, ?, ?, ?)",
                 (aid, kind[:40], (detail or '')[:300], client_ts))


# ── the clock ───────────────────────────────────────────────────────────────────────────────────────

def advance(conn, a, paper, now=None):
    """Brings the attempt up to `now`: closes sections whose time is over, opens the next one at the exact
    moment the previous closed, and submits when the last one ends. Safe to call any number of times."""
    now = now or utcnow()
    if a['status'] != 'in_progress':
        return a
    secs = paper['pattern']['sections']
    changed = False
    while True:
        i = a['cur_section']
        cur = a['sections'][i]
        ends = _dt(cur['ends_at'])
        if now < ends:
            break
        cur['closed_at'], cur['close_reason'] = cur['ends_at'], 'time_up'
        changed = True
        if i + 1 < len(secs):
            nxt = a['sections'][i + 1]
            nxt['started_at'] = cur['ends_at']
            nxt['ends_at'] = _iso(ends + timedelta(minutes=int(secs[i + 1]['minutes'])))
            a['cur_section'] = i + 1
            log_event(conn, a['id'], 'section_closed', f"{cur['code']} time_up")
        else:
            _persist(conn, a)
            finalize(conn, a, paper, 'time_up', at=ends)
            return a
    if changed:
        _persist(conn, a)
    return a


def end_section_early(conn, a, paper, now=None):
    """The doctor finishes the current section early — only when the pattern allows it
    (NEET PG: each section runs its full time, so this is refused)."""
    now = now or utcnow()
    advance(conn, a, paper, now)
    if a['status'] != 'in_progress':
        return 'This attempt is already submitted.'
    if paper['pattern'].get('section_runs_full_time'):
        return 'Each section runs its full time in this exam — the next section opens when the timer ends.'
    secs = paper['pattern']['sections']
    i = a['cur_section']
    cur = a['sections'][i]
    cur['closed_at'], cur['close_reason'] = _iso(now), 'doctor'
    if i + 1 < len(secs):
        nxt = a['sections'][i + 1]
        nxt['started_at'] = _iso(now)
        nxt_end = now + timedelta(minutes=int(secs[i + 1]['minutes']))
        nxt['ends_at'] = _iso(nxt_end)
        a['cur_section'] = i + 1
        a['deadline_at'] = nxt_end + timedelta(minutes=sum(int(s['minutes']) for s in secs[i + 2:]))
        _persist(conn, a)
        log_event(conn, a['id'], 'section_closed', f"{cur['code']} doctor")
        return None
    _persist(conn, a)
    finalize(conn, a, paper, 'doctor', at=now)
    return None


def remaining(a, now=None):
    now = now or utcnow()
    if a['status'] != 'in_progress':
        return 0, 0
    cur = a['sections'][a['cur_section']]
    sec_left = max(0, int((_dt(cur['ends_at']) - now).total_seconds()))
    total_left = max(0, int((a['deadline_at'] - now).total_seconds())) if a.get('deadline_at') else sec_left
    return sec_left, total_left


# ── saving answers ──────────────────────────────────────────────────────────────────────────────────

def _open_sections(a, now):
    """Section codes that may still receive answers: the current one, plus one that closed < GRACE ago."""
    codes = set()
    if a['status'] == 'in_progress':
        codes.add(a['sections'][a['cur_section']]['code'])
    for s in a['sections']:
        if s.get('closed_at') and now <= _dt(s['closed_at']) + timedelta(seconds=GRACE_SECONDS):
            codes.add(s['code'])
    if a['status'] == 'submitted' and a.get('submitted_at') and now <= a['submitted_at'] + timedelta(seconds=GRACE_SECONDS):
        last = next((s for s in reversed(a['sections']) if s.get('started_at')), None)
        if last:
            codes.add(last['code'])
    return codes


def save(conn, a, paper, responses, events=None, now=None):
    """Applies a batch of answers. responses: [{item_id, chosen ('A'…'D' original key, or null), marked,
    visited, time_ms (total on this question), client_ts (ms)}]. → {'saved', 'rejected', 'late_rescore'}"""
    now = now or utcnow()
    advance(conn, a, paper, now)
    allowed = _open_sections(a, now)
    opts = {}
    for i in paper_items(conn, paper):
        opts[i['id']] = ({o[0] for o in (i['snap'] or {}).get('options') or []}, i['section_code'])
    saved, rejected = 0, []
    for r in (responses or [])[:500]:
        try:
            item_id = int(r.get('item_id'))
        except (TypeError, ValueError):
            rejected.append({'item_id': r.get('item_id'), 'why': 'bad_item'})
            continue
        if item_id not in opts:
            rejected.append({'item_id': item_id, 'why': 'not_in_paper'})
            continue
        keys, sec = opts[item_id]
        if sec not in allowed:
            rejected.append({'item_id': item_id, 'why': 'section_closed'})
            continue
        chosen = r.get('chosen')
        chosen = str(chosen).upper() if chosen not in (None, '') else None
        if chosen is not None and chosen not in keys:
            rejected.append({'item_id': item_id, 'why': 'bad_option'})
            continue
        try:
            ts = int(r.get('client_ts') or 0)
            tms = max(0, min(int(r.get('time_ms') or 0), 6 * 3600 * 1000))
        except (TypeError, ValueError):
            ts, tms = 0, 0
        cur = conn.execute(
            "UPDATE ex_attempt_answers SET chosen=?, marked=?, visited=(visited OR ?), "
            "time_ms=GREATEST(time_ms, ?), client_ts=?, updated_at=? "
            "WHERE attempt_id=? AND item_id=? AND client_ts <= ?",
            (chosen, bool(r.get('marked')), bool(r.get('visited', True)), tms, ts, now, a['id'], item_id, ts))
        if getattr(cur.cursor, 'rowcount', 1):
            saved += 1
    for e in (events or [])[:MAX_EVENTS_PER_SAVE]:
        kind = str((e or {}).get('kind') or '')
        if kind in EVENT_KINDS:
            try:
                cts = int(e.get('client_ts') or 0) or None
            except (TypeError, ValueError):
                cts = None
            log_event(conn, a['id'], kind, str(e.get('detail') or ''), cts)
    conn.execute("UPDATE ex_attempts SET last_seen_at=? WHERE id=?", (now, a['id']))
    late = False
    if a['status'] == 'submitted' and saved:
        score(conn, a, paper)          # late saves inside the grace window still count
        late = True
    return {'saved': saved, 'rejected': rejected, 'late_rescore': late}


# ── submitting + scoring ────────────────────────────────────────────────────────────────────────────

def finalize(conn, a, paper, reason, at=None):
    """Submits the attempt (once — later calls do nothing) and scores it."""
    at = at or utcnow()
    r = conn.execute("UPDATE ex_attempts SET status='submitted', submit_reason=?, submitted_at=? "
                     "WHERE id=? AND status='in_progress' RETURNING id", (reason, at, a['id'])).fetchone()
    if not r:
        return False
    a['status'], a['submit_reason'], a['submitted_at'] = 'submitted', reason, at
    # the doctor's first submitted attempt is the ranked one; retakes are practice; team dry runs never rank
    ranked = a.get('access') != 'team' and not conn.execute(
        "SELECT 1 FROM ex_attempts WHERE user_id=? AND paper_id=? AND is_ranked AND id <> ? LIMIT 1",
        (a['user_id'], a['paper_id'], a['id'])).fetchone()
    conn.execute("UPDATE ex_attempts SET is_ranked=? WHERE id=?", (bool(ranked), a['id']))
    a['is_ranked'] = bool(ranked)
    log_event(conn, a['id'], 'submitted', reason)
    score(conn, a, paper)
    return True


def score(conn, a, paper):
    m = paper['pattern'].get('marking') or {'correct': 4, 'wrong': -1, 'unattempted': 0}
    key = {i['id']: (i['snap'] or {}).get('answer') for i in paper_items(conn, paper)}
    n_c = n_w = n_u = total = 0
    for r in conn.execute("SELECT item_id, chosen FROM ex_attempt_answers WHERE attempt_id=?", (a['id'],)).fetchall():
        if not r['chosen']:
            ok, marks = None, int(m.get('unattempted', 0))
            n_u += 1
        elif r['chosen'] == key.get(r['item_id']):
            ok, marks = True, int(m.get('correct', 4))
            n_c += 1
        else:
            ok, marks = False, int(m.get('wrong', -1))
            n_w += 1
        total += marks
        conn.execute("UPDATE ex_attempt_answers SET is_correct=?, marks=? WHERE attempt_id=? AND item_id=?",
                     (ok, marks, a['id'], r['item_id']))
    conn.execute("UPDATE ex_attempts SET n_correct=?, n_wrong=?, n_unattempted=?, score=? WHERE id=?",
                 (n_c, n_w, n_u, total, a['id']))
    a.update({'n_correct': n_c, 'n_wrong': n_w, 'n_unattempted': n_u, 'score': total})
    return total


def sweep():
    """Background job: submits attempts whose time ran out while nobody was looking. Idempotent, so it is
    fine that every web process runs it."""
    from exam_engine import papers as _papers
    conn = get_db()
    done = 0
    try:
        cutoff = utcnow() - timedelta(seconds=GRACE_SECONDS)
        ids = [r['id'] for r in conn.execute(
            "SELECT id FROM ex_attempts WHERE status='in_progress' AND deadline_at < ? ORDER BY id LIMIT 500",
            (cutoff,)).fetchall()]
        cache = {}
        for aid in ids:
            a = load(conn, aid)
            if not a:
                continue
            p = cache.get(a['paper_id']) or _papers.load(conn, a['paper_id'])
            cache[a['paper_id']] = p
            advance(conn, a, p)
            conn.commit()
            done += 1
    except Exception as e:
        logging.error(f'exam attempts sweep: {e}')
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return done


def start_sweeper():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        sch = BackgroundScheduler()
        sch.add_job(sweep, 'interval', minutes=2, id='ex_attempt_sweep', coalesce=True, max_instances=1,
                    misfire_grace_time=60)
        sch.start()
    except Exception as e:
        logging.warning(f'exam attempt sweeper not started: {e}')


# ── what the exam screen needs ──────────────────────────────────────────────────────────────────────

def palette_state(r):
    """NBEMS palette colours: not_visited · not_answered · answered · marked · answered_marked."""
    if r['chosen'] and r['marked']:
        return 'answered_marked'
    if r['chosen']:
        return 'answered'
    if r['marked']:
        return 'marked'
    if r['visited']:
        return 'not_answered'
    return 'not_visited'


def state(conn, a, paper, image_url, now=None):
    """Everything the exam screen needs right now. Only the CURRENT section's questions are sent (closed
    sections can't be reopened; later ones can't be peeked at). No answers or explanations."""
    now = now or utcnow()
    pat = paper['pattern']
    sec_left, total_left = remaining(a, now)
    answers = {r['item_id']: dict(r) for r in conn.execute(
        "SELECT item_id, section_code, chosen, marked, visited, time_ms FROM ex_attempt_answers WHERE attempt_id=?",
        (a['id'],)).fetchall()}
    progress = []
    for i, s in enumerate(pat['sections']):
        rows = [r for r in answers.values() if r['section_code'] == s['code']]
        st = a['sections'][i]
        progress.append({
            'code': s['code'], 'name': s['name'], 'questions': int(s['questions']), 'minutes': int(s['minutes']),
            'status': 'closed' if st.get('closed_at') else ('current' if (a['status'] == 'in_progress' and i == a['cur_section']) else 'upcoming'),
            'answered': sum(1 for r in rows if r['chosen']),
            'marked': sum(1 for r in rows if r['marked']),
            'visited': sum(1 for r in rows if r['visited']),
        })
    out = {
        'attempt_id': a['id'], 'status': a['status'], 'submit_reason': a.get('submit_reason') or '',
        'server_time': _iso(now),
        'paper': {'id': paper['id'], 'title': paper['title'], 'kind': paper['kind'],
                  'total_questions': pat.get('total_questions'), 'total_minutes': pat.get('total_minutes'),
                  'max_marks': pat.get('max_marks'), 'marking': pat.get('marking'),
                  'section_lock': bool(pat.get('section_lock')),
                  'can_end_section_early': not pat.get('section_runs_full_time')},
        'sections': progress,
        'total_remaining_seconds': total_left,
    }
    if a['status'] != 'in_progress':
        out['result'] = {'ranked': bool(a.get('is_ranked')), 'score': a.get('score'), 'max_score': a.get('max_score'), 'correct': a.get('n_correct'),
                         'wrong': a.get('n_wrong'), 'unattempted': a.get('n_unattempted'),
                         'submitted_at': _iso(a.get('submitted_at'))}
        return out
    i = a['cur_section']
    sec = a['sections'][i]
    code = sec['code']
    items = {it['id']: it for it in paper_items(conn, paper) if it['section_code'] == code}
    img_rows = {}
    ids = [im['id'] for it in items.values() for im in (it['snap'] or {}).get('images') or [] if im.get('role') == 'stem']
    if ids:
        ph = ','.join('?' * len(ids))
        img_rows = {r['id']: dict(r) for r in conn.execute(
            f"SELECT id, file_key, width, height FROM ex_question_images WHERE id IN ({ph})", tuple(ids)).fetchall()}
    qs = []
    order = (a['order'].get('questions') or {}).get(code) or sorted(items, key=lambda k: items[k]['position'])
    for n, item_id in enumerate(order, 1):
        it = items.get(item_id)
        if not it:
            continue
        snap = it['snap']
        opt_text = {o[0]: o[1] for o in snap['options']}
        keys = (a['order'].get('options') or {}).get(str(item_id)) or [o[0] for o in snap['options']]
        r = answers.get(item_id) or {}
        qs.append({
            'item_id': item_id, 'number': n, 'stem': snap['stem'],
            'images': [{'url': image_url(im['id'], img_rows.get(im['id'])), 'width': im.get('width'),
                        'height': im.get('height')}
                       for im in snap.get('images') or [] if im.get('role') == 'stem' and im['id'] in img_rows],
            'options': [{'key': k, 'text': opt_text.get(k, '')} for k in keys],
            'response': {'chosen': r.get('chosen'), 'marked': bool(r.get('marked')), 'visited': bool(r.get('visited')),
                         'time_ms': int(r.get('time_ms') or 0)},
            'palette': palette_state(r) if r else 'not_visited',
        })
    out['current_section'] = {'index': i, 'code': code, 'name': pat['sections'][i]['name'],
                              'started_at': sec['started_at'], 'ends_at': sec['ends_at'],
                              'remaining_seconds': sec_left, 'questions': qs}
    return out
