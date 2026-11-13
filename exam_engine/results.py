"""Results for a submitted attempt: score, rank, percentile, section/subject/time analysis, solutions,
predicted NEET PG rank.

Rank rules (founder 2026-11-13): a doctor may retake a mock to practise, but only their FIRST submitted
attempt is ranked (ex_attempts.is_ranked). Team dry runs (access='team') are never ranked. A practice attempt
shows where that score WOULD sit, clearly labelled.

Per-question and per-subject "how did everyone do" figures are computed over ranked attempts and cached for
a few minutes per paper — they barely move between two views and are the only heavy queries here.
"""
import collections
import time

from exam_engine import attempts as A, neet_curve

STATS_TTL = 600
_STATS = {}


def _iso(dt):
    return A._iso(dt)


def rank_of(conn, paper_id, score):
    r = conn.execute(
        "SELECT COUNT(*) AS n, "
        "COALESCE(SUM(CASE WHEN score > ? THEN 1 ELSE 0 END), 0) AS higher, "
        "COALESCE(SUM(CASE WHEN score < ? THEN 1 ELSE 0 END), 0) AS lower, "
        "MAX(score) AS top, AVG(score) AS avg FROM ex_attempts WHERE paper_id=? AND is_ranked",
        (score, score, paper_id)).fetchone()
    return dict(r)


def paper_stats(conn, paper_id):
    """{'items': {item_id: (n, n_attempted, n_correct)}, 'subjects': {subject: avg marks per ranked taker}, 'n'}"""
    hit = _STATS.get(paper_id)
    if hit and time.time() - hit[0] < STATS_TTL:
        return hit[1]
    n = conn.execute("SELECT COUNT(*) AS n FROM ex_attempts WHERE paper_id=? AND is_ranked", (paper_id,)).fetchone()['n']
    items, subj = {}, {}
    if n:
        for r in conn.execute(
                "SELECT aa.item_id, COUNT(*) AS n, "
                "SUM(CASE WHEN aa.chosen IS NOT NULL THEN 1 ELSE 0 END) AS att, "
                "SUM(CASE WHEN aa.is_correct THEN 1 ELSE 0 END) AS ok "
                "FROM ex_attempt_answers aa JOIN ex_attempts a ON a.id = aa.attempt_id "
                "WHERE a.paper_id=? AND a.is_ranked GROUP BY aa.item_id", (paper_id,)).fetchall():
            items[r['item_id']] = (int(r['n']), int(r['att'] or 0), int(r['ok'] or 0))
        for r in conn.execute(
                "SELECT aa.subject, SUM(aa.marks) AS m FROM ex_attempt_answers aa JOIN ex_attempts a ON a.id = aa.attempt_id "
                "WHERE a.paper_id=? AND a.is_ranked GROUP BY aa.subject", (paper_id,)).fetchall():
            subj[r['subject'] or ''] = round(float(r['m'] or 0) / n, 1)
    out = {'items': items, 'subjects': subj, 'n': n}
    _STATS[paper_id] = (time.time(), out)
    if len(_STATS) > 300:
        _STATS.clear()
    return out


def _answers(conn, aid):
    return [dict(r) for r in conn.execute(
        "SELECT item_id, question_id, section_code, subject, chosen, marked, visited, time_ms, is_correct, marks "
        "FROM ex_attempt_answers WHERE attempt_id=?", (aid,)).fetchall()]


def _display_order(a, paper, items_by_id):
    """[(section_code, number, item_id)] in the order the doctor saw them."""
    out = []
    for s in paper['pattern']['sections']:
        ids = (a['order'].get('questions') or {}).get(s['code']) or \
            [i['id'] for i in sorted((x for x in items_by_id.values() if x['section_code'] == s['code']),
                                     key=lambda x: x['position'])]
        for n, iid in enumerate(ids, 1):
            out.append((s['code'], n, iid))
    return out


def result(conn, a, paper):
    """The result page data (no per-question solutions — see solutions())."""
    pat = paper['pattern']
    ans = _answers(conn, a['id'])
    items = {i['id']: i for i in A.paper_items(conn, paper)}
    attempted = sum(1 for r in ans if r['chosen'])
    neg = sum(1 for r in ans if r['is_correct'] is False) * abs(int((pat.get('marking') or {}).get('wrong', -1)))
    total_ms = sum(int(r['time_ms'] or 0) for r in ans)
    started, ended = a['started_at'], a.get('submitted_at') or A.utcnow()
    score = int(a.get('score') or 0)

    rk = rank_of(conn, paper['id'], score)
    n = int(rk['n'] or 0)
    rank = {'ranked': bool(a.get('is_ranked')), 'out_of': n,
            'topper_score': rk['top'], 'average_score': round(float(rk['avg']), 1) if rk['avg'] is not None else None}
    if n:
        rank['rank'] = int(rk['higher']) + 1
        rank['percentile'] = round(100.0 * int(rk['lower']) / n, 2)
    else:
        rank['rank'], rank['percentile'] = None, None
    if a.get('is_ranked'):
        rank['note'] = f"Among {n} doctor{'s' if n != 1 else ''} who have taken this mock so far — updates as more take it."
    else:
        first = conn.execute("SELECT id, score FROM ex_attempts WHERE user_id=? AND paper_id=? AND is_ranked LIMIT 1",
                             (a['user_id'], paper['id'])).fetchone()
        rank['note'] = ('Practice attempt — not ranked. This score would sit at the position shown.'
                        if a.get('access') != 'team' else 'Team test attempt — not ranked.')
        rank['ranked_attempt'] = {'attempt_id': first['id'], 'score': first['score']} if first else None

    stats = paper_stats(conn, paper['id'])
    sec_rows = collections.OrderedDict((s['code'], {'code': s['code'], 'name': s['name'], 'questions': int(s['questions']),
                                                    'correct': 0, 'wrong': 0, 'unattempted': 0, 'score': 0, 'time_seconds': 0})
                                       for s in pat['sections'])
    subj_rows = {}
    for r in ans:
        s = sec_rows.setdefault(r['section_code'], {'code': r['section_code'], 'name': r['section_code'], 'questions': 0,
                                                    'correct': 0, 'wrong': 0, 'unattempted': 0, 'score': 0, 'time_seconds': 0})
        k = 'correct' if r['is_correct'] else ('wrong' if r['is_correct'] is False else 'unattempted')
        s[k] += 1
        s['score'] += int(r['marks'] or 0)
        s['time_seconds'] += int(r['time_ms'] or 0) // 1000
        sub = subj_rows.setdefault(r['subject'] or 'Other', {'subject': r['subject'] or 'Other', 'questions': 0, 'attempted': 0,
                                                             'correct': 0, 'wrong': 0, 'score': 0, 'time_seconds': 0})
        sub['questions'] += 1
        sub['attempted'] += 1 if r['chosen'] else 0
        sub['correct'] += 1 if r['is_correct'] else 0
        sub['wrong'] += 1 if r['is_correct'] is False else 0
        sub['score'] += int(r['marks'] or 0)
        sub['time_seconds'] += int(r['time_ms'] or 0) // 1000
    correct_pts = int((pat.get('marking') or {}).get('correct', 4))
    subjects = []
    for sub in sorted(subj_rows.values(), key=lambda x: -x['questions']):
        sub['max'] = sub['questions'] * correct_pts
        sub['accuracy'] = round(100.0 * sub['correct'] / sub['attempted'], 1) if sub['attempted'] else None
        sub['average_score_all'] = stats['subjects'].get(sub['subject'])
        subjects.append(sub)

    order = _display_order(a, paper, items)
    num = {iid: (sec, n) for sec, n, iid in order}
    timed = sorted((r for r in ans if r['time_ms']), key=lambda r: -int(r['time_ms']))[:5]
    on_ok = [int(r['time_ms']) for r in ans if r['is_correct'] and r['time_ms']]
    on_bad = [int(r['time_ms']) for r in ans if r['is_correct'] is False and r['time_ms']]

    pred = None
    if paper['kind'] == 'full':
        p = neet_curve.predict(conn, score, int(a.get('max_score') or pat.get('max_marks') or 0))
        if p:
            pred = dict(p, note=(f"Based on the real NEET PG {p['year']} result ({p['candidates']:,} candidates): "
                                 f"a score of {p['score_720']}/720 got about this All-India rank. It assumes this mock is "
                                 "as hard as the real paper — use it as a guide."))

    return {
        'attempt': {'id': a['id'], 'attempt_no': a['attempt_no'], 'ranked': bool(a.get('is_ranked')),
                    'access': a.get('access'), 'submit_reason': a.get('submit_reason'),
                    'started_at': _iso(started), 'submitted_at': _iso(a.get('submitted_at')),
                    'duration_seconds': int((ended - started).total_seconds())},
        'paper': {'id': paper['id'], 'title': paper['title'], 'kind': paper['kind'],
                  'total_questions': pat.get('total_questions'), 'max_marks': pat.get('max_marks'),
                  'marking': pat.get('marking')},
        'score': {'score': score, 'max_score': a.get('max_score'), 'correct': a.get('n_correct'), 'wrong': a.get('n_wrong'),
                  'unattempted': a.get('n_unattempted'), 'attempted': attempted,
                  'accuracy': round(100.0 * (a.get('n_correct') or 0) / attempted, 1) if attempted else None,
                  'marks_lost_to_negative': neg},
        'rank': rank,
        'predicted_neet': pred,
        'sections': list(sec_rows.values()),
        'subjects': subjects,
        'time': {'total_seconds': total_ms // 1000,
                 'average_per_question_seconds': round(total_ms / 1000 / attempted, 1) if attempted else None,
                 'average_on_correct_seconds': round(sum(on_ok) / 1000 / len(on_ok), 1) if on_ok else None,
                 'average_on_wrong_seconds': round(sum(on_bad) / 1000 / len(on_bad), 1) if on_bad else None,
                 'slowest': [{'item_id': r['item_id'], 'section': num.get(r['item_id'], ('', 0))[0],
                              'number': num.get(r['item_id'], ('', 0))[1], 'seconds': int(r['time_ms']) // 1000,
                              'result': 'correct' if r['is_correct'] else ('wrong' if r['is_correct'] is False else 'skipped')}
                             for r in timed]},
    }


def solutions(conn, a, paper, image_url, section=None):
    """Every question (or one section) with the doctor's answer, the right answer, the explanation and how
    everyone else did."""
    items = {i['id']: i for i in A.paper_items(conn, paper)}
    ans = {r['item_id']: r for r in _answers(conn, a['id'])}
    stats = paper_stats(conn, paper['id'])
    order = _display_order(a, paper, items)
    if section:
        order = [o for o in order if o[0] == section]
    img_ids = [im['id'] for _, _, iid in order for im in (items[iid]['snap'].get('images') or [])]
    img_rows = {}
    if img_ids:
        ph = ','.join('?' * len(img_ids))
        img_rows = {r['id']: dict(r) for r in conn.execute(
            f"SELECT id, file_key FROM ex_question_images WHERE id IN ({ph})", tuple(img_ids)).fetchall()}
    out = []
    for sec, n, iid in order:
        it = items[iid]
        snap = it['snap']
        r = ans.get(iid) or {}
        keys = (a['order'].get('options') or {}).get(str(iid)) or [o[0] for o in snap['options']]
        text = {o[0]: o[1] for o in snap['options']}
        st = stats['items'].get(iid)
        imgs = lambda role: [{'url': image_url(im['id'], img_rows.get(im['id'])), 'width': im.get('width'),
                              'height': im.get('height')}
                             for im in snap.get('images') or [] if im.get('role') == role and im['id'] in img_rows]
        out.append({
            'item_id': iid, 'section': sec, 'number': n, 'stem': snap['stem'], 'images': imgs('stem'),
            'options': [{'key': k, 'text': text.get(k, '')} for k in keys],
            'correct': snap['answer'], 'chosen': r.get('chosen'), 'marked': bool(r.get('marked')),
            'result': 'correct' if r.get('is_correct') else ('wrong' if r.get('is_correct') is False else 'skipped'),
            'marks': r.get('marks'), 'time_seconds': int(r.get('time_ms') or 0) // 1000,
            'subject': snap.get('subject') or '', 'topic': snap.get('topic') or '',
            'explanation': [{'title': t, 'text': x} for t, x in snap.get('sections') or []],
            'explanation_images': imgs('explanation'),
            'everyone': ({'takers': st[0], 'percent_attempted': round(100.0 * st[1] / st[0], 1),
                          'percent_correct': round(100.0 * st[2] / st[0], 1)} if st and st[0] else None),
        })
    return out
