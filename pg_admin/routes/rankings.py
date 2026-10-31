"""GooCampus MCC College Rankings 2026 — one general list for ALL Internal + Paid doctors.

Founder 2026-10-15. By college only (not speciality, not location): for each MCC list —
All India Quota (Govt), Deemed Paid, Central Universities (DU/IP/BHU/AMU), Deemed NRI —
colleges are grouped Top / Good / Average using the SAME team-curated tiers as the Desk
(pg_college_tiers). The draft tiers come from how fast each college's seats went in the MAIN
rounds last year (Round 1, else Round 2; mop-up / stray ignored, so a good college whose few
leftover seats went late is not dragged down). Colleges new in 2026 are never tiered — they go
out as a separate "New colleges in 2026" PDF.

Rows show only college, state, institute type and 2026 seats in that list — no ranks.
Delivery: dashboard page (/api/pg/rankings, Internal + Paid + desk staff), two PDFs, and a Desk
"Email to all Internal + Paid doctors" (test-send first).
"""
import base64
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta

from flask import request, jsonify, Response
from db import get_db
from pg_admin.routes import recommended as rec

_TIER_ORDER = ('Top', 'Good', 'Average')


def _ist_now():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


_QUOTA_LABEL = {'All India': 'All India Quota', 'Self-Financed Merit Seat': 'Deemed Paid',
                'Non-Resident Indian': 'Deemed NRI', 'Muslim Minority Quota': 'Muslim Minority',
                'Jain Minority Quota': 'Jain Minority'}


def _type_label(it):
    it = (it or '').lower()
    return 'Deemed University' if 'deemed' in it else 'Central University' if it.startswith('central') \
        else 'Government' if it else ''


# ── Category picker for MCC (founder 2026-10-31) ─────────────────────────────
# Default OPEN keeps the team-curated tiers; any other category (EWS / OBC / SC / ST …) is computed live,
# course against course, from last year's MCC main-round allotments in that category (state_rankings rule).
_MCC_PREF = ('OPEN',)


def _mcc_rows(conn, key):
    meta = rec.TIER_LISTS[key]
    bodies = rec._bodies(conn, meta['section'])
    if not bodies:
        return []
    ph = ','.join(['?'] * len(bodies)); qph = ','.join(['?'] * len(meta['seat_quotas']))
    return [dict(r) for r in conn.execute(
        f"SELECT college_code, college_name, state, institute_type, quota, category, cutoff_category, cutoff_course, "
        f"cutoff_institute, seats, has_cutoff, cr_r1, cr_r2, cr_closing FROM pg_seat_matrix "
        f"WHERE counselling_body IN ({ph}) AND quota IN ({qph})", bodies + list(meta['seat_quotas'])).fetchall()]


def mcc_categories(conn, key, rows=None):
    from pg_admin.routes import state_rankings as srk
    return srk.categories_of(rows if rows is not None else _mcc_rows(conn, key), _MCC_PREF)


def _pick(cats, dflt, want):
    return want if want and want in {c['code'] for c in cats} else dflt


def _mcc_category_tiers(conn, key, cat, rows):
    """{Top:[..], Good:[..], Average:[..]} for one MCC list in a non-default category (new colleges left out —
    they're in the separate New colleges document)."""
    from pg_admin.routes import state_rankings as srk
    from collections import defaultdict as _dd
    clinical = srk._clinical_fn(conn)
    newc = rec._new_codes(conn, key)
    by, best = {}, _dd(dict)
    for r in rows:
        d = by.setdefault(r['college_code'], {
            'college_code': r['college_code'], 'college': rec._short_name(r['college_name']), 'state': r['state'],
            'institute_type': _type_label(r['institute_type']), 'seats': 0, 'hist': False})
        d['seats'] += int(r['seats'] or 0)
        if r['has_cutoff']:
            d['hist'] = True
        v = srk._r12(r) if (r.get('cutoff_category') or '') == cat else None
        course = (r.get('cutoff_course') or '').strip()
        if v and course and (best[course].get(r['college_code']) is None or v < best[course][r['college_code']]):
            best[course][r['college_code']] = v
    draft = srk.score_colleges(by, best, clinical, newc)
    tiers = {t: [] for t in _TIER_ORDER}
    for d in sorted(by.values(), key=lambda x: (x['score'] if x['score'] is not None else 9, x['college'])):
        if d['new_college']:
            continue
        tiers[draft.get(d['college_code']) or 'Average'].append(
            {k: d[k] for k in ('college', 'state', 'institute_type', 'seats', 'college_code')})
    return tiers


def _speciality_lists(conn, speciality, cats_sel=None):
    """Per-speciality view: in each list, the colleges offering THIS speciality ordered by how fast
    its seat went in last year's Round 1 (Round 2 as fallback; Open category), split Top (first 20%) /
    Good (next 35%) / Average (rest). Colleges/courses with no history → 'new' (new in 2026)."""
    from pg_admin.routes.api_choice import _spec_core
    lists = []
    for key, meta in rec.TIER_LISTS.items():
        bodies = rec._bodies(conn, meta['section'])
        if not bodies:
            continue
        cats, dflt = mcc_categories(conn, key)
        cat = _pick(cats, dflt, (cats_sel or {}).get(key))
        ph = ','.join(['?'] * len(bodies)); qph = ','.join(['?'] * len(meta['seat_quotas']))
        rows = [dict(r) for r in conn.execute(
            f"SELECT college_code, college_name, state, institute_type, category, cutoff_category, seats, has_cutoff, "
            f"cr_r1, cr_r2, cr_closing FROM pg_seat_matrix WHERE counselling_body IN ({ph}) "
            f"AND quota IN ({qph}) AND (LOWER(TRIM(cutoff_course))=LOWER(TRIM(?)) OR cutoff_course ILIKE ?)",
            bodies + list(meta['seat_quotas']) + [speciality, '%' + _spec_core(speciality) + '%']).fetchall()]
        by = {}
        for r in rows:
            d = by.setdefault(r['college_code'], {'college': rec._short_name(r['college_name']), 'state': r['state'],
                                                   'institute_type': _type_label(r['institute_type']),
                                                   'seats': 0, 'college_code': r['college_code'], 'r1': None,
                                                   'hist': False})
            d['seats'] += int(r['seats'] or 0)
            if r['has_cutoff']:
                d['hist'] = True
            # default OPEN = the 2026 Open seat's history (as before); another category = last year's rank IN it
            if r['has_cutoff'] and ((r['category'] == 'OPEN') if cat == dflt else (r.get('cutoff_category') == cat)):
                v = rec._r1(r)
                if v and (d['r1'] is None or v < d['r1']):
                    d['r1'] = v
        known = sorted([d for d in by.values() if d['r1']], key=lambda d: d['r1'])
        n = len(known)
        tiers = {t: [] for t in _TIER_ORDER}
        for i, d in enumerate(known):
            tiers['Top' if i < n * 0.2 else 'Good' if i < n * 0.55 else 'Average'].append(d)
        # had this course last year but no Open-category Round 1/2 allotment → end of Average (not 'new')
        tiers['Average'].extend(sorted([d for d in by.values() if not d['r1'] and d['hist']],
                                       key=lambda d: (d['state'], d['college'])))
        new = sorted([d for d in by.values() if not d['r1'] and not d['hist']], key=lambda d: (d['state'], d['college']))
        lists.append({'key': key, 'label': meta['label'], 'tiers': tiers, 'new': new,
                      'counts': {**{t: len(v) for t, v in tiers.items()}, 'New': len(new)},
                      'categories': cats, 'category': cat, 'default_category': dflt})
    return lists


def speciality_options(conn):
    """Specialities present in the official MCC matrices, grouped clinical / non-clinical."""
    from pg_admin.data import specialty_groups as sg
    bodies = rec._bodies(conn)
    if not bodies:
        return {'clinical': [], 'non_clinical': []}
    ph = ','.join(['?'] * len(bodies))
    courses = [r['c'] for r in conn.execute(
        f"SELECT DISTINCT cutoff_course AS c FROM pg_seat_matrix WHERE counselling_body IN ({ph}) "
        f"AND COALESCE(cutoff_course,'')<>'' ORDER BY cutoff_course", bodies).fetchall()]
    ctx = sg.context(conn)
    out = {'clinical': [], 'non_clinical': []}
    for c in courses:
        out['clinical' if sg.group_source(c, ctx)[0] == 'clinical' else 'non_clinical'].append(c)
    return out


def rankings_data(conn, speciality='', cats_sel=None):
    """{lists:[{key,label,tiers:{Top:[..],Good:[..],Average:[..]},counts}], new_colleges:[..]}
    With `speciality`: the per-speciality order (each list also gets `new` for that course)."""
    rec.ensure_rec_tables(conn)
    if speciality:
        return {'speciality': speciality, 'lists': _speciality_lists(conn, speciality, cats_sel), 'new_colleges': [],
                'generated_at': _ist_now().strftime('%d %b %Y, %I:%M %p IST')}
    lists, new_by_code = [], {}
    for key, meta in rec.TIER_LISTS.items():
        mrows = _mcc_rows(conn, key)
        cats, dflt = mcc_categories(conn, key, mrows)
        cat = _pick(cats, dflt, (cats_sel or {}).get(key))
        if cat != dflt:                      # another category: computed live, team tiers don't apply
            tiers = _mcc_category_tiers(conn, key, cat, mrows)
            lists.append({'key': key, 'label': meta['label'], 'tiers': tiers,
                          'counts': {t: len(v) for t, v in tiers.items()},
                          'categories': cats, 'category': cat, 'default_category': dflt, 'team_edited': False})
            continue
        rows = rec.tiers_payload(conn, key)
        tiers = {t: [] for t in _TIER_ORDER}
        for r in rows:
            item = {'college': r['college'], 'state': r['state'], 'institute_type': _type_label(r.get('institute_type')),
                    'seats': r['seats'], 'college_code': r['college_code']}
            if r['tier'] == rec.NEW_TIER:
                continue                     # listed in the separate New colleges document
            tiers.setdefault(r['tier'], []).append(item)
        # within a tier: keep the curated order (tiers_payload sorts by tier then basis rank)
        lists.append({'key': key, 'label': meta['label'], 'tiers': tiers,
                      'counts': {t: len(v) for t, v in tiers.items()},
                      'categories': cats, 'category': cat, 'default_category': dflt, 'team_edited': True})
    # New colleges come from EVERY official MCC seat list (incl. Deemed 'All India' + minority quotas,
    # which a brand-new deemed college may have alone), not only the 4 ranked lists.
    bodies = rec._bodies(conn)
    if bodies:
        ph = ','.join(['?'] * len(bodies))
        for r in conn.execute(
                f"SELECT college_code, MAX(college_name) AS name, MAX(state) AS state, MAX(institute_type) AS itype, "
                f"quota, SUM(seats) AS seats FROM pg_seat_matrix WHERE counselling_body IN ({ph}) "
                f"GROUP BY college_code, quota HAVING MAX(CASE WHEN COALESCE(cutoff_institute,'')<>'' THEN 1 ELSE 0 END)=0",
                bodies).fetchall():
            n = new_by_code.setdefault(r['college_code'], {
                'college': rec._short_name(r['name']), 'state': r['state'], 'institute_type': _type_label(r['itype']),
                'college_code': r['college_code'], 'lists': [], 'seats_by_list': {}})
            q = _QUOTA_LABEL.get(r['quota'], r['quota'])
            if q not in n['seats_by_list']:
                n['lists'].append(q)
            n['seats_by_list'][q] = int(r['seats'] or 0)
    news = sorted(new_by_code.values(), key=lambda x: (x['state'], x['college']))
    for n in news:
        n['seats'] = sum(n['seats_by_list'].values())
    _add_2025_notes(conn, news, bodies)
    return {'lists': lists, 'new_colleges': news, 'generated_at': _ist_now().strftime('%d %b %Y, %I:%M %p IST')}


# ── PDFs ─────────────────────────────────────────────────────────────────────
def _pdf_base(title, subtitle, detail=''):
    """Branded A4 header: logo left; title, optional detail line (speciality · list · category) and subtitle
    right-aligned and WRAPPED inside x 60-198, so a long line never runs over the logo or off the page."""
    from pg_admin.choice_pdf import _PDF, _LOGO, _NAVY, _ORANGE, _t
    import os
    pdf = _PDF(orientation='P', unit='mm', format='A4')
    pdf.set_margins(12, 12, 12)
    pdf.set_auto_page_break(True, margin=16)
    pdf.alias_nb_pages()
    pdf.footer_note = ('GooCampus guidance based on last year\'s MCC main-round allotments. A suggestion only - '
                       'please verify before locking your choices.')
    pdf.add_page()
    try:
        if os.path.exists(_LOGO):
            pdf.image(_LOGO, x=12, y=10, h=12)
    except Exception:
        pass
    pdf.set_xy(60, 10)
    pdf.set_font('Helvetica', 'B', 15); pdf.set_text_color(*_NAVY)
    pdf.multi_cell(138, 7, _t(title), align='R', new_x='LMARGIN', new_y='NEXT')
    if detail:
        pdf.set_x(60); pdf.set_font('Helvetica', 'B', 10.5); pdf.set_text_color(*_NAVY)
        pdf.multi_cell(138, 5.5, _t(detail), align='R', new_x='LMARGIN', new_y='NEXT')
    pdf.set_x(60); pdf.set_font('Helvetica', 'B', 10); pdf.set_text_color(*_ORANGE)
    pdf.multi_cell(138, 6, _t(subtitle), align='R', new_x='LMARGIN', new_y='NEXT')
    pdf.set_y(max(pdf.get_y(), 23))            # below the logo (y 10-22)
    pdf.ln(4); pdf.set_draw_color(*_ORANGE); pdf.set_line_width(0.6)
    pdf.line(12, pdf.get_y(), 198, pdf.get_y()); pdf.ln(3)
    return pdf


def _table(pdf, rows, heads, widths, aligns):
    from pg_admin.choice_pdf import _t, _head_style
    pdf.set_font('Helvetica', '', 8.6)
    pdf.set_draw_color(220, 224, 230); pdf.set_line_width(0.2)
    with pdf.table(col_widths=widths, text_align=aligns, line_height=4.8, headings_style=_head_style(),
                   first_row_as_headings=True, repeat_headings=1) as t:
        hr = t.row()
        for h in heads:
            hr.cell(h)
        for r in rows:
            row = t.row()
            for v in r:
                row.cell(_t(v))


def build_rankings_pdf(conn, speciality='', only='', plain=False, category=''):
    """only = one list key (aiq_open | deemed_paid_open | ciq_open | nri_deemed) → just that list.
    plain = one continuous numbered list per list (same order: Top, Good, Average), no tier headings."""
    from pg_admin.choice_pdf import _t, _NAVY, _GREY
    data = rankings_data(conn, speciality, {only: category} if (only and category) else None)
    used = ''
    if only:
        data['lists'] = [l for l in data['lists'] if l['key'] == only]
        used = next((l.get('category') or '' for l in data['lists']), '')   # named in title + filename (as states)
    detail = ' · '.join(x for x in (speciality, rec.TIER_LISTS[only]['label'] if only else '',
                                    f'{used} category' if used else '') if x)
    pdf = _pdf_base('MCC College Rankings 2026',
                    'GooCampus guidance · ' + ('colleges in recommended order' if plain else 'Top · Good · Average colleges'),
                    detail)
    pdf.set_font('Helvetica', '', 8.6); pdf.set_text_color(*_GREY)
    intro = (
        'How to read this: colleges are grouped by how quickly their seats were taken in the MAIN rounds of last '
        "year's MCC counselling (Round 1 / Round 2; mop-up and stray rounds are ignored). It is by college only - "
        'not by speciality or location. Each list uses last year\'s allotments in the category shown beside it. '
        'Colleges that are new in 2026 are listed in a separate document. '
        f"Prepared by the GooCampus team on {data['generated_at']}.") if not speciality else (
        f"How to read this: for {speciality}, colleges in each list are in the order their {speciality} seat was "
        "taken in Round 1 of last year's MCC counselling (Round 2 where it wasn't filled in Round 1), in the category "
        "shown beside each list. "
        "Top = first 20%, Good = next 35%, Average = the rest. Seats with no previous allotment are listed as "
        f"'New in 2026' at the end of each list. Prepared by the GooCampus team on {data['generated_at']}.")
    if plain:   # plain list: no tier wording in the intro
        intro = intro.replace('colleges are grouped by how quickly', 'colleges are listed in the order of how quickly') \
                     .replace('Top = first 20%, Good = next 35%, Average = the rest. ', '')
    pdf.multi_cell(0, 4.4, _t(intro), new_x='LMARGIN', new_y='NEXT')
    TIER_COL = {'Top': (22, 101, 52), 'Good': (37, 99, 235), 'Average': (107, 114, 128)}
    for lst in data['lists']:
        if not any(lst['tiers'].values()) and not lst.get('new'):
            continue
        if pdf.get_y() > 240:
            pdf.add_page()
        pdf.ln(4); pdf.set_font('Helvetica', 'B', 13); pdf.set_text_color(*_NAVY)
        pdf.multi_cell(0, 7, _t(lst['label'] + (f" · {lst['category']} category" if lst.get('category') else '')),
                       new_x='LMARGIN', new_y='NEXT')
        groups = ([('', [r for t in _TIER_ORDER for r in (lst['tiers'].get(t) or [])])] if plain
                  else [(t, lst['tiers'].get(t) or []) for t in _TIER_ORDER])
        for tier, rows in groups:
            if not rows:
                continue
            if pdf.get_y() > 250:
                pdf.add_page()
            if tier:
                pdf.ln(1); pdf.set_font('Helvetica', 'B', 10.5); pdf.set_text_color(*TIER_COL[tier])
                pdf.cell(0, 6.5, f'{tier} colleges ({len(rows)})', new_x='LMARGIN', new_y='NEXT')
            _table(pdf, [[str(i), r['college'], r['state'], r['institute_type'], str(r['seats'])]
                         for i, r in enumerate(rows, start=1)],
                   ('#', 'College', 'State', 'Type', 'Seats'), (9, 102, 34, 26, 15),
                   ('CENTER', 'LEFT', 'LEFT', 'LEFT', 'RIGHT'))
        if lst.get('new'):
            if pdf.get_y() > 250:
                pdf.add_page()
            pdf.ln(1); pdf.set_font('Helvetica', 'B', 10.5); pdf.set_text_color(154, 52, 18)
            pdf.cell(0, 6.5, f"New in 2026 ({len(lst['new'])}) - no previous allotment", new_x='LMARGIN', new_y='NEXT')
            _table(pdf, [[str(i), r['college'], r['state'], r['institute_type'], str(r['seats'])]
                         for i, r in enumerate(lst['new'], start=1)],
                   ('#', 'College', 'State', 'Type', 'Seats'), (9, 102, 34, 26, 15),
                   ('CENTER', 'LEFT', 'LEFT', 'LEFT', 'RIGHT'))
    import re
    slug = re.sub(r'[^A-Za-z0-9]+', '_', speciality).strip('_')[:40] if speciality else ''
    one = re.sub(r'[^A-Za-z0-9]+', '_', rec.TIER_LISTS[only]['label']).strip('_') if only else ''
    return bytes(pdf.output()), 'GooCampus_MCC_College_Rankings_2026' + ''.join(
        '_' + x for x in (slug, one, re.sub(r'[^A-Za-z0-9]+', '_', used).strip('_'), 'List' if plain else '') if x) + '.pdf'


NOTE_MATCH_MIN = 0.6
_GENERIC = {'government', 'govt', 'medical', 'college', 'colleges', 'hospital', 'hospitals', 'institute', 'institutes',
            'sciences', 'science', 'research', 'centre', 'center', 'and', 'of', 'the', 'gmc', 'mch', 'health',
            'university', 'faculty', 'district', 'state', 'post', 'graduate', 'pg', 'education', 'general',
            'j', 'k', 'jk', 'south', 'north', 'east', 'west', 'road', 'india'}


def _distinct(name, state=''):
    """The words that tell one college from another (place / founder names), minus generic and state words."""
    from pg_admin import name_memory as NM
    return set(NM.norm(name).split()) - _GENERIC - set(NM.norm(state).split()) - {t for t in NM.norm(name).split() if t.isdigit()}


def _add_2025_notes(conn, news, bodies):
    """note per new-to-MCC college: 'In 2025: Tamil Nadu state counselling' when another authority had it in
    2025, else 'New college' (founder 2026-10-27, option B). Matched by name through the name memory, and only
    trusted when that 2025 college is in the same state — otherwise no note rather than a wrong one."""
    if not news:
        return
    try:
        from pg_admin import name_memory as NM
        from pg_admin.routes.results_api import _was_in_note
        ph = ','.join(['?'] * len(bodies))
        full = {r['college_code']: r['name'] for r in conn.execute(
            f"SELECT college_code, MAX(college_name) AS name FROM pg_seat_matrix WHERE counselling_body IN ({ph}) "
            f"AND college_code = ANY(?) GROUP BY college_code", bodies + [[n['college_code'] for n in news]]).fetchall()}
        hits = NM.resolve(conn, 'college', list(full.values()), learn=False)
        known = defaultdict(lambda: (set(), set()))       # 2025 institute → (authorities, states)
        for c in conn.execute("SELECT DISTINCT institute, authority, state FROM pg_cutoffs "
                              "WHERE year=2025 AND COALESCE(institute,'')<>''").fetchall():
            known[c['institute']][0].add(c['authority'] or '')
            known[c['institute']][1].add((c['state'] or '').strip().lower())
        by_state = defaultdict(list)
        for inst, (_a, sts) in known.items():
            for st in sts:
                by_state[st].append(inst)
        for n in news:
            std = (hits.get(full.get(n['college_code']) or '') or {}).get('std') or ''
            if not std and full.get(n['college_code']):
                # not in the name memory: closest 2025 college IN THE SAME STATE (the note only names the
                # counselling, so a near-namesake in that state still gives the right answer)
                st_l = (n['state'] or '').strip().lower()
                own = _distinct(full[n['college_code']], st_l)
                cands = NM._Index(by_state.get(st_l, [])).best(full[n['college_code']], 3)
                # must share a distinctive word (Karpaga, Srinivasan…) — "Government Medical College" alone
                # would tie a brand-new GMC to an old one in the same state
                cands = [c for c in cands if c[0] >= NOTE_MATCH_MIN and own & _distinct(c[1], st_l)]
                if cands:
                    std = cands[0][1]
            auths, states = known[std] if std in known else (set(), set())
            if not std:
                n['note'] = ''                     # name not recognised — say nothing rather than guess
            elif std not in known:
                n['note'] = 'New college'          # a College Database college with no 2025 cut-off anywhere
            elif (n['state'] or '').strip().lower() in states:
                n['note'] = _was_in_note(auths - {'MCC (All India)'})
            else:
                n['note'] = ''
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.warning("rankings 2025 notes: %s", e)


def build_new_colleges_pdf(conn):
    from pg_admin.choice_pdf import _t, _GREY
    data = rankings_data(conn)
    pdf = _pdf_base('New in 2026', 'MCC PG counselling · colleges with no MCC allotment in 2025')
    pdf.set_font('Helvetica', '', 8.8); pdf.set_text_color(*_GREY)
    pdf.multi_cell(0, 4.6, _t(
        "These colleges are in MCC's 2026 seat matrix but had no MCC allotment in 2025, so there is no MCC rank "
        "from last year to judge them by. Some are new colleges; others were in their state's counselling in "
        "2025 (see 'In 2025'). We have not graded them - look at each one on its own merits (hospital, "
        'faculty, location) before adding it to your choices.'), new_x='LMARGIN', new_y='NEXT')
    pdf.ln(3)
    rows = data['new_colleges']
    if rows:
        _table(pdf, [[str(i), r['college'], r['state'], r['institute_type'], ', '.join(r['lists']),
                      (r.get('note') or '').replace('In 2025: ', ''), str(r['seats'])]
                     for i, r in enumerate(rows, start=1)],
               ('#', 'College', 'State', 'Type', 'Seat lists', 'In 2025', 'Seats'), (8, 52, 22, 24, 34, 32, 14),
               ('CENTER', 'LEFT', 'LEFT', 'LEFT', 'LEFT', 'LEFT', 'RIGHT'))
    else:
        pdf.set_font('Helvetica', 'I', 10)
        pdf.cell(0, 8, 'Every college in this year\'s MCC seat matrix had an MCC allotment in 2025.', new_x='LMARGIN', new_y='NEXT')
    return bytes(pdf.output()), 'GooCampus_New_Colleges_2026.pdf'


def _pdf_resp(kind):
    conn = get_db()
    try:
        sp = (request.args.get('speciality') or '').strip()
        auth = (request.args.get('authority') or 'mcc').strip().lower()
        only = (request.args.get('list') or '').strip()      # one list only (founder 2026-10-31); '' = all lists
        plain = (request.args.get('style') or '').strip().lower() == 'plain'   # no Top/Good/Average headings
        cat = (request.args.get('category') or '').strip()   # with list=: that list's category (unknown → default)
        if auth != 'mcc':                    # a state's PDF carries its own "New in 2026" section
            from pg_admin.routes import state_rankings as srk
            if only and only not in srk.LISTS:
                return jsonify({'ok': False, 'error': 'unknown_list', 'allowed': list(srk.LISTS)}), 400
            pdf, fn = srk.build_pdf(conn, auth, sp, only, plain, cat)
            if not pdf:
                return jsonify({'ok': False, 'error': 'unknown_authority'}), 404
        else:
            if only and only not in rec.TIER_LISTS:
                return jsonify({'ok': False, 'error': 'unknown_list', 'allowed': list(rec.TIER_LISTS)}), 400
            pdf, fn = build_new_colleges_pdf(conn) if kind == 'new' else build_rankings_pdf(conn, sp, only, plain, cat)
        return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': f'attachment; filename="{fn}"'})
    finally:
        conn.close()


# ── Access ───────────────────────────────────────────────────────────────────
def _doctor_or_desk():
    """Internal / Paid doctor (choice-list plan) or a Desk team member. → (ok, err_response)."""
    from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token
    from pg_admin.routes.api_choice import _plan_has
    if not _authorized():
        return False, (jsonify({'ok': False, 'error': 'unauthorized'}), 401)
    conn = get_db()
    try:
        tok = _bearer_token()
        u = _pg_user_by_token(conn, tok) if tok else None
        if not u:
            return False, (jsonify({'ok': False, 'error': 'no_token'}), 401)
        u = dict(u)
        if int(u.get('desk_access') or 0) == 1 and int(u.get('is_team_member') or 0) == 1:
            return True, None
        if _plan_has(conn, u['id'], 'dash_choice_list'):
            return True, None
        return False, (jsonify({'ok': False, 'error': 'not_entitled',
                                'message': 'The GooCampus College Rankings are for Internal and paid doctors.'}), 403)
    finally:
        conn.close()


def api_rankings():
    """GET /api/pg/rankings[?authority=mcc|<state code>&speciality=&list=<key>&category=<code>] → the rankings for
    the dashboard page (Internal / Paid / desk). `authorities` lists the tabs (MCC + every state with a 2026 seat
    matrix). Every list carries `categories` (default first), `category` (in use), `default_category`,
    `team_edited`; list+category recompute that one list in that category, the others stay on their default."""
    ok, err = _doctor_or_desk()
    if not ok:
        return err
    conn = get_db()
    try:
        from pg_admin.routes import state_rankings as srk
        sp = (request.args.get('speciality') or '').strip()
        auth = (request.args.get('authority') or 'mcc').strip().lower()
        lk, ck = (request.args.get('list') or '').strip(), (request.args.get('category') or '').strip()
        sel = {lk: ck} if (lk and ck) else None   # recompute that one list in that category (founder 2026-10-31)
        # tabs: MCC first, then every state with a 2026 seat matrix (founder 2026-10-31)
        tabs = [{'authority': 'mcc', 'name': 'MCC (All India)'}] + [
            {'authority': a['authority'], 'name': a['name'], 'source': a.get('source') or 'matrix'}
            for a in srk.authorities(conn)]
        if auth != 'mcc':
            d = srk.rankings_data(conn, auth, sp, sel)
            if not d:
                return jsonify({'ok': False, 'error': 'unknown_authority', 'authorities': tabs}), 404
            return jsonify({'ok': True, **d, 'authorities': tabs,
                            'specialities': srk.speciality_options(conn, d['body'])})
        return jsonify({'ok': True, 'authority': 'mcc', 'name': 'MCC (All India)', **rankings_data(conn, sp, sel),
                        'authorities': tabs, 'specialities': speciality_options(conn)})
    except Exception as e:
        logging.error("api_rankings: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_rankings_pdf():
    """GET /api/pg/rankings/pdf?kind=rankings|new[&authority=<state code>&speciality=&list=<one list key>&category=<code>&style=plain]"""
    ok, err = _doctor_or_desk()
    if not ok:
        return err
    return _pdf_resp('new' if (request.args.get('kind') or '') == 'new' else 'rankings')


def admin_rankings_pdf():
    from core.users import get_user
    u = get_user()
    if not (u and u.get('is_admin')):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    return _pdf_resp('new' if (request.args.get('kind') or '') == 'new' else 'rankings')


# ── Email to all Internal + Paid doctors ─────────────────────────────────────
def _ensure_log(conn):
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_rankings_email_log (
            id SERIAL PRIMARY KEY,
            kind TEXT DEFAULT 'all',          -- all | test
            requested_by TEXT DEFAULT '',
            recipients INTEGER DEFAULT 0,
            sent INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'queued',     -- queued | sending | done
            test_to TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP
        )''')
        conn.commit()
    except Exception:
        try: conn.rollback()
        except Exception: pass


def _recipients(conn):
    """Internal + Paid doctors with an email (desk categorisation), de-duplicated."""
    from pg_admin.routes.desk_api import _type_sql
    rows = conn.execute(
        f"SELECT x.name, LOWER(TRIM(x.email)) AS email FROM (SELECT u.name, u.email, {_type_sql('u')} AS t "
        f"FROM pg_users u WHERE COALESCE(u.is_blocked,0)=0) x WHERE x.t IN ('internal','paid') "
        f"AND COALESCE(x.email,'') <> '' AND strpos(x.email, '@') > 0").fetchall()
    seen, out = set(), []
    for r in rows:
        if r['email'] in seen:
            continue
        seen.add(r['email']); out.append({'email': r['email'], 'name': r['name'] or ''})
    return out


def _email_html(name, sender):
    from email_utils import render_branded_email
    from html import escape
    n = (name or '').strip()
    dr = n if n.lower().startswith('dr') else ('Dr. ' + n if n else 'Doctor')
    inner = (f"<p style='margin:0 0 14px;font-size:15px;color:#0F1B33;'>Dear {escape(dr)},</p>"
             "<p style='margin:0 0 14px;font-size:14px;color:#374151;line-height:1.6;'>Please find attached the "
             "<b>GooCampus MCC College Rankings 2026</b> — the All India Quota, Deemed (Paid and NRI) and Central "
             "University colleges grouped as <b>Top, Good and Average</b>, based on how quickly their seats were "
             "taken in last year's main counselling rounds. A second document lists the <b>colleges that are new "
             "in 2026</b>, which have no previous allotment to grade them by.</p>"
             "<p style='margin:0 0 14px;font-size:14px;color:#374151;line-height:1.6;'>Use this alongside your "
             "personalised choice list on <a href='https://goocampus.in/dashboard' style='color:#EA6C1E;'>"
             "goocampus.in</a>. Your counsellor is happy to talk it through.</p>"
             "<p style='margin:0 0 16px;font-size:12px;color:#6b7280;line-height:1.55;border-left:3px solid #fdba74;"
             "padding:6px 10px;background:#fff7ed;'>This is GooCampus guidance based on last year's allotments — a "
             "suggestion only. Please verify every choice before you lock it; the final decision is yours.</p>"
             f"<p style='margin:0;font-size:14px;color:#374151;'>Warm regards,<br>{escape(sender)}<br>Team GooCampus</p>")
    return render_branded_email('MCC College Rankings 2026', inner,
                                preheader='Top, Good and Average MCC colleges + new colleges in 2026')


def _send_all(log_id, sender, test_to=''):
    from email_utils import send_email
    conn = get_db()
    try:
        a, fa = build_rankings_pdf(conn)
        b, fb = build_new_colleges_pdf(conn)
        recips = [{'email': test_to, 'name': ''}] if test_to else _recipients(conn)
        conn.execute("UPDATE pg_rankings_email_log SET status='sending', recipients=? WHERE id=?", [len(recips), log_id])
        conn.commit()
    except Exception as e:
        logging.error("rankings email prepare: %s", e)
        try: conn.rollback()
        except Exception: pass
        conn.close()
        return
    atts = [{'filename': fa, 'content': base64.b64encode(a).decode('ascii')},
            {'filename': fb, 'content': base64.b64encode(b).decode('ascii')}]
    sent = failed = 0
    from pg_admin import email_tracking as ET
    subj = 'GooCampus MCC College Rankings 2026 — Top, Good & Average colleges'
    for r in recips:
        try:
            html, tok = _email_html(r['name'], sender), None
            if not test_to:      # a test send is not a campaign
                html, tok = ET.wrap(conn, html, kind='rankings', email=r['email'], subject=subj,
                                    ref_id=log_id, ref_label='MCC College Rankings 2026')
            ok = send_email([r['email']], subj, html, from_address='GooCampus <info@goocampus.in>',
                            attachments=atts)
            ET.mark_sent(conn, tok, ok)
            sent += 1 if ok else 0
            failed += 0 if ok else 1
        except Exception as e:
            failed += 1
            logging.error("rankings email to %s: %s", r['email'], e)
        time.sleep(0.4)            # Resend: 2 req/sec
    try:
        conn.execute("UPDATE pg_rankings_email_log SET status='done', sent=?, failed=?, finished_at=CURRENT_TIMESTAMP "
                     "WHERE id=?", [sent, failed, log_id])
        conn.commit()
    finally:
        conn.close()


def desk_rankings_email():
    """GET → recent sends + recipient count.  POST {test_to?} → test to one address, else to ALL
    Internal + Paid doctors (background, throttled)."""
    from pg_admin.routes.desk_api import _guard, _actor_name
    import re
    m, _, err = _guard()
    if err:
        return err
    conn = get_db()
    try:
        _ensure_log(conn)
        if request.method == 'GET':
            log = [dict(r) for r in conn.execute(
                "SELECT kind, requested_by, recipients, sent, failed, status, test_to, created_at, finished_at "
                "FROM pg_rankings_email_log ORDER BY id DESC LIMIT 20").fetchall()]
            for r in log:
                for k in ('created_at', 'finished_at'):
                    r[k] = str(r[k])[:19] if r.get(k) else ''
            return jsonify({'ok': True, 'recipients': len(_recipients(conn)), 'log': log})
        body = request.get_json(silent=True) or {}
        test_to = (body.get('test_to') or '').strip()
        if test_to and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', test_to):
            return jsonify({'ok': False, 'error': 'bad_email'}), 400
        if not test_to and not body.get('confirm'):
            return jsonify({'ok': False, 'error': 'confirm_required',
                            'message': 'Send {confirm:true} to email every Internal + Paid doctor.'}), 400
        who = _actor_name(m)
        lid = conn.execute("INSERT INTO pg_rankings_email_log (kind, requested_by, test_to) VALUES (?,?,?) RETURNING id",
                           ['test' if test_to else 'all', who, test_to]).fetchone()['id']
        n = 1 if test_to else len(_recipients(conn))
        conn.commit()
    finally:
        conn.close()
    threading.Thread(target=_send_all, args=(lid, who, test_to), daemon=True).start()
    return jsonify({'ok': True, 'queued': n, 'log_id': lid, 'test': bool(test_to)})
