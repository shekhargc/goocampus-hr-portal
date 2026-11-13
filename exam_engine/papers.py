"""Papers (mocks): building them from approved questions, checking, locking, publishing.

A paper copies the exam pattern when it is created (sections, minutes, marking), so a later pattern change
never alters an existing mock. Questions are placed into section slots; on LOCK every question is frozen
into ex_paper_items.snapshot_json — editing the question in the bank afterwards does not change a locked
or published paper. Only a locked paper can be published; unlocking is possible until it is published.
"""
import collections
import json
import random

from exam_engine import store
from exam_engine.tables import scale_blueprint
from exam_engine.importer import checks

KIND_LABEL = {'full': 'Full mock', 'subject': 'Subject test', 'mini': 'Mini test'}
STATUS_LABEL = {'draft': 'Draft', 'locked': 'Locked', 'published': 'Published', 'retired': 'Retired'}


# ── pattern ─────────────────────────────────────────────────────────────────────────────────────────

def pattern_for(kind, cfg):
    """The section layout a new paper of this kind gets, copied from the exam pattern settings."""
    base = {k: cfg.get(k) for k in ('options_per_question', 'marking', 'section_lock', 'section_runs_full_time',
                                    'marked_unanswered_scores', 'language', 'shuffle_questions', 'shuffle_options')
            if k in cfg}
    if kind == 'full':
        sections = [dict(s) for s in cfg.get('sections') or []]
    else:
        spec = cfg.get('subject_test' if kind == 'subject' else 'mini_test') or {}
        sections = [{'code': 'A', 'name': 'Section A', 'questions': int(spec.get('questions') or 30),
                     'minutes': int(spec.get('minutes') or 35)}]
        base['section_lock'] = False
        base['section_runs_full_time'] = False
    base['sections'] = sections
    base['total_questions'] = sum(int(s['questions']) for s in sections)
    base['total_minutes'] = sum(int(s['minutes']) for s in sections)
    base['max_marks'] = base['total_questions'] * int((base.get('marking') or {}).get('correct', 4))
    if kind in ('full', 'mini') and cfg.get('blueprint'):
        base['blueprint'] = scale_blueprint(cfg['blueprint'], base['total_questions'])
    return base


# ── reading ─────────────────────────────────────────────────────────────────────────────────────────

def load(conn, pid):
    r = conn.execute("SELECT * FROM ex_papers WHERE id=?", (pid,)).fetchone()
    if not r:
        return None
    p = dict(r)
    p['pattern'] = json.loads(p.get('pattern_json') or '{}')
    p['frozen'] = p['status'] in ('locked', 'published', 'retired')
    return p


def items(conn, p):
    """Paper items with question details — the frozen copy once locked, the live question while a draft."""
    subj = {s['id']: s['name'] for s in store.subjects(conn, p['exam_code'], p['tenant_id'])}
    rows = [dict(r) for r in conn.execute(
        "SELECT i.id AS item_id, i.section_code, i.position, i.question_id, i.question_version, i.snapshot_json, "
        "q.stem, q.options_json, q.answer, q.sections_json, q.subject_id, q.topic, q.status, q.n_errors, "
        "q.version, q.fingerprint, q.source_no, q.batch_id, "
        "(SELECT COUNT(*) FROM ex_question_images im WHERE im.question_id = q.id AND im.role='stem') AS n_images "
        "FROM ex_paper_items i LEFT JOIN ex_questions q ON q.id = i.question_id "
        "WHERE i.paper_id=? ORDER BY i.section_code, i.position", (p['id'],)).fetchall()]
    for r in rows:
        snap = json.loads(r['snapshot_json']) if r.get('snapshot_json') else None
        r['snap'] = snap
        if snap:
            r['stem'], r['answer'] = snap['stem'], snap['answer']
            r['options'] = [tuple(o) for o in snap['options']]
            r['sections'] = [tuple(s) for s in snap['sections']]
            r['subject'] = snap.get('subject') or ''
            r['topic'] = snap.get('topic') or ''
            r['images'] = snap.get('images') or []
            r['n_images'] = sum(1 for i in r['images'] if i.get('role') == 'stem')
        else:
            r['options'] = [tuple(o) for o in json.loads(r.get('options_json') or '[]')]
            r['sections'] = [tuple(s) for s in json.loads(r.get('sections_json') or '[]')]
            r['subject'] = subj.get(r.get('subject_id'), '')
            r['images'] = None
    return rows


def by_section(p, rows):
    out = collections.OrderedDict()
    for s in p['pattern'].get('sections') or []:
        out[s['code']] = {'spec': s, 'qs': []}
    for r in rows:
        out.setdefault(r['section_code'], {'spec': {'code': r['section_code'], 'name': 'Section ' + r['section_code'],
                                                    'questions': 0, 'minutes': 0}, 'qs': []})['qs'].append(r)
    return out


def usage(conn, qids, exclude_paper=None):
    """{question_id: [{'paper_id', 'title', 'status'}]} — which other papers use each question."""
    if not qids:
        return {}
    out = collections.defaultdict(list)
    ph = ','.join('?' * len(qids))
    params = list(qids)
    sql = (f"SELECT i.question_id, p.id AS paper_id, p.title, p.status FROM ex_paper_items i "
           f"JOIN ex_papers p ON p.id = i.paper_id WHERE i.question_id IN ({ph})")
    if exclude_paper:
        sql += " AND p.id <> ?"
        params.append(exclude_paper)
    for r in conn.execute(sql + " ORDER BY p.id", tuple(params)).fetchall():
        out[r['question_id']].append({'paper_id': r['paper_id'], 'title': r['title'], 'status': r['status']})
    return out


def subject_counts(rows):
    return collections.Counter(r.get('subject') or 'Not set' for r in rows)


# ── building ────────────────────────────────────────────────────────────────────────────────────────

def _free_slots(p, rows):
    taken = collections.defaultdict(set)
    for r in rows:
        taken[r['section_code']].add(r['position'])
    slots = []
    for s in p['pattern'].get('sections') or []:
        for pos in range(1, int(s['questions']) + 1):
            if pos not in taken[s['code']]:
                slots.append((s['code'], pos))
    return slots


def add_questions(conn, p, qids, section=None):
    """Places questions into the first free slots (of `section` if given). → (added, skipped [(qid, why)])."""
    rows = items(conn, p)
    have = {r['question_id'] for r in rows}
    slots = _free_slots(p, rows)
    if section:
        slots = [s for s in slots if s[0] == section] + [s for s in slots if s[0] != section]
    added, skipped = 0, []
    for qid in qids:
        if qid in have:
            skipped.append((qid, 'already in this paper'))
            continue
        q = conn.execute("SELECT status, n_errors, tenant_id, exam_code FROM ex_questions WHERE id=?", (qid,)).fetchone()
        if not q or q['tenant_id'] != p['tenant_id'] or q['exam_code'] != p['exam_code']:
            skipped.append((qid, 'not found'))
            continue
        if q['status'] != 'approved' or q['n_errors']:
            skipped.append((qid, 'not approved'))
            continue
        if not slots:
            skipped.append((qid, 'the paper is full'))
            continue
        sec, pos = slots.pop(0)
        conn.execute("INSERT INTO ex_paper_items (paper_id, section_code, position, question_id) VALUES (?, ?, ?, ?)",
                     (p['id'], sec, pos, qid))
        have.add(qid)
        added += 1
    touch(conn, p['id'])
    return added, skipped


def remove_item(conn, p, item_id):
    conn.execute("DELETE FROM ex_paper_items WHERE id=? AND paper_id=?", (item_id, p['id']))
    compact(conn, p)
    touch(conn, p['id'])


def clear(conn, p):
    conn.execute("DELETE FROM ex_paper_items WHERE paper_id=?", (p['id'],))
    touch(conn, p['id'])


def compact(conn, p):
    """Closes gaps so each section's questions are numbered 1, 2, 3 …"""
    for s in p['pattern'].get('sections') or []:
        ids = [r['id'] for r in conn.execute("SELECT id FROM ex_paper_items WHERE paper_id=? AND section_code=? "
                                             "ORDER BY position, id", (p['id'], s['code'])).fetchall()]
        for i, iid in enumerate(ids, 1):
            conn.execute("UPDATE ex_paper_items SET position=? WHERE id=?", (-i, iid))   # avoid clashes mid-way
        conn.execute("UPDATE ex_paper_items SET position=-position WHERE paper_id=? AND section_code=? AND position < 0",
                     (p['id'], s['code']))


def move_item(conn, p, item_id, direction):
    """'up' / 'down' within the section, or 'to:<code>' to the end of another section (if it has room)."""
    it = conn.execute("SELECT id, section_code, position FROM ex_paper_items WHERE id=? AND paper_id=?",
                      (item_id, p['id'])).fetchone()
    if not it:
        return 'Not found.'
    if direction in ('up', 'down'):
        other_pos = it['position'] - 1 if direction == 'up' else it['position'] + 1
        other = conn.execute("SELECT id FROM ex_paper_items WHERE paper_id=? AND section_code=? AND position=?",
                             (p['id'], it['section_code'], other_pos)).fetchone()
        if not other:
            return None
        conn.execute("UPDATE ex_paper_items SET position=? WHERE id=?", (-1, it['id']))
        conn.execute("UPDATE ex_paper_items SET position=? WHERE id=?", (it['position'], other['id']))
        conn.execute("UPDATE ex_paper_items SET position=? WHERE id=?", (other_pos, it['id']))
    elif direction.startswith('to:'):
        code = direction[3:]
        spec = next((s for s in p['pattern'].get('sections') or [] if s['code'] == code), None)
        if not spec:
            return 'No such section.'
        n = conn.execute("SELECT COUNT(*) AS n FROM ex_paper_items WHERE paper_id=? AND section_code=?",
                         (p['id'], code)).fetchone()['n']
        if n >= int(spec['questions']):
            return f'Section {code} is already full.'
        conn.execute("UPDATE ex_paper_items SET section_code=?, position=? WHERE id=?", (code, 10000, it['id']))
        compact(conn, p)
    touch(conn, p['id'])
    return None


def candidates(conn, p, subject_id=None, text='', topic='', unused_only=False, with_image=False, limit=60):
    """Approved, problem-free questions not yet in this paper — for the picker."""
    sql = ("SELECT q.id, q.stem, q.subject_id, q.topic, q.answer, q.source_no, q.batch_id, "
           "(SELECT COUNT(*) FROM ex_question_images im WHERE im.question_id = q.id AND im.role='stem') AS n_images, "
           "(SELECT COUNT(*) FROM ex_paper_items pi WHERE pi.question_id = q.id) AS n_used "
           "FROM ex_questions q WHERE q.tenant_id=? AND q.exam_code=? AND q.status='approved' AND q.n_errors=0 "
           "AND q.id NOT IN (SELECT question_id FROM ex_paper_items WHERE paper_id=?)")
    params = [p['tenant_id'], p['exam_code'], p['id']]
    if subject_id:
        sql += " AND q.subject_id=?"
        params.append(subject_id)
    if text:
        sql += " AND q.stem ILIKE ?"
        params.append('%' + text + '%')
    if topic:
        sql += " AND q.topic ILIKE ?"
        params.append('%' + topic + '%')
    if unused_only:
        sql += " AND NOT EXISTS (SELECT 1 FROM ex_paper_items pi WHERE pi.question_id = q.id)"
    if with_image:
        sql += " AND EXISTS (SELECT 1 FROM ex_question_images im WHERE im.question_id = q.id AND im.role='stem')"
    sql += " ORDER BY n_used, q.id LIMIT ?"
    params.append(limit)
    subj = {s['id']: s['name'] for s in store.subjects(conn, p['exam_code'], p['tenant_id'])}
    out = [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
    for r in out:
        r['subject'] = subj.get(r['subject_id'], '')
    return out


def autofill(conn, p, any_subject=False, rng=None):
    """Fills the empty slots: the subject mix from the pattern (full / mini) or the test's subject (subject test),
    preferring questions not used in any other paper, then spreading subjects across the sections.
    → {'added', 'short': {subject: (wanted, found)}, 'filled_from_any'}"""
    rng = rng or random.Random()
    rows = items(conn, p)
    slots = _free_slots(p, rows)
    if not slots:
        return {'added': 0, 'short': {}, 'filled_from_any': 0}
    subj_rows = store.subjects(conn, p['exam_code'], p['tenant_id'])
    name_of = {s['id']: s['name'] for s in subj_rows}
    pool = [dict(r) for r in conn.execute(
        "SELECT q.id, q.subject_id, q.fingerprint, (SELECT COUNT(*) FROM ex_paper_items pi WHERE pi.question_id = q.id) AS n_used "
        "FROM ex_questions q WHERE q.tenant_id=? AND q.exam_code=? AND q.status='approved' AND q.n_errors=0 "
        "AND q.id NOT IN (SELECT question_id FROM ex_paper_items WHERE paper_id=?)",
        (p['tenant_id'], p['exam_code'], p['id'])).fetchall()]
    have_fp = {r['fingerprint'] for r in rows if r.get('fingerprint')}
    rng.shuffle(pool)
    pool.sort(key=lambda r: r['n_used'])            # unused first, random within each group
    by_subj = collections.defaultdict(list)
    for r in pool:
        by_subj[name_of.get(r['subject_id'], '')].append(r)

    current = subject_counts(rows)
    if p['kind'] == 'subject':
        want = {name_of.get(p.get('subject_id'), ''): len(slots)}
    else:
        bp = p['pattern'].get('blueprint') or {}
        want = {k: max(0, v - current.get(k, 0)) for k, v in bp.items()}
        # trim to the free slots (largest wants keep their share)
        while sum(want.values()) > len(slots):
            k = max(want, key=lambda x: want[x])
            want[k] -= 1
    picked, short = [], {}
    for subject, n in want.items():
        got = []
        for r in by_subj.get(subject, []):
            if len(got) >= n:
                break
            if r['fingerprint'] in have_fp:
                continue
            got.append(r)
            have_fp.add(r['fingerprint'])
        if len(got) < n:
            short[subject] = (n, len(got))
        picked.extend(got)
    picked_ids = {r['id'] for r in picked}
    from_any = 0
    if any_subject and len(picked) < len(slots):
        for r in pool:
            if len(picked) >= len(slots):
                break
            if r['id'] in picked_ids or r['fingerprint'] in have_fp:
                continue
            if p['kind'] == 'subject' and r['subject_id'] != p.get('subject_id'):
                continue
            picked.append(r)
            picked_ids.add(r['id'])
            have_fp.add(r['fingerprint'])
            from_any += 1
    # round-robin by subject so every section gets a mix (NBEMS sections are mixed-subject)
    groups = collections.defaultdict(list)
    for r in picked:
        groups[r['subject_id']].append(r)
    order = []
    keys = list(groups)
    rng.shuffle(keys)
    while any(groups.values()):
        for k in keys:
            if groups[k]:
                order.append(groups[k].pop())
    for (sec, pos), r in zip(slots, order):
        conn.execute("INSERT INTO ex_paper_items (paper_id, section_code, position, question_id) VALUES (?, ?, ?, ?)",
                     (p['id'], sec, pos, r['id']))
    touch(conn, p['id'])
    return {'added': min(len(slots), len(order)), 'short': short, 'filled_from_any': from_any}


# ── checking, locking, publishing ───────────────────────────────────────────────────────────────────

def lock_check(conn, p, rows=None):
    """→ (problems that block locking, notes). Plain words for the team."""
    rows = rows if rows is not None else items(conn, p)
    errors, notes = [], []
    secs = by_section(p, rows)
    for code, s in secs.items():
        need, have = int(s['spec']['questions']), len(s['qs'])
        if have != need:
            errors.append(f"{s['spec']['name']} has {have} of {need} questions.")
    bad = [r for r in rows if r.get('status') != 'approved' or r.get('n_errors')]
    if bad and not p['frozen']:
        errors.append(f"{len(bad)} question(s) are no longer approved or now have problems: "
                      + ', '.join(f"#{r['question_id']}" for r in bad[:10]) + ('…' if len(bad) > 10 else ''))
    fps = collections.Counter(r.get('fingerprint') for r in rows if r.get('fingerprint'))
    dups = [fp for fp, n in fps.items() if n > 1]
    if dups:
        errors.append(f"{len(dups)} question(s) appear twice (same text and options).")
    if p['kind'] == 'subject' and p.get('subject_id'):
        name = {s['id']: s['name'] for s in store.subjects(conn, p['exam_code'], p['tenant_id'])}.get(p['subject_id'])
        off = [r for r in rows if r.get('subject') != name]
        if off:
            notes.append(f"{len(off)} question(s) are not {name} questions.")
    bp = p['pattern'].get('blueprint') or {}
    if bp and rows:
        cur = subject_counts(rows)
        diff = [f"{k} {cur.get(k, 0)}/{v}" for k, v in bp.items() if abs(cur.get(k, 0) - v) >= 3]
        if diff:
            notes.append('Subject mix differs from the pattern by 3+ in: ' + ', '.join(diff) + '.')
    ans = collections.Counter(r.get('answer') for r in rows if r.get('answer'))
    if rows and ans:
        top, n = ans.most_common(1)[0]
        if n / len(rows) > 0.4:
            notes.append(f'“{top}” is the correct answer in {round(100 * n / len(rows))}% of questions.')
    used = usage(conn, [r['question_id'] for r in rows], exclude_paper=p['id'])
    reused = [qid for qid, us in used.items() if any(u['status'] in ('locked', 'published') for u in us)]
    if reused:
        notes.append(f"{len(reused)} question(s) are also in another locked/published paper.")
    return errors, notes


def lock(conn, p, user):
    """Freezes every question into the paper. → list of problems (empty = locked)."""
    rows = items(conn, p)
    errors, _ = lock_check(conn, p, rows)
    if errors:
        return errors
    for r in rows:
        imgs = store.images_for(conn, r['question_id'])
        snap = {'stem': r['stem'], 'options': r['options'], 'answer': r['answer'], 'sections': r['sections'],
                'subject_id': r.get('subject_id'), 'subject': r.get('subject'), 'topic': r.get('topic') or '',
                'images': [{'id': i['id'], 'role': i['role'], 'ext': i['ext'], 'width': i['width'], 'height': i['height']}
                           for i in imgs],
                'version': r.get('version')}
        conn.execute("UPDATE ex_paper_items SET snapshot_json=?, question_version=? WHERE id=?",
                     (json.dumps(snap), r.get('version'), r['item_id']))
    conn.execute("UPDATE ex_papers SET status='locked', locked_by=?, locked_at=CURRENT_TIMESTAMP, "
                 "updated_at=CURRENT_TIMESTAMP WHERE id=?", (user, p['id']))
    return []


def attempts_count(conn, pid):
    """Doctors' attempts on this paper (the exam player arrives in step 5; until then there are none)."""
    try:
        r = conn.execute("SELECT to_regclass('ex_attempts') AS t").fetchone()
        if not r or not r['t']:
            return 0
        return conn.execute("SELECT COUNT(*) AS n FROM ex_attempts WHERE paper_id=?", (pid,)).fetchone()['n']
    except Exception:
        conn.rollback()
        return 0


def unlock(conn, p, user):
    if p['status'] != 'locked':
        return 'Only a locked (not published) paper can be unlocked.'
    if attempts_count(conn, p['id']):
        return 'Doctors have already taken this paper, so it can\'t be changed.'
    conn.execute("UPDATE ex_paper_items SET snapshot_json=NULL, question_version=NULL WHERE paper_id=?", (p['id'],))
    conn.execute("UPDATE ex_papers SET status='draft', locked_by='', locked_at=NULL, updated_at=CURRENT_TIMESTAMP "
                 "WHERE id=?", (p['id'],))
    return None


def set_status(conn, p, action, user):
    if action == 'publish':
        if p['status'] != 'locked':
            return 'Lock the paper before publishing it.'
        conn.execute("UPDATE ex_papers SET status='published', published_by=?, published_at=CURRENT_TIMESTAMP, "
                     "updated_at=CURRENT_TIMESTAMP WHERE id=?", (user, p['id']))
    elif action == 'unpublish':
        if p['status'] != 'published':
            return 'This paper is not published.'
        conn.execute("UPDATE ex_papers SET status='locked', updated_at=CURRENT_TIMESTAMP WHERE id=?", (p['id'],))
    elif action == 'retire':
        if p['status'] not in ('published', 'locked'):
            return 'Only a locked or published paper can be retired.'
        conn.execute("UPDATE ex_papers SET status='retired', updated_at=CURRENT_TIMESTAMP WHERE id=?", (p['id'],))
    elif action == 'restore':
        if p['status'] != 'retired':
            return 'This paper is not retired.'
        conn.execute("UPDATE ex_papers SET status='locked', updated_at=CURRENT_TIMESTAMP WHERE id=?", (p['id'],))
    else:
        return 'Unknown action.'
    return None


def image_in_frozen_paper(conn, image_id, question_id):
    """True when a locked/published paper shows this picture (so it must not be deleted)."""
    for r in conn.execute("SELECT snapshot_json FROM ex_paper_items WHERE question_id=? AND snapshot_json IS NOT NULL",
                          (question_id,)).fetchall():
        try:
            if any(i.get('id') == image_id for i in json.loads(r['snapshot_json']).get('images') or []):
                return True
        except Exception:
            continue
    return False


def touch(conn, pid):
    conn.execute("UPDATE ex_papers SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (pid,))
