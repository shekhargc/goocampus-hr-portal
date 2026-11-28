"""College Rankings 2026 lists built with pg_admin.data.rank_engine (founder 2026-11-28).

Same payload shape the website already reads ({key, label, tiers{Top,Good,Average}, counts, categories, category,
default_category, team_edited, new}), every college item now also carries closing_2025 / closing_2026 (the page's
last column), new_in_2026 and score. MCC and every state use one rule set — see rank_engine's docstring.
"""
import re

from pg_admin.data import rank_engine as E
from pg_admin.routes import recommended as rec

_TIERS = ('Top', 'Good', 'Average')


def _spec_fn(speciality):
    if not speciality:
        return None
    from pg_admin.routes.api_choice import _spec_core
    core, want = _spec_core(speciality).lower(), speciality.strip().lower()
    return lambda c: bool(c) and (c.lower() == want or (core and core in c.lower()))


def _item(d, tier):
    return {'college': d['college'], 'state': d['state'], 'institute_type': d['institute_type'], 'seats': d['seats'],
            'college_code': d['college_code'], 'courses': d.get('courses'), 'course_names': d.get('course_names'),
            'closing_2025': d['closing_2025'], 'closing_2026': d['closing_2026'],
            'new_in_2026': bool(d['new_college']), 'score': d['score'], 'tier_source': tier[1]}


def _assemble(by, draft, team, follow=None, min_courses=0):
    """→ (tiers{Top,Good,Average: [items]}, new[items], specialist[items]) — team tier wins, then (NRI) the
    Deemed Paid tier it follows, then the computed one; colleges with fewer than `min_courses` MD/MS courses
    (speciality institutes, colleges just starting) go to `specialist`, ordered by fill speed; colleges with no
    Round 1–2 rank in either year: history → Average end, none → 'new'."""
    tiers, new, specialist = {t: [] for t in _TIERS}, [], []
    for d in sorted(by.values(), key=lambda x: (x['score'] if x['score'] is not None else 9,
                                               x['closing_2026'] or x['closing_2025'] or 10 ** 9, x['college'])):
        code = d['college_code']
        if team.get(code) in _TIERS:
            t = (team[code], 'team')
        elif min_courses and (d.get('courses') or 0) < min_courses and d['score'] is not None:
            specialist.append(_item(d, ('Speciality institute', 'fewer than %d courses' % min_courses)))
            continue
        elif follow and follow.get(code) in _TIERS:
            t = (follow[code], 'follows deemed paid')
        elif code in draft:
            t = (draft[code], 'computed')
        elif min_courses and d['score'] is not None and not d.get('has_clinical'):
            t = ('Average', 'no clinical seat in this category yet')
        elif d['hist']:
            t = ('Average', 'no Round 1-2 seat in this category')
        else:
            new.append(_item(d, ('New', 'new')))
            continue
        tiers[t[0]].append(_item(d, t))
    return tiers, new, specialist


def _mcc_team(conn, key):
    """Tiers a team member set on the Desk (machine drafts 'Draft…' / 'import' are not team decisions)."""
    rec.ensure_rec_tables(conn)
    return {r['college_code']: r['tier'] for r in conn.execute(
        "SELECT college_code, tier FROM pg_college_tiers WHERE list_key=? AND COALESCE(updated_by,'') NOT ILIKE ? "
        "AND COALESCE(updated_by,'') NOT IN ('', 'import')", [key, 'Draft%']).fetchall()}


def mcc_lists(conn, speciality='', cats_sel=None):
    from pg_admin.routes import rankings as rk
    from pg_admin.routes import state_rankings as srk
    ck = E.college_key_fn(conn)
    c26 = E.closings_2026(conn, 'mcc', lambda q, t: E.MCC_QUOTA_LIST.get((q or '').strip()), ck)
    clinical = srk._clinical_fn(conn)
    spec = _spec_fn(speciality)
    lists, final = [], {}
    for key, meta in rec.TIER_LISTS.items():
        rows = rk._mcc_rows(conn, key)
        if not rows:
            continue
        cats, dflt = srk.categories_of(rows, rk._MCC_PREF)
        cat = rk._pick(cats, dflt, (cats_sel or {}).get(key))
        by, _, _ = E.rank_list(
            conn, key=key, rows=rows, row_in_list=lambda r: True,
            cat_ok25=lambda r, c=cat: (r.get('cutoff_category') or '') == c, c26=c26, cats26={cat},
            clinical=clinical, ck=ck, short_name=rec._short_name, type_label=rk._type_label,
            speciality=speciality or None, spec_match=spec)
        if not by:
            continue
        mc = 0 if speciality else E.MIN_COURSES
        draft = E.tiers_for(by, mc)
        use_team = cat == dflt and not speciality
        team = _mcc_team(conn, key) if use_team else {}
        follow = final.get('deemed_paid_open') if key == 'nri_deemed' and use_team else None
        tiers, new, specialist = _assemble(by, draft, team, follow, mc)
        final[key] = {i['college_code']: t for t, items in tiers.items() for i in items}
        lists.append({'key': key, 'label': meta['label'], 'tiers': tiers, 'new': new, 'specialist': specialist,
                      'specialist_label': 'Speciality institutes & colleges with 1–2 MD/MS courses (by fill speed)',
                      'counts': {**{t: len(v) for t, v in tiers.items()}, 'New': len(new), 'Specialist': len(specialist)},
                      'categories': cats, 'category': cat, 'default_category': dflt, 'team_edited': use_team})
    return lists


def state_lists(conn, authority, rows, speciality='', cats_sel=None):
    from pg_admin.routes import state_rankings as srk
    ck = E.college_key_fn(conn)
    c26 = E.closings_2026(conn, authority, srk.list_of, ck)
    clinical = srk._clinical_fn(conn)
    spec = _spec_fn(speciality)
    lists = []
    for key, label in srk.LISTS.items():
        cats, dflt = srk.list_categories(rows, key)
        want = (cats_sel or {}).get(key)
        cat = want if want and want in {c['code'] for c in cats} else dflt
        by, _, _ = E.rank_list(
            conn, key=key, rows=rows, row_in_list=lambda r, k=key: srk.list_of(r['quota'], r['institute_type']) == k,
            cat_ok25=lambda r, k=key, c=cat: srk._cat_ok(r, k, c), c26=c26, cats26={cat} if cat else None,
            clinical=clinical, ck=ck, short_name=rec._short_name, type_label=srk._type_label,
            speciality=speciality or None, spec_match=spec)
        if not by:
            continue
        mc = 0 if speciality else E.MIN_COURSES
        draft = E.tiers_for(by, mc)
        use_team = cat == dflt and not speciality
        team = {c: s.get('tier') for c, s in srk._stored(conn, authority, key).items()} if use_team else {}
        tiers, new, specialist = _assemble(by, draft, team, None, mc)
        lists.append({'key': key, 'label': label, 'tiers': tiers, 'new': new, 'specialist': specialist,
                      'specialist_label': 'Speciality institutes & colleges with 1–2 MD/MS courses (by fill speed)',
                      'counts': {**{t: len(v) for t, v in tiers.items()}, 'New': len(new), 'Specialist': len(specialist)},
                      'categories': cats, 'category': cat, 'default_category': dflt, 'team_edited': use_team})
    return lists


def method_note(conn, authority):
    n = E.rounds_done(conn, authority)
    yr26 = ('2026 Rounds 1 and 2' if n >= 2 else '2026 Round 1' if n == 1 else 'no 2026 round yet')
    return (f"Order = how fast each college's seats went to top rankers: 2025 Rounds 1–2 and {yr26}, counted "
            "equally, course against course. Top = first 30 %, Good = next 35 %, Average = last 35 % of colleges with "
            "3+ MD/MS courses; institutes with 1–2 courses are listed separately by fill speed. "
            "Closing rank = the highest rank that got a seat by the end of Round 2 (typical over the college's "
            "clinical courses; in a speciality view, that course).")


# ── Excel: 2025 vs 2026 closing-rank order, side by side (founder 2026-11-28) ─────────────────────────────
def _list_inputs(conn, authority, key, cats_sel):
    """(rows, row_in_list, cat, cat_ok25, cats26, c26, label, clinical, ck, type_label) for one list."""
    from pg_admin.routes import rankings as rk
    from pg_admin.routes import state_rankings as srk
    ck = E.college_key_fn(conn)
    clinical = srk._clinical_fn(conn)
    if authority == 'mcc':
        meta = rec.TIER_LISTS.get(key)
        if not meta:
            return None
        rows = rk._mcc_rows(conn, key)
        cats, dflt = srk.categories_of(rows, rk._MCC_PREF)
        cat = rk._pick(cats, dflt, cats_sel)
        c26 = E.closings_2026(conn, 'mcc', lambda q, t: E.MCC_QUOTA_LIST.get((q or '').strip()), ck)
        return dict(rows=rows, row_in_list=lambda r: True, cat=cat, cat_ok25=lambda r: (r.get('cutoff_category') or '') == cat,
                    cats26={cat}, c26=c26, label=meta['label'], clinical=clinical, ck=ck, type_label=rk._type_label,
                    name='MCC (All India)')
    a = srk._body(conn, authority)
    if not a or key not in srk.LISTS:
        return None
    rows = srk._rows(conn, a['body'])
    cats, dflt = srk.list_categories(rows, key)
    cat = cats_sel if cats_sel and cats_sel in {c['code'] for c in cats} else dflt
    c26 = E.closings_2026(conn, authority, srk.list_of, ck)
    return dict(rows=rows, row_in_list=lambda r: srk.list_of(r['quota'], r['institute_type']) == key, cat=cat,
                cat_ok25=lambda r: srk._cat_ok(r, key, cat), cats26={cat} if cat else None, c26=c26,
                label=srk.LISTS[key], clinical=clinical, ck=ck, type_label=srk._type_label, name=a['name'])


def build_xlsx(conn, authority, key, category='', speciality=''):
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    p = _list_inputs(conn, authority, key, category)
    if not p:
        return None, None
    spec = _spec_fn(speciality)
    by, b25, b26 = E.rank_list(conn, key=key, rows=p['rows'], row_in_list=p['row_in_list'], cat_ok25=p['cat_ok25'],
                               c26=p['c26'], cats26=p['cats26'], clinical=p['clinical'], ck=p['ck'],
                               short_name=rec._short_name, type_label=p['type_label'],
                               speciality=speciality or None, spec_match=spec)
    courses = sorted(set(b25) | set(b26), key=lambda c: (not p['clinical'](c), c))
    n26 = E.rounds_done(conn, authority)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    head_fill, used = PatternFill('solid', fgColor='1F3A5F'), set()
    for course in courses:
        a25 = sorted(b25.get(course, {}).items(), key=lambda kv: kv[1])
        a26 = sorted(b26.get(course, {}).items(), key=lambda kv: kv[1])
        if not a25 and not a26:
            continue
        title = re.sub(r'[\[\]\*\?/\\:]', '', course)[:28] or 'Course'
        t, i = title, 2
        while t in used:
            t = f'{title[:25]} {i}'; i += 1
        used.add(t)
        ws = wb.create_sheet(t)
        ws.append([f"{course} — {p['name']} · {p['label']} · category {p['cat'] or 'all'}"])
        ws['A1'].font = Font(bold=True, size=12)
        ws.append([f"Closing rank = highest rank that got a seat by the end of Round 2. 2025: Rounds 1–2. "
                   f"2026: {'Rounds 1–2' if n26 >= 2 else 'Round 1' if n26 == 1 else 'no round yet'}."])
        ws.append([])
        ws.append(['S.No', 'College (2025)', 'Closing rank 2025', '', 'S.No', 'College (2026)', 'Closing rank 2026'])
        for c in ws[4]:
            if c.value:
                c.font = Font(bold=True, color='FFFFFF'); c.fill = head_fill
        for n in range(max(len(a25), len(a26))):
            row = [None] * 7
            if n < len(a25):
                row[0:3] = [n + 1, by[a25[n][0]]['college'], a25[n][1]]
            if n < len(a26):
                row[4:7] = [n + 1, by[a26[n][0]]['college'], a26[n][1]]
            ws.append(row)
        for col, w in zip('ABCDEFG', (6, 52, 16, 3, 6, 52, 16)):
            ws.column_dimensions[col].width = w
        ws.freeze_panes = 'A5'
    if not wb.sheetnames:
        ws = wb.create_sheet('No data'); ws.append(['No Round 1–2 closing ranks for this choice yet.'])
    buf = io.BytesIO(); wb.save(buf)
    fname = re.sub(r'[^A-Za-z0-9]+', '_', f"College_Rankings_{p['name']}_{p['label']}_{speciality or 'all'}_2025_vs_2026")
    return buf.getvalue(), fname.strip('_')[:120] + '.xlsx'


def api_rankings_xlsx():
    """GET /api/pg/rankings/xlsx?authority=mcc|<state>&list=<key>&category=<code>&speciality=<course>"""
    from flask import request, jsonify, Response
    from db import get_db
    from pg_admin.routes import rankings as rk
    ok, err = rk._doctor_or_desk()
    if not ok:
        return err
    conn = get_db()
    try:
        auth = (request.args.get('authority') or 'mcc').strip().lower()
        key = (request.args.get('list') or ('aiq_open' if auth == 'mcc' else 'govt')).strip()
        data, fname = build_xlsx(conn, auth, key, (request.args.get('category') or '').strip(),
                                 (request.args.get('speciality') or '').strip())
        if data is None:
            return jsonify({'ok': False, 'error': 'unknown_list'}), 404
        return Response(data, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename="{fname}"'})
    except Exception as e:
        import logging
        logging.error("api_rankings_xlsx: %s", e)
        try: conn.rollback()
        except Exception: pass
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()
