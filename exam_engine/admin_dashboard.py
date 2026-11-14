"""Mock Tests › Dashboard, Attempts, per-mock Analytics — the team's view of how the mocks are doing (admin only).

  /admin/pg/mocks                          overview: takers, attempts, free-sample → package conversion, sales,
                                           every mock's numbers, latest attempts
  /admin/pg/mocks/attempts                 every attempt (filters: mock, status, flagged, doctor) + CSV
  /admin/pg/mocks/attempts/<aid>           one attempt: score, rank, flags (tab switches …), timeline, answers
  /admin/pg/mocks/papers/<pid>/analytics   score spread, section/subject averages, and "questions to check" —
                                           very few got it right, or strong doctors did worse than weak ones
                                           (often a wrong answer key)
Doctor names come from pg_users (goocampus.in accounts) and are shown as "Dr. <name>".
"""
import csv
import io
import re
import statistics

from flask import render_template, request, Response, abort

from db import get_db
from core.auth import login_required
from exam_engine import attempts as A, papers as P, results as R, store
from exam_engine.admin import _admin, _deny, _close, EXAM_CODE
from exam_engine.tables import TENANT_GOOCAMPUS_IN

FLAG_KINDS = ('tab_hidden', 'fullscreen_exit', 'offline', 'copy_attempt', 'right_click', 'devtools')
FLAG_LABEL = {'tab_hidden': 'Left the tab', 'fullscreen_exit': 'Left full screen', 'offline': 'Went offline',
              'copy_attempt': 'Tried to copy', 'right_click': 'Right-clicked', 'devtools': 'Opened dev tools'}


def dr(name, fallback=''):
    n = (name or '').strip()
    if not n:
        return fallback
    # "Dr. Asha" / "Dr Asha" stay as they are; "Drishti" is a name, not a title, so it still gets "Dr."
    return n if re.match(r'^dr[.\s]', n, re.I) else 'Dr. ' + n


def _fmt_secs(s):
    s = int(s or 0)
    return f'{s // 3600}h {s % 3600 // 60:02d}m' if s >= 3600 else f'{s // 60}m {s % 60:02d}s'


# ── overview ────────────────────────────────────────────────────────────────────────────────────────

@login_required
def dashboard():
    if not _admin():
        return _deny()
    conn = get_db()
    try:
        t = (TENANT_GOOCAMPUS_IN, EXAM_CODE)
        k = conn.execute(
            "SELECT COUNT(*) AS attempts, COUNT(DISTINCT user_id) AS takers, "
            "SUM(CASE WHEN status='in_progress' THEN 1 ELSE 0 END) AS live, "
            "SUM(CASE WHEN status='submitted' AND submitted_at > CURRENT_TIMESTAMP - INTERVAL '1 day' THEN 1 ELSE 0 END) AS day, "
            "SUM(CASE WHEN status='submitted' AND submitted_at > CURRENT_TIMESTAMP - INTERVAL '7 days' THEN 1 ELSE 0 END) AS week "
            "FROM ex_attempts WHERE tenant_id=? AND exam_code=? AND access <> 'team'", t).fetchone()
        free = conn.execute(
            "SELECT COUNT(DISTINCT a.user_id) AS n, "
            "COUNT(DISTINCT CASE WHEN EXISTS (SELECT 1 FROM ex_package_purchases pp WHERE pp.user_id = a.user_id "
            "AND pp.source <> 'admin_grant') THEN a.user_id END) AS bought "
            "FROM ex_attempts a JOIN ex_papers p ON p.id = a.paper_id WHERE p.tenant_id=? AND p.exam_code=? "
            "AND p.is_free_sample=1 AND a.access <> 'team'", t).fetchone()
        sales = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(price_paid), 0) AS revenue, COUNT(DISTINCT user_id) AS buyers "
            "FROM ex_package_purchases WHERE tenant_id=? AND status='active' AND source <> 'admin_grant'",
            (TENANT_GOOCAMPUS_IN,)).fetchone()
        sales_week = conn.execute(
            "SELECT COALESCE(SUM(price_paid), 0) AS r FROM ex_package_purchases WHERE tenant_id=? AND status='active' "
            "AND created_at > CURRENT_TIMESTAMP - INTERVAL '7 days'", (TENANT_GOOCAMPUS_IN,)).fetchone()['r']
        bank = conn.execute("SELECT SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) AS approved, "
                            "SUM(CASE WHEN status='draft' THEN 1 ELSE 0 END) AS draft FROM ex_questions "
                            "WHERE tenant_id=? AND exam_code=?", t).fetchone()
        papers = [dict(r) for r in conn.execute(
            "SELECT p.id, p.title, p.kind, p.status, p.is_free_sample, "
            "(SELECT COUNT(*) FROM ex_attempts a WHERE a.paper_id = p.id AND a.is_ranked) AS ranked, "
            "(SELECT COUNT(*) FROM ex_attempts a WHERE a.paper_id = p.id AND a.status='in_progress') AS live, "
            "(SELECT COUNT(*) FROM ex_attempts a WHERE a.paper_id = p.id AND a.status='submitted' AND NOT a.is_ranked) AS practice, "
            "(SELECT AVG(score) FROM ex_attempts a WHERE a.paper_id = p.id AND a.is_ranked) AS avg_score, "
            "(SELECT MAX(score) FROM ex_attempts a WHERE a.paper_id = p.id AND a.is_ranked) AS top_score, "
            "(SELECT MAX(max_score) FROM ex_attempts a WHERE a.paper_id = p.id) AS max_score "
            "FROM ex_papers p WHERE p.tenant_id=? AND p.exam_code=? AND p.status IN ('published','locked','retired') "
            "ORDER BY p.status='retired', p.sort_order, p.id", t).fetchall()]
        recent = _attempt_rows(conn, limit=15)
        takers = int(free['n'] or 0)
        return render_template('exam_engine/dashboard.html', tab='ex_dashboard', k=dict(k), sales=dict(sales),
                               sales_week=float(sales_week or 0), bank=dict(bank), papers=papers, recent=recent,
                               free_takers=takers, free_bought=int(free['bought'] or 0),
                               conversion=round(100.0 * int(free['bought'] or 0) / takers, 1) if takers else None,
                               kind_label=P.KIND_LABEL)
    finally:
        _close(conn)


# ── attempts ────────────────────────────────────────────────────────────────────────────────────────

def _attempt_rows(conn, paper_id=None, status='', flagged=False, q='', ranked='', limit=200, offset=0):
    sql = ("SELECT a.id, a.paper_id, a.user_id, a.attempt_no, a.status, a.submit_reason, a.access, a.is_ranked, "
           "a.started_at, a.submitted_at, a.score, a.max_score, a.n_correct, a.n_wrong, a.n_unattempted, a.cur_section, "
           "p.title AS paper_title, p.kind, u.name AS doctor_name, u.mobile, "
           "(SELECT COUNT(*) FROM ex_attempt_events e WHERE e.attempt_id = a.id AND e.kind IN ("
           + ','.join('?' * len(FLAG_KINDS)) + ")) AS n_flags "
           "FROM ex_attempts a JOIN ex_papers p ON p.id = a.paper_id LEFT JOIN pg_users u ON u.id = a.user_id "
           "WHERE a.tenant_id=? AND a.exam_code=?")
    params = list(FLAG_KINDS) + [TENANT_GOOCAMPUS_IN, EXAM_CODE]
    if paper_id:
        sql += " AND a.paper_id=?"
        params.append(paper_id)
    if status in ('in_progress', 'submitted'):
        sql += " AND a.status=?"
        params.append(status)
    if ranked == '1':
        sql += " AND a.is_ranked"
    elif ranked == '0':
        sql += " AND NOT a.is_ranked"
    if q:
        sql += " AND (u.name ILIKE ? OR u.mobile ILIKE ?)"
        params += ['%' + q + '%', '%' + q + '%']
    if flagged:
        sql += (" AND EXISTS (SELECT 1 FROM ex_attempt_events e WHERE e.attempt_id = a.id AND e.kind IN ("
                + ','.join('?' * len(FLAG_KINDS)) + "))")
        params += list(FLAG_KINDS)
    sql += " ORDER BY a.id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
    rank_cache = {}
    for r in rows:
        r['doctor'] = dr(r.get('doctor_name'), f"#{r['user_id']}")
        r['started'] = store.now_ist_str(r['started_at'])
        r['submitted'] = store.now_ist_str(r['submitted_at'])
        if r['status'] == 'submitted' and r['score'] is not None:
            key = (r['paper_id'], r['score'])
            if key not in rank_cache:
                rank_cache[key] = R.rank_of(conn, r['paper_id'], r['score'])
            rk = rank_cache[key]
            r['rank'] = int(rk['higher']) + 1 if rk['n'] else None
            r['out_of'] = int(rk['n'] or 0)
    return rows


@login_required
def attempts_list():
    if not _admin():
        return _deny()
    a = request.args
    try:
        paper_id = int(a.get('paper') or 0) or None
    except ValueError:
        paper_id = None
    conn = get_db()
    try:
        rows = _attempt_rows(conn, paper_id, a.get('status', ''), a.get('flagged') == '1', (a.get('q') or '').strip(),
                             a.get('ranked', ''), limit=5000 if a.get('csv') else 300)
        if a.get('csv'):
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(['Attempt', 'Doctor', 'Mobile', 'Mock', 'Attempt no', 'Ranked', 'Access', 'Status', 'How ended',
                        'Started (IST)', 'Submitted (IST)', 'Score', 'Max', 'Correct', 'Wrong', 'Skipped', 'Rank',
                        'Out of', 'Flags'])
            for r in rows:
                w.writerow([r['id'], r['doctor'], r.get('mobile') or '', r['paper_title'], r['attempt_no'],
                            'yes' if r['is_ranked'] else 'no', r['access'], r['status'], r.get('submit_reason') or '',
                            r['started'], r['submitted'], r['score'], r['max_score'], r['n_correct'], r['n_wrong'],
                            r['n_unattempted'], r.get('rank') or '', r.get('out_of') or '', r['n_flags']])
            return Response(out.getvalue(), mimetype='text/csv',
                            headers={'Content-Disposition': 'attachment; filename="mock_attempts.csv"'})
        papers = [dict(r) for r in conn.execute(
            "SELECT id, title FROM ex_papers WHERE tenant_id=? AND exam_code=? AND status IN ('published','locked','retired') "
            "ORDER BY sort_order, id", (TENANT_GOOCAMPUS_IN, EXAM_CODE)).fetchall()]
        return render_template('exam_engine/attempts.html', tab='ex_dashboard', rows=rows, papers=papers,
                               f={'paper': str(paper_id or ''), 'status': a.get('status', ''), 'flagged': a.get('flagged', ''),
                                  'q': a.get('q', ''), 'ranked': a.get('ranked', '')})
    finally:
        _close(conn)


@login_required
def attempt_detail(aid):
    if not _admin():
        return _deny()
    conn = get_db()
    try:
        a = A.load(conn, aid)
        if not a:
            abort(404)
        p = P.load(conn, a['paper_id'])
        A.advance(conn, a, p)
        conn.commit()
        u = conn.execute("SELECT * FROM pg_users WHERE id=?", (a['user_id'],)).fetchone()
        u = dict(u) if u else {}
        u = {'id': a['user_id'], 'name': u.get('name') or '', 'mobile': u.get('mobile') or '', 'email': u.get('email') or ''}
        events = [dict(r) for r in conn.execute(
            "SELECT kind, detail, created_at FROM ex_attempt_events WHERE attempt_id=? ORDER BY id", (aid,)).fetchall()]
        for e in events:
            e['when'] = store.now_ist_str(e['created_at'])
            e['label'] = FLAG_LABEL.get(e['kind'], e['kind'].replace('_', ' ').capitalize())
            e['flag'] = e['kind'] in FLAG_KINDS
        flag_counts = {}
        for e in events:
            if e['flag']:
                flag_counts[e['label']] = flag_counts.get(e['label'], 0) + 1
        res = R.result(conn, a, p) if a['status'] == 'submitted' else None
        answers = []
        if a['status'] == 'submitted':
            answers = R.solutions(conn, a, p, lambda iid, row: '')
        else:
            sec_left, total_left = A.remaining(a)
            res = {'live': True, 'section': a['sections'][a['cur_section']]['code'],
                   'section_left': _fmt_secs(sec_left), 'total_left': _fmt_secs(total_left),
                   'answered': conn.execute("SELECT COUNT(*) AS n FROM ex_attempt_answers WHERE attempt_id=? "
                                            "AND chosen IS NOT NULL", (aid,)).fetchone()['n']}
        return render_template('exam_engine/attempt.html', tab='ex_dashboard', a=a, p=p, u=u, doctor=dr(u.get('name'), f"#{u['id']}"),
                               events=events, flag_counts=flag_counts, res=res, answers=answers,
                               started=store.now_ist_str(a['started_at']), submitted=store.now_ist_str(a.get('submitted_at')),
                               fmt=_fmt_secs)
    finally:
        _close(conn)


# ── per-mock analytics ──────────────────────────────────────────────────────────────────────────────

@login_required
def paper_analytics(pid):
    if not _admin():
        return _deny()
    conn = get_db()
    try:
        p = P.load(conn, pid)
        if not p or p['tenant_id'] != TENANT_GOOCAMPUS_IN:
            abort(404)
        scores = [r['score'] for r in conn.execute(
            "SELECT score FROM ex_attempts WHERE paper_id=? AND is_ranked ORDER BY score DESC", (pid,)).fetchall()]
        n = len(scores)
        mx = int(p['pattern'].get('max_marks') or 720)
        summary = {'n': n, 'avg': round(statistics.mean(scores), 1) if n else None,
                   'median': statistics.median(scores) if n else None, 'top': scores[0] if n else None,
                   'low': scores[-1] if n else None}
        # score spread in bins of 10% of max marks
        step = max(1, mx // 10)
        lo_edge = min([0] + scores)
        bins = []
        edge = (lo_edge // step) * step
        while edge < mx:
            c = sum(1 for s in scores if edge <= s < edge + step or (edge + step >= mx and s == mx))
            bins.append({'from': edge, 'to': min(mx, edge + step), 'n': c})
            edge += step
        peak = max([b['n'] for b in bins] or [1]) or 1

        items = {i['id']: i for i in A.paper_items(conn, p)}
        # per-question stats over ranked attempts, plus "discrimination": top 27% vs bottom 27% by score
        rows = conn.execute(
            "SELECT aa.item_id, aa.chosen, aa.is_correct, aa.time_ms, a.score FROM ex_attempt_answers aa "
            "JOIN ex_attempts a ON a.id = aa.attempt_id WHERE a.paper_id=? AND a.is_ranked", (pid,)).fetchall()
        cut = max(1, int(round(n * 0.27))) if n else 0
        top_cut = scores[cut - 1] if n else None
        low_cut = scores[-cut] if n else None
        st = {}
        for r in rows:
            s = st.setdefault(r['item_id'], {'n': 0, 'att': 0, 'ok': 0, 'ms': 0, 'top_n': 0, 'top_ok': 0, 'low_n': 0,
                                             'low_ok': 0, 'choices': {}})
            s['n'] += 1
            if r['chosen']:
                s['att'] += 1
                s['choices'][r['chosen']] = s['choices'].get(r['chosen'], 0) + 1
            s['ok'] += 1 if r['is_correct'] else 0
            s['ms'] += int(r['time_ms'] or 0)
            if n >= 10 and r['score'] >= top_cut:
                s['top_n'] += 1
                s['top_ok'] += 1 if r['is_correct'] else 0
            if n >= 10 and r['score'] <= low_cut:
                s['low_n'] += 1
                s['low_ok'] += 1 if r['is_correct'] else 0
        qrows = []
        for it in sorted(items.values(), key=lambda x: (x['section_code'], x['position'])):
            s = st.get(it['id'], {'n': 0})
            snap = it['snap']
            row = {'item_id': it['id'], 'question_id': it['question_id'], 'section': it['section_code'],
                   'position': it['position'], 'stem': snap['stem'][:140], 'answer': snap['answer'],
                   'subject': snap.get('subject') or '', 'n': s.get('n', 0)}
            if s.get('n'):
                row['pct_correct'] = round(100.0 * s['ok'] / s['n'], 1)
                row['pct_attempted'] = round(100.0 * s['att'] / s['n'], 1)
                row['avg_secs'] = round(s['ms'] / 1000 / s['n'])
                top_choice = max(s['choices'].items(), key=lambda kv: kv[1]) if s['choices'] else None
                row['top_choice'] = top_choice[0] if top_choice else None
                row['top_choice_pct'] = round(100.0 * top_choice[1] / s['att'], 0) if top_choice else None
                row['disc'] = (round(s['top_ok'] / s['top_n'] - s['low_ok'] / s['low_n'], 2)
                               if s.get('top_n') and s.get('low_n') else None)
                why = []
                if n >= 10 and row['pct_correct'] < 15:
                    why.append(f"only {row['pct_correct']}% got it right")
                if row.get('disc') is not None and row['disc'] < 0:
                    why.append('strong doctors did worse than weak ones')
                if (row.get('top_choice') and row['top_choice'] != row['answer'] and (row['top_choice_pct'] or 0) >= 50
                        and n >= 10):
                    why.append(f"most chose {row['top_choice']}, the key says {row['answer']}")
                row['check'] = '; '.join(why)
            qrows.append(row)
        to_check = [r for r in qrows if r.get('check')]
        subj = {}
        for r in conn.execute(
                "SELECT aa.subject, SUM(aa.marks) AS m, COUNT(*) AS q, SUM(CASE WHEN aa.is_correct THEN 1 ELSE 0 END) AS ok "
                "FROM ex_attempt_answers aa JOIN ex_attempts a ON a.id = aa.attempt_id WHERE a.paper_id=? AND a.is_ranked "
                "GROUP BY aa.subject ORDER BY aa.subject", (pid,)).fetchall():
            subj[r['subject'] or 'Other'] = {'avg': round(float(r['m'] or 0) / n, 1) if n else 0,
                                             'pct': round(100.0 * int(r['ok'] or 0) / int(r['q']), 1) if r['q'] else 0,
                                             'per_taker_q': round(int(r['q']) / n) if n else 0}
        return render_template('exam_engine/paper_analytics.html', tab='ex_dashboard', p=p, summary=summary, bins=bins,
                               peak=peak, qrows=qrows, to_check=to_check, subj=subj, mx=mx,
                               live=conn.execute("SELECT COUNT(*) AS n FROM ex_attempts WHERE paper_id=? AND status='in_progress'",
                                                 (pid,)).fetchone()['n'],
                               practice=conn.execute("SELECT COUNT(*) AS n FROM ex_attempts WHERE paper_id=? AND status='submitted' "
                                                     "AND NOT is_ranked", (pid,)).fetchone()['n'])
    finally:
        _close(conn)


def register_routes(app):
    r = app.add_url_rule
    r('/admin/pg/mocks', 'ex_dashboard', dashboard, methods=['GET'])
    r('/admin/pg/mocks/attempts', 'ex_attempts', attempts_list, methods=['GET'])
    r('/admin/pg/mocks/attempts/<int:aid>', 'ex_attempt', attempt_detail, methods=['GET'])
    r('/admin/pg/mocks/papers/<int:pid>/analytics', 'ex_paper_analytics', paper_analytics, methods=['GET'])
