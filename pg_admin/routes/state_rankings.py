"""GooCampus College Rankings 2026 — STATE counselling authorities (founder 2026-10-31).

The MCC rankings (rankings.py) extended to every state whose 2026 seat matrix is loaded
(pg_seat_matrix_source: authority_code <> 'mcc', section 'state', not superseded) — a new state
appears by itself once its matrix is imported. Each state is split into FOUR lists by kind of seat
(founder: "keep Management separate and NRI separate"):
  govt        — Government colleges (state / government / institutional quota seats)
  private     — Private colleges (incl. private universities, deemed in state counselling): every seat
                that is NOT Management / NRI (e.g. Karnataka Govt-quota + GMP / Open / Minority, UP Private Quota)
  management  — Management Quota seats (government or private colleges)
  nri         — NRI Quota seats
In-service, DNB and diploma seats are left out (as MCC's lists are MD/MS only).

Tiers Top / Good / Average are a DRAFT computed live from last year's same-state main rounds (Round 1, else
Round 2; mop-up / stray ignored; Open/General category — any category for Management / NRI): course against
course — in each course a college's place among the colleges offering it — averaged over its clinical courses
(all courses if none) → first 20% Top, next 35% Good, rest Average (the MCC bands). The team overrides any college on the Desk (stored in pg_college_tiers under list_key
'st:<authority>:<list>'; a stored tier always wins over the draft). Colleges with no 2025 cut-off in this
state are never tiered — 'New'. Rows show college, state, type and 2026 seats — no ranks.
"""
import logging
import statistics
from collections import defaultdict

from flask import request, jsonify

from db import get_db
from pg_admin.routes import recommended as rec

LISTS = {
    'govt': 'Government colleges',
    'private': 'Private colleges',
    'management': 'Management Quota',
    'nri': 'NRI Quota',
}
_TIER_ORDER = ('Top', 'Good', 'Average')
# 2025 cut-off categories that are the open / general merit pool (per state's own wording)
_OPEN = {'UR', 'GEN', 'GN', 'OP', 'OPEN', 'OM', 'GM', 'GMP', 'OPN', 'MNG', 'MQ', 'NRI', 'UR/X/OP', 'GENERAL'}


def _s(v):
    return (str(v).strip() if v is not None else '')


def list_of(quota, itype):
    """Which of the four lists a seat belongs to (None = left out)."""
    q = (quota or '').lower()
    if any(k in q for k in ('in-service', 'inservice', 'in service', 'dnb', 'diploma quota')):
        return None
    if 'nri' in q or 'non-resident' in q:
        return 'nri'
    if 'management' in q:
        return 'management'
    t = (itype or '').lower()
    if t.startswith('government') or t.startswith('central') or t == 'afms':
        return 'govt'
    return 'private'


def _type_label(it):
    t = (it or '').lower()
    if 'deemed' in t:
        return 'Deemed University'
    if 'private university' in t:
        return 'Private University'
    if t.startswith('private'):
        return 'Private'
    return 'Government' if t else ''


def authorities(conn):
    """[{authority, body, name, seats}] — every state body with a current seat matrix, by name."""
    out = []
    for r in conn.execute(
            "SELECT counselling_body, COALESCE(authority_code,'') AS a, total_seats FROM pg_seat_matrix_source "
            "WHERE COALESCE(superseded,0)=0 AND COALESCE(authority_code,'') NOT IN ('', 'mcc') "
            "AND COALESCE(section,'')='state' ORDER BY counselling_body").fetchall():
        out.append({'authority': r['a'], 'body': r['counselling_body'],
                    'name': r['counselling_body'].split(' —')[0].strip(), 'seats': int(r['total_seats'] or 0)})
    return out


def _body(conn, authority):
    for a in authorities(conn):
        if a['authority'] == authority:
            return a
    return None


def _rows(conn, body):
    return [dict(r) for r in conn.execute(
        "SELECT college_code, college_name, state, institute_type, quota, category, cutoff_category, "
        "cutoff_course, cutoff_institute, seats, has_cutoff, cr_r1, cr_r2 FROM pg_seat_matrix "
        "WHERE counselling_body=? AND COALESCE(section,'')='mdms'", [body]).fetchall()]


def _clinical_fn(conn):
    from pg_admin.data import specialty_groups as sg
    ctx = sg.context(conn)
    cache = {}

    def f(course):
        if course not in cache:
            try:
                cache[course] = sg.group_source(course, ctx)[0] == 'clinical'
            except Exception:
                cache[course] = False
        return cache[course]
    return f


def _r12(r):
    for k in ('cr_r1', 'cr_r2'):
        try:
            v = int(r.get(k) or 0)
        except (TypeError, ValueError):
            v = 0
        if v > 0:
            return v
    return None


def _is_open(r):
    return _s(r.get('cutoff_category')).upper() in _OPEN


def _new_codes(rows):
    has = defaultdict(bool)
    for r in rows:
        has[r['college_code']] |= bool(_s(r.get('cutoff_institute')))
    return {c for c, h in has.items() if not h}


def _stored(conn, authority, key):
    rec.ensure_rec_tables(conn)
    return {r['college_code']: dict(r) for r in conn.execute(
        "SELECT college_code, tier, updated_by, updated_at FROM pg_college_tiers WHERE list_key=?",
        [f'st:{authority}:{key}']).fetchall()}


def _band(i, n):
    return 'Top' if i < n * 0.2 else 'Good' if i < n * 0.55 else 'Average'


def list_payload(conn, authority, body, key, rows=None, clinical=None):
    """Colleges of one state list with draft + stored tiers (the Desk tier editor shape)."""
    rows = rows if rows is not None else _rows(conn, body)
    clinical = clinical or _clinical_fn(conn)
    newc = _new_codes(rows)
    by, best = {}, defaultdict(dict)          # best[course][college] = fastest Open R1/R2 closing rank
    for r in rows:
        if list_of(r['quota'], r['institute_type']) != key:
            continue
        d = by.setdefault(r['college_code'], {
            'college_code': r['college_code'], 'college': rec._short_name(r['college_name']), 'state': r['state'],
            'institute_type': _type_label(r['institute_type']), 'seats': 0, 'hist': False})
        d['seats'] += int(r['seats'] or 0)
        if r['has_cutoff']:
            d['hist'] = True
        v = _r12(r) if (key in ('management', 'nri') or _is_open(r)) else None
        course = _s(r['cutoff_course'])
        if v and course:
            cur = best[course].get(r['college_code'])
            if cur is None or v < cur:
                best[course][r['college_code']] = v
    # course-against-course: in every course offered by 2+ colleges, each college's place (0 = filled first,
    # 1 = last); a college's score = its average place over its clinical courses (all courses if none).
    # A small college with only a few popular courses is then not mistaken for a top college.
    places = defaultdict(lambda: ([], []))
    for course, cols in best.items():
        if len(cols) < 2:
            continue
        order = sorted(cols, key=lambda c: cols[c])
        for i, c in enumerate(order):
            places[c][0 if clinical(course) else 1].append(i / (len(order) - 1))
    for d in by.values():
        clin, other = places.get(d['college_code'], ([], []))
        vals = clin or other
        d['basis_rank'] = None
        d['score'] = round(sum(vals) / len(vals), 4) if vals else None
        d['new_college'] = d['college_code'] in newc
        mins = [cols[d['college_code']] for cols in best.values() if d['college_code'] in cols]
        if mins:
            d['basis_rank'] = int(statistics.median(mins))
    known = sorted([d for d in by.values() if d['score'] is not None and not d['new_college']],
                   key=lambda d: (d['score'], d['basis_rank'] or 10 ** 9))
    draft = {d['college_code']: _band(i, len(known)) for i, d in enumerate(known)}
    stored = _stored(conn, authority, key)
    out = []
    for d in by.values():
        hist = d.pop('hist')
        st = stored.get(d['college_code']) or {}
        if d['new_college']:
            tier, src = rec.NEW_TIER, 'new'
        elif st.get('tier'):
            tier, src = st['tier'], 'team'
        else:
            tier, src = draft.get(d['college_code']) or 'Average', 'draft'
        d.update({'tier': tier, 'tier_source': src, 'draft_tier': draft.get(d['college_code']) or
                  ('' if d['new_college'] else 'Average'), 'editable': not d['new_college'],
                  'no_open_history': (not d['new_college']) and d['score'] is None and hist,
                  'updated_by': st.get('updated_by') or '',
                  'updated_at': str(st['updated_at'])[:16] if st.get('updated_at') else ''})
        out.append(d)
    idx = {'Top': 0, 'Good': 1, 'Average': 2, rec.NEW_TIER: 3}
    out.sort(key=lambda x: (idx.get(x['tier'], 2), x['score'] if x['score'] is not None else 9, x['college']))
    return out


def _speciality_lists(conn, authority, body, speciality, rows):
    """Per speciality: colleges offering it, in the order its Open seat went in last year's Round 1 (else 2)."""
    from pg_admin.routes.api_choice import _spec_core
    core = _spec_core(speciality).lower()
    want = speciality.strip().lower()
    newc = _new_codes(rows)
    lists = []
    for key, label in LISTS.items():
        by = {}
        for r in rows:
            if list_of(r['quota'], r['institute_type']) != key:
                continue
            c = _s(r['cutoff_course']).lower()
            if not c or not (c == want or (core and core in c)):
                continue
            d = by.setdefault(r['college_code'], {
                'college_code': r['college_code'], 'college': rec._short_name(r['college_name']), 'state': r['state'],
                'institute_type': _type_label(r['institute_type']), 'seats': 0, 'r1': None, 'hist': False})
            d['seats'] += int(r['seats'] or 0)
            if r['has_cutoff']:
                d['hist'] = True
                v = _r12(r) if (key in ('management', 'nri') or _is_open(r)) else None
                if v and (d['r1'] is None or v < d['r1']):
                    d['r1'] = v
        if not by:
            continue
        known = sorted([d for d in by.values() if d['r1']], key=lambda d: d['r1'])
        tiers = {t: [] for t in _TIER_ORDER}
        for i, d in enumerate(known):
            tiers[_band(i, len(known))].append(d)
        tiers['Average'].extend(sorted([d for d in by.values() if not d['r1'] and d['hist']],
                                       key=lambda d: d['college']))
        new = sorted([d for d in by.values() if not d['r1'] and not d['hist']], key=lambda d: d['college'])
        for d in list(by.values()):
            d.pop('r1', None); d.pop('hist', None)
        lists.append({'key': key, 'label': label, 'tiers': tiers, 'new': new,
                      'counts': {**{t: len(v) for t, v in tiers.items()}, 'New': len(new)}})
    return lists


def speciality_options(conn, body):
    from pg_admin.data import specialty_groups as sg
    ctx = sg.context(conn)
    out = {'clinical': [], 'non_clinical': []}
    for r in conn.execute("SELECT DISTINCT cutoff_course AS c FROM pg_seat_matrix WHERE counselling_body=? "
                          "AND COALESCE(section,'')='mdms' AND COALESCE(cutoff_course,'')<>'' ORDER BY cutoff_course",
                          [body]).fetchall():
        out['clinical' if sg.group_source(r['c'], ctx)[0] == 'clinical' else 'non_clinical'].append(r['c'])
    return out


def rankings_data(conn, authority, speciality=''):
    """Same shape as rankings.rankings_data: {authority, name, lists:[{key,label,tiers,counts}], new_colleges}."""
    from pg_admin.routes.rankings import _ist_now
    a = _body(conn, authority)
    if not a:
        return None
    rows = _rows(conn, a['body'])
    base = {'authority': authority, 'name': a['name'], 'body': a['body'],
            'generated_at': _ist_now().strftime('%d %b %Y, %I:%M %p IST')}
    if speciality:
        return {**base, 'speciality': speciality,
                'lists': _speciality_lists(conn, authority, a['body'], speciality, rows), 'new_colleges': []}
    clinical = _clinical_fn(conn)
    lists, news = [], {}
    for key, label in LISTS.items():
        cols = list_payload(conn, authority, a['body'], key, rows, clinical)
        if not cols:
            continue
        tiers = {t: [] for t in _TIER_ORDER}
        for c in cols:
            item = {k: c[k] for k in ('college', 'state', 'institute_type', 'seats', 'college_code')}
            if c['tier'] == rec.NEW_TIER:
                n = news.setdefault(c['college_code'], {**item, 'seats': 0, 'lists': [], 'seats_by_list': {}})
                n['lists'].append(label); n['seats_by_list'][label] = c['seats']; n['seats'] += c['seats']
                continue
            tiers.setdefault(c['tier'], []).append(item)
        lists.append({'key': key, 'label': label, 'tiers': tiers, 'counts': {t: len(v) for t, v in tiers.items()}})
    return {**base, 'lists': lists, 'new_colleges': sorted(news.values(), key=lambda x: x['college'])}


# ── PDFs ─────────────────────────────────────────────────────────────────────
def build_pdf(conn, authority, speciality='', only=''):
    """only = one list key (govt|private|management|nri) → just that list + its new colleges."""
    from pg_admin.choice_pdf import _t, _NAVY, _GREY
    from pg_admin.routes.rankings import _pdf_base, _table
    data = rankings_data(conn, authority, speciality)
    if not data:
        return None, None
    if only:
        label = LISTS.get(only, '')
        data['lists'] = [l for l in data['lists'] if l['key'] == only]
        news = []
        for n in data.get('new_colleges') or []:
            if label in n['lists']:
                news.append({**n, 'lists': [label], 'seats': n['seats_by_list'].get(label, 0)})
        data['new_colleges'] = news
    pdf = _pdf_base(f"{data['name']} College Rankings 2026" + (f' - {speciality}' if speciality else '')
                    + (f" - {LISTS.get(only, '')}" if only else ''),
                    'GooCampus guidance · Top · Good · Average colleges')
    pdf.footer_note = (f"GooCampus guidance from last year's {data['name']} main rounds. "
                       "A suggestion only - verify before locking your choices.")
    pdf.set_font('Helvetica', '', 8.6); pdf.set_text_color(*_GREY)
    pdf.multi_cell(0, 4.4, _t(
        f"How to read this: {data['name']} state counselling seats, in four lists - Government colleges, Private "
        "colleges, Management Quota and NRI Quota. In each list colleges are grouped by how quickly their seats were "
        f"taken in the MAIN rounds of last year's {data['name']} counselling (Round 1 / Round 2; mop-up and stray "
        "rounds ignored). It is by college only - not by speciality. Colleges new to this counselling in 2026 are "
        f"listed at the end. Prepared by the GooCampus team on {data['generated_at']}.") if not speciality else _t(
        f"How to read this: for {speciality}, colleges in each list are in the order their {speciality} seat was "
        f"taken in Round 1 of last year's {data['name']} counselling (Round 2 where it wasn't filled in Round 1; "
        "Open / General category). Top = first 20%, Good = next 35%, Average = the rest. Seats with no previous "
        f"allotment are listed as 'New in 2026'. Prepared by the GooCampus team on {data['generated_at']}."),
        new_x='LMARGIN', new_y='NEXT')
    TIER_COL = {'Top': (22, 101, 52), 'Good': (37, 99, 235), 'Average': (107, 114, 128)}
    heads, widths = ('#', 'College', 'Type', '2026 seats'), (9, 128, 34, 15)
    aligns = ('CENTER', 'LEFT', 'LEFT', 'RIGHT')

    def block(title, rows, colour):
        if not rows:
            return
        if pdf.get_y() > 250:
            pdf.add_page()
        pdf.ln(1); pdf.set_font('Helvetica', 'B', 10.5); pdf.set_text_color(*colour)
        pdf.cell(0, 6.5, _t(f'{title} ({len(rows)})'), new_x='LMARGIN', new_y='NEXT')
        _table(pdf, [[str(i), r['college'], r['institute_type'], str(r['seats'])] for i, r in enumerate(rows, 1)],
               heads, widths, aligns)

    for lst in data['lists']:
        if not any(lst['tiers'].values()) and not lst.get('new'):
            continue
        if pdf.get_y() > 240:
            pdf.add_page()
        pdf.ln(4); pdf.set_font('Helvetica', 'B', 13); pdf.set_text_color(*_NAVY)
        pdf.cell(0, 8, _t(lst['label']), new_x='LMARGIN', new_y='NEXT')
        for tier in _TIER_ORDER:
            block(f'{tier} colleges', lst['tiers'].get(tier) or [], TIER_COL[tier])
        block('New in 2026 - no previous allotment', lst.get('new') or [], (154, 52, 18))
    if data.get('new_colleges'):
        if pdf.get_y() > 230:
            pdf.add_page()
        pdf.ln(4); pdf.set_font('Helvetica', 'B', 13); pdf.set_text_color(*_NAVY)
        pdf.cell(0, 8, _t(f"New to {data['name']} counselling in 2026 ({len(data['new_colleges'])})"),
                 new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('Helvetica', '', 8.6); pdf.set_text_color(*_GREY)
        pdf.multi_cell(0, 4.4, _t('No allotment in this counselling last year, so not graded - judge each on its own '
                                  'merits (hospital, faculty, location).'), new_x='LMARGIN', new_y='NEXT')
        _table(pdf, [[str(i), r['college'], ', '.join(r['lists']), str(r['seats'])]
                     for i, r in enumerate(data['new_colleges'], 1)],
               ('#', 'College', 'Seat lists', '2026 seats'), (9, 112, 50, 15), aligns)
    import re
    slug = re.sub(r'[^A-Za-z0-9]+', '_', data['name']).strip('_')
    sp = ('_' + re.sub(r'[^A-Za-z0-9]+', '_', speciality).strip('_')[:40]) if speciality else ''
    one = ('_' + re.sub(r'[^A-Za-z0-9]+', '_', LISTS.get(only, '')).strip('_')) if only else ''
    return bytes(pdf.output()), f'GooCampus_{slug}_College_Rankings_2026{sp}{one}.pdf'


# ── Desk tier editor (combo 'st:<authority>:<list>') ─────────────────────────
def parse_combo(combo):
    p = _s(combo).split(':')
    if len(p) == 3 and p[0] == 'st' and p[2] in LISTS:
        return p[1], p[2]
    return None, None


def tiers_get(combo):
    authority, key = parse_combo(combo)
    conn = get_db()
    try:
        a = _body(conn, authority) if authority else None
        if not a:
            return jsonify({'ok': False, 'error': 'unknown list'}), 400
        cols = list_payload(conn, authority, a['body'], key)
        return jsonify({'ok': True, 'combo': combo, 'authority': authority, 'name': a['name'],
                        'label': f"{a['name']} — {LISTS[key]}", 'tiers': list(rec.TIERS),
                        'lists': [{'key': f'st:{authority}:{k}', 'label': f"{a['name']} — {v}"} for k, v in LISTS.items()],
                        'colleges': cols})
    finally:
        conn.close()


def tiers_post(actor, body):
    """{combo:'st:kea:govt', changes:[{code, tier}]} — tier '' (or 'Draft') clears the team's tier → back to the draft."""
    authority, key = parse_combo(body.get('combo'))
    changes = body.get('changes') or ([{'code': body.get('code'), 'tier': body.get('tier')}] if body.get('code') else [])
    conn = get_db()
    try:
        a = _body(conn, authority) if authority else None
        if not a:
            return jsonify({'ok': False, 'error': 'unknown list'}), 400
        rec.ensure_rec_tables(conn)
        cols = {c['college_code']: c for c in list_payload(conn, authority, a['body'], key)}
        lk, n = f'st:{authority}:{key}', 0
        for ch in changes:
            code, tier = _s(ch.get('code')), _s(ch.get('tier'))
            c = cols.get(code)
            if not c or not c['editable']:
                continue
            if tier in ('', 'Draft'):
                conn.execute("DELETE FROM pg_college_tiers WHERE list_key=? AND college_code=?", [lk, code]); n += 1
                continue
            if tier not in rec.TIERS:
                continue
            row = conn.execute("SELECT id FROM pg_college_tiers WHERE list_key=? AND college_code=?", [lk, code]).fetchone()
            if row:
                conn.execute("UPDATE pg_college_tiers SET tier=?, updated_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             [tier, actor, row['id']])
            else:
                conn.execute("INSERT INTO pg_college_tiers (list_key, college_code, college_name, tier, basis_rank, "
                             "updated_by) VALUES (?,?,?,?,?,?)", [lk, code, c['college'], tier, c['basis_rank'], actor])
            n += 1
        conn.commit()
        return jsonify({'ok': True, 'updated': n})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("state tiers_post: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()
