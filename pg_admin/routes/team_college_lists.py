"""Team college lists — the counselling team's own, judgement-based order of colleges (founder 2026-10-15).

Data (last year's ranks) can't judge deemed colleges well: their demand follows FEES, so a cheaper
average college "fills fast" while a better, costlier one looks slow. So the counsellor makes her
own list: every deemed college in MCC's 2026 matrix (last year's + new ones), grouped STATE BY
STATE, which she orders within each state (and orders the states), with an optional Top / Good /
Average label and a one-line note per college. Team-only (never shown to doctors); she downloads a
GooCampus-branded PDF and sends it on WhatsApp herself. Several named lists can exist (e.g. a
general one + a variant for a particular doctor) — "copy_from" duplicates one.

State counselling lists (founder 2026-10-31): kind 'state:<authority>' — every MD/MS college in that state's
2026 matrix, grouped by SEAT TYPE instead of by state (Government colleges / Private colleges / Management
Quota / NRI Quota — the College Rankings lists; Management and NRI always separate). The group name sits in
the item's `state` column, so ordering / grading / remarks / PDF work unchanged; a college may appear in several
groups. Seeded in the draft College Rankings order (Top → Good → Average → New). "Email this PDF" sends it to a
test address, one doctor, or every Internal + Paid doctor linked to the list's state.
"""
import json
import logging
from flask import request, jsonify, Response

from db import get_db
from pg_admin.routes import recommended as rec

_LABELS = ('', 'Top', 'Good', 'Average')
ALL_INDIA = 'All India'
_READY = False


def _s(v):
    return (str(v).strip() if v is not None else '')


def ensure_tables(conn):
    global _READY
    if _READY:
        return
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_team_college_lists (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT DEFAULT 'deemed',          -- which colleges it covers
            state_order TEXT DEFAULT '[]',       -- ordered state names
            created_by TEXT DEFAULT '',
            updated_by TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_team_college_list_items (
            id SERIAL PRIMARY KEY,
            list_id INTEGER NOT NULL,
            college_code TEXT NOT NULL,
            college_name TEXT DEFAULT '',
            state TEXT DEFAULT '',
            position INTEGER DEFAULT 0,          -- order WITHIN its state
            label TEXT DEFAULT '',               -- '' | Top | Good | Average (her own)
            note TEXT DEFAULT '',
            seats INTEGER DEFAULT 0,
            is_new INTEGER DEFAULT 0
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_team_cl_items ON pg_team_college_list_items (list_id, state, position)")
        # mode: 'by_state' (ordered within each state) | 'all_india' (one order across the country)
        conn.execute("ALTER TABLE pg_team_college_lists ADD COLUMN IF NOT EXISTS mode TEXT DEFAULT 'by_state'")
        conn.execute("ALTER TABLE pg_team_college_lists ADD COLUMN IF NOT EXISTS states_filter TEXT DEFAULT '[]'")
        conn.commit()
        _READY = True
    except Exception as e:
        logging.warning("team_college_lists ensure: %s", e)
        try: conn.rollback()
        except Exception: pass


def _deemed_colleges(conn):
    """Every college in the official MCC Deemed matrix (all quotas), with seats + new flag,
    pre-ordered per state by the Deemed Paid tier then main-round demand (a starting point only)."""
    bodies = rec._bodies(conn, 'deemed')
    if not bodies:
        return []
    ph = ','.join(['?'] * len(bodies))
    rows = [dict(r) for r in conn.execute(
        f"SELECT college_code, MAX(college_name) AS name, MAX(state) AS state, SUM(seats) AS seats, "
        f"MAX(CASE WHEN COALESCE(cutoff_institute,'')<>'' THEN 1 ELSE 0 END) AS hist "
        f"FROM pg_seat_matrix WHERE counselling_body IN ({ph}) GROUP BY college_code", bodies).fetchall()]
    tiers = {r['college_code']: dict(r) for r in conn.execute(
        "SELECT college_code, tier, basis_rank FROM pg_college_tiers WHERE list_key='deemed_paid_open'").fetchall()}
    order = {'Top': 0, 'Good': 1, 'Average': 2}
    for r in rows:
        t = tiers.get(r['college_code']) or {}
        r['is_new'] = not r['hist']
        r['_k'] = (r['state'] or '', 1 if r['is_new'] else 0, order.get(t.get('tier'), 2),
                   t.get('basis_rank') or 10 ** 9, r['name'] or '')
    rows.sort(key=lambda r: r['_k'])
    return rows


def _is_state(l):
    return (l.get('kind') or '').startswith('state:')


def _state_colleges(conn, authority):
    """[{group, college_code, name, seats, is_new}] for a state body, groups in College Rankings order."""
    from pg_admin.routes import state_rankings as srk
    a = srk._body(conn, authority)
    if not a or (a.get('source') or 'matrix') != 'matrix':   # state lists need the 2026 matrix (seat counts)
        return None, []
    rows = srk._rows(conn, a['body'])
    clinical = srk._clinical_fn(conn)
    out = []
    for key, label in srk.LISTS.items():
        for c in srk.list_payload(conn, authority, a['body'], key, rows, clinical):
            out.append({'group': label, 'college_code': c['college_code'], 'name': c['college'],
                        'seats': c['seats'], 'is_new': c['new_college']})
    return a, out


def _payload(conn, lid):
    l = conn.execute("SELECT * FROM pg_team_college_lists WHERE id=?", [lid]).fetchone()
    if not l:
        return None
    l = dict(l)
    try:
        sorder = json.loads(l.get('state_order') or '[]')
    except Exception:
        sorder = []
    all_india = (l.get('mode') or 'by_state') == 'all_india'
    items = [dict(r) for r in conn.execute(
        "SELECT id, college_code, college_name, state, position, label, note, seats, is_new "
        "FROM pg_team_college_list_items WHERE list_id=? ORDER BY " + ("position, id" if all_india else "state, position, id"),
        [lid]).fetchall()]
    by = {}
    for it in items:
        it['college'] = rec._short_name(it.pop('college_name'))
        it['is_new'] = bool(it['is_new'])
        by.setdefault(ALL_INDIA if all_india else it['state'], []).append(it)
    states = [s for s in sorder if s in by] + sorted(s for s in by if s not in sorder)
    try:
        l['states_filter'] = json.loads(l.get('states_filter') or '[]')
    except Exception:
        l['states_filter'] = []
    l['mode'] = 'all_india' if all_india else 'by_state'
    for k in ('created_at', 'updated_at'):
        l[k] = str(l[k])[:16] if l.get(k) else ''
    l.pop('state_order', None)
    # state lists: the groups are seat types, not states (the UI can say "Seat type" instead of "State")
    l['group_by'] = 'seat_type' if _is_state(l) else ('all_india' if all_india else 'state')
    l['authority'] = (l.get('kind') or '')[6:] if _is_state(l) else 'mcc'
    return {'list': l, 'states': [{'state': s, 'items': by[s]} for s in states],
            'labels': [x for x in _LABELS if x]}


def _guard():
    from pg_admin.routes.desk_api import _guard as g, _actor_name
    m, _, err = g()
    return (None, err) if err else (_actor_name(m), None)


def _create(conn, who, name, mode, only, kind='deemed'):
    if kind.startswith('state:'):
        a, seed = _state_colleges(conn, kind[6:])
        if not a:
            return None
        want = {x.lower() for x in only}
        groups = []
        for r in seed:
            if r['group'] not in groups:
                groups.append(r['group'])
        lid = conn.execute("INSERT INTO pg_team_college_lists (name, kind, created_by, updated_by, mode, states_filter, "
                           "state_order) VALUES (?, ?, ?, ?, 'by_state', ?, ?) RETURNING id",
                           [name, kind, who, who, json.dumps(only), json.dumps(groups)]).fetchone()['id']
        pos = {}
        for r in seed:
            if want and r['group'].lower() not in want:
                continue
            p = pos[r['group']] = pos.get(r['group'], 0) + 1
            conn.execute("INSERT INTO pg_team_college_list_items (list_id, college_code, college_name, state, "
                         "position, seats, is_new) VALUES (?,?,?,?,?,?,?)",
                         [lid, r['college_code'], r['name'] or '', r['group'], p, int(r['seats'] or 0),
                          1 if r['is_new'] else 0])
        return lid
    lid = conn.execute("INSERT INTO pg_team_college_lists (name, kind, created_by, updated_by, mode, states_filter) "
                       "VALUES (?, 'deemed', ?, ?, ?, ?) RETURNING id",
                       [name, who, who, mode, json.dumps(only)]).fetchone()['id']
    want = {x.lower() for x in only}
    seed = [r for r in _deemed_colleges(conn) if not want or (r['state'] or '').lower() in want]
    if mode == 'all_india':
        order = {'Top': 0, 'Good': 1, 'Average': 2}
        tiers = {r['college_code']: dict(r) for r in conn.execute(
            "SELECT college_code, tier, basis_rank FROM pg_college_tiers WHERE list_key='deemed_paid_open'").fetchall()}
        seed.sort(key=lambda r: (1 if r['is_new'] else 0,
                                 order.get((tiers.get(r['college_code']) or {}).get('tier'), 2),
                                 (tiers.get(r['college_code']) or {}).get('basis_rank') or 10 ** 9, r['name'] or ''))
    pos = {}
    for r in seed:
        key = ALL_INDIA if mode == 'all_india' else r['state']
        p = pos[key] = pos.get(key, 0) + 1
        conn.execute("INSERT INTO pg_team_college_list_items (list_id, college_code, college_name, state, "
                     "position, seats, is_new) VALUES (?,?,?,?,?,?,?)",
                     [lid, r['college_code'], r['name'] or '', r['state'] or '', p, int(r['seats'] or 0),
                      1 if r['is_new'] else 0])
    return lid


_BASE = 'GooCampus Recommended Colleges — Deemed Universities 2026'
_STATE_BASE = 'GooCampus Recommended Colleges — {name} State Counselling 2026'


def _state_name(conn, kind):
    from pg_admin.routes import state_rankings as srk
    a = srk._body(conn, (kind or '')[6:])
    return a['name'] if a else (kind or '')[6:]


def _generate_all(conn, who):
    """Make sure there is ONE All-India list + ONE list per state (12 today). Idempotent — creates
    only what is missing (matched by mode + states), never touches an existing list's order."""
    have, kinds = set(), set()
    for r in conn.execute("SELECT kind, mode, states_filter FROM pg_team_college_lists").fetchall():
        try:
            f = json.loads(r['states_filter'] or '[]')
        except Exception:
            f = []
        if (r['kind'] or 'deemed').startswith('state:'):
            kinds.add(r['kind'])
            continue
        have.add(((r['mode'] or 'by_state'), tuple(sorted(x.lower() for x in f))))
    made = 0
    if ('all_india', ()) not in have:
        _create(conn, who, _BASE + ' — All India', 'all_india', []); made += 1
    for st in sorted({(r['state'] or '') for r in _deemed_colleges(conn) if r['state']}):
        if ('by_state', (st.lower(),)) not in have:
            _create(conn, who, f'{_BASE} — {st}', 'by_state', [st]); made += 1
    made += _generate_states(conn, who, kinds)
    return made


def _generate_states(conn, who, kinds=None):
    """One list per state counselling authority with a 2026 matrix (only the missing ones)."""
    from pg_admin.routes import state_rankings as srk
    if kinds is None:
        kinds = {r['kind'] for r in conn.execute(
            "SELECT kind FROM pg_team_college_lists WHERE LEFT(COALESCE(kind,''), 6)='state:'").fetchall()}
    made = 0
    for a in srk.authorities(conn, with_cutoffs=False):
        k = 'state:' + a['authority']
        if k not in kinds and _create(conn, who, _STATE_BASE.format(name=a['name']), 'by_state', [], kind=k):
            made += 1
    return made


# ── Routes (Desk team only) ──────────────────────────────────────────────────
def lists_index():
    """GET → all lists.  POST {name, copy_from?} → create (prefilled with every 2026 deemed college)."""
    who, err = _guard()
    if err:
        return err
    conn = get_db()
    try:
        ensure_tables(conn)
        if request.method == 'GET':
            # All-India + one list per state are created automatically ONCE (founder 2026-10-21: a
            # hand-made Karnataka list existed, so the old "only when there are no lists at all" rule never
            # fired). Idempotent — only missing lists are added, existing ones are never touched; the
            # marker stops a list the team deliberately deleted from coming back.
            conn.execute("CREATE TABLE IF NOT EXISTS pg_team_college_lists_meta (k TEXT PRIMARY KEY, v TEXT)")
            if not conn.execute("SELECT 1 FROM pg_team_college_lists_meta WHERE k='auto_generated_v2'").fetchone():
                _generate_all(conn, who)
                conn.execute("INSERT INTO pg_team_college_lists_meta (k, v) VALUES ('auto_generated_v2', ?) "
                             "ON CONFLICT (k) DO NOTHING", [who])
                conn.commit()
            # state counselling lists (founder 2026-10-31): created once per authority; a state whose matrix
            # arrives later is added by "Create missing lists" (generate_all)
            if not conn.execute("SELECT 1 FROM pg_team_college_lists_meta WHERE k='auto_generated_states_v1'").fetchone():
                _generate_states(conn, who)
                conn.execute("INSERT INTO pg_team_college_lists_meta (k, v) VALUES ('auto_generated_states_v1', ?) "
                             "ON CONFLICT (k) DO NOTHING", [who])
                conn.commit()
            rows = [dict(r) for r in conn.execute(
                "SELECT l.id, l.name, l.kind, COALESCE(l.mode,'by_state') AS mode, l.states_filter, "
                "l.created_by, l.updated_by, l.updated_at, "
                "(SELECT COUNT(*) FROM pg_team_college_list_items i WHERE i.list_id=l.id) AS colleges "
                "FROM pg_team_college_lists l ORDER BY (COALESCE(l.mode,'')<>'all_india'), "
                "(LEFT(COALESCE(l.kind,''), 6)='state:'), l.name").fetchall()]
            for r in rows:
                r['updated_at'] = str(r['updated_at'])[:16] if r.get('updated_at') else ''
                r['group'] = 'state_counselling' if (r['kind'] or '').startswith('state:') else (
                    'all_india' if r['mode'] == 'all_india' else 'state_wise')
                r['authority'] = (r['kind'] or '')[6:] if r['group'] == 'state_counselling' else 'mcc'
                try:
                    r['states_filter'] = json.loads(r.get('states_filter') or '[]')
                except Exception:
                    r['states_filter'] = []
            return jsonify({'ok': True, 'lists': rows})
        body = request.get_json(silent=True) or {}
        if body.get('generate_all'):
            made = _generate_all(conn, who)
            conn.commit()
            return jsonify({'ok': True, 'created': made})
        src = body.get('copy_from')
        mode = 'all_india' if _s(body.get('mode')) == 'all_india' else 'by_state'
        only = [_s(x) for x in (body.get('states') or []) if _s(x)]
        # a state counselling list: {authority:'kea'} (optional states = seat-type groups to include)
        kind = ('state:' + _s(body.get('authority')).lower()) if _s(body.get('authority')) not in ('', 'mcc') else 'deemed'
        if src:
            sr = conn.execute("SELECT kind, mode, states_filter FROM pg_team_college_lists WHERE id=?", [src]).fetchone()
            if sr:
                mode = sr['mode'] or 'by_state'
                kind = sr['kind'] or 'deemed'
                try:
                    only = json.loads(sr['states_filter'] or '[]')
                except Exception:
                    only = []
        if kind.startswith('state:'):
            mode = 'by_state'
            default = _STATE_BASE.format(name=_state_name(conn, kind)) + ((' — ' + ', '.join(only)) if only else '')
        else:
            default = (_BASE + (' — All India' if mode == 'all_india' else '')
                       + ((' — ' + ', '.join(only)) if only else ''))
        name = _s(body.get('name')) or default
        if not src:
            lid = _create(conn, who, name, mode, only, kind=kind)
            if not lid:
                return jsonify({'ok': False, 'error': 'unknown_authority'}), 400
        else:
            lid = conn.execute("INSERT INTO pg_team_college_lists (name, kind, created_by, updated_by, mode, states_filter) "
                               "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                               [name, kind, who, who, mode, json.dumps(only)]).fetchone()['id']
            s = conn.execute("SELECT state_order FROM pg_team_college_lists WHERE id=?", [src]).fetchone()
            if s:
                conn.execute("UPDATE pg_team_college_lists SET state_order=? WHERE id=?", [s['state_order'], lid])
            conn.execute("INSERT INTO pg_team_college_list_items (list_id, college_code, college_name, state, position, "
                         "label, note, seats, is_new) SELECT ?, college_code, college_name, state, position, label, note, "
                         "seats, is_new FROM pg_team_college_list_items WHERE list_id=?", [lid, src])
        conn.commit()
        return jsonify({'ok': True, **_payload(conn, lid)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("team college lists: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def list_detail(lid):
    """GET → the list grouped by state.  POST {name?, state_order?:[states], states?:{state:[{college_code,
    label?, note?}] in order}} → saves names/order/labels/notes (colleges are never added/removed here).
    DELETE → remove the list."""
    who, err = _guard()
    if err:
        return err
    conn = get_db()
    try:
        ensure_tables(conn)
        if not conn.execute("SELECT 1 FROM pg_team_college_lists WHERE id=?", [lid]).fetchone():
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        if request.method == 'DELETE':
            conn.execute("DELETE FROM pg_team_college_list_items WHERE list_id=?", [lid])
            conn.execute("DELETE FROM pg_team_college_lists WHERE id=?", [lid])
            conn.commit()
            return jsonify({'ok': True, 'deleted': True})
        if request.method == 'POST':
            body = request.get_json(silent=True) or {}
            by_group = (conn.execute("SELECT COALESCE(mode,'by_state') AS m FROM pg_team_college_lists WHERE id=?",
                                     [lid]).fetchone()['m'] != 'all_india')
            if _s(body.get('name')):
                conn.execute("UPDATE pg_team_college_lists SET name=? WHERE id=?", [_s(body['name']), lid])
            if isinstance(body.get('state_order'), list):
                conn.execute("UPDATE pg_team_college_lists SET state_order=? WHERE id=?",
                             [json.dumps([_s(x) for x in body['state_order'] if _s(x)]), lid])
            for state, arr in (body.get('states') or {}).items():
                # in an All-India list the single group key is 'All India' — positions are country-wide
                for pos, it in enumerate(arr or [], start=1):
                    code = _s(it.get('college_code'))
                    if not code:
                        continue
                    lab = _s(it.get('label'))
                    lab = lab if lab in _LABELS else ''
                    conn.execute("UPDATE pg_team_college_list_items SET position=?, label=?, note=? "
                                 "WHERE list_id=? AND college_code=?" + (" AND state=?" if by_group else ""),
                                 [pos, lab, _s(it.get('note'))[:300], lid, code] + ([_s(state)] if by_group else []))
            conn.execute("UPDATE pg_team_college_lists SET updated_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         [who, lid])
            conn.commit()
        return jsonify({'ok': True, **_payload(conn, lid)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("team college list %s: %s", lid, e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def build_pdf(conn, lid, states=None):
    from pg_admin.routes.rankings import _pdf_base, _table
    from pg_admin.choice_pdf import _t, _NAVY, _GREY
    data = _payload(conn, lid)
    if not data:
        return None, None
    if _is_state(data['list']):
        return _build_state_pdf(conn, data, states)
    pdf = _pdf_base('GooCampus Recommended Colleges', 'Deemed universities · MCC PG 2026 · ' +
                    ('all India' if data['list'].get('mode') == 'all_india' else 'state by state'))
    pdf.footer_note = 'GooCampus Recommended Colleges - a suggestion only; the final decision is yours.'
    # no intro paragraph (founder 2026-10-31) — only the "Please note" box above the lists
    pdf.ln(1); pdf.set_fill_color(255, 247, 237); pdf.set_draw_color(253, 186, 116); pdf.set_text_color(124, 45, 18)
    pdf.set_font('Helvetica', '', 8.6)
    pdf.multi_cell(0, 4.6, _t('Please note: this is a suggestion from GooCampus to help you decide. Please verify '
                              'every college before you lock your choices - the final decision, and responsibility '
                              'for it, is yours.'), border='L', fill=True, new_x='LMARGIN', new_y='NEXT')
    pdf.set_fill_color(255, 255, 255)
    want = {x.strip().lower() for x in (states or []) if x.strip()}
    if data['list'].get('mode') == 'all_india':
        rows = [it for grp in data['states'] for it in grp['items']
                if not want or (it['state'] or '').lower() in want]
        pdf.ln(4); pdf.set_font('Helvetica', 'B', 12); pdf.set_text_color(*_NAVY)
        pdf.cell(0, 7, _t(f"All India ({len(rows)})"), new_x='LMARGIN', new_y='NEXT')
        _flex_table(pdf, rows, with_state=True)
        return bytes(pdf.output()), 'GooCampus_Recommended_Colleges_Deemed_2026_All_India.pdf'
    for grp in data['states']:
        if want and grp['state'].lower() not in want:
            continue
        if pdf.get_y() > 245:
            pdf.add_page()
        pdf.ln(4); pdf.set_font('Helvetica', 'B', 12); pdf.set_text_color(*_NAVY)
        pdf.cell(0, 7, _t(f"{grp['state']} ({len(grp['items'])})"), new_x='LMARGIN', new_y='NEXT')
        _flex_table(pdf, grp['items'], with_state=False)
    tail = ('_' + '_'.join(''.join(c for c in x if c.isalnum()) for x in sorted(want))[:60]) if want else ''
    return bytes(pdf.output()), f'GooCampus_Recommended_Colleges_Deemed_2026{tail}.pdf'


def _build_state_pdf(conn, data, groups=None):
    import re
    from pg_admin.routes.rankings import _pdf_base
    from pg_admin.choice_pdf import _t, _NAVY, _GREY
    name = _state_name(conn, data['list'].get('kind'))
    pdf = _pdf_base('GooCampus Recommended Colleges', f'{name} state counselling · PG 2026 · by seat type')
    pdf.footer_note = 'GooCampus Recommended Colleges - a suggestion only; the final decision is yours.'
    # no intro paragraph (founder 2026-10-31) — only the "Please note" box above the lists
    pdf.ln(1); pdf.set_fill_color(255, 247, 237); pdf.set_draw_color(253, 186, 116); pdf.set_text_color(124, 45, 18)
    pdf.set_font('Helvetica', '', 8.6)
    pdf.multi_cell(0, 4.6, _t('Please note: this is a suggestion from GooCampus to help you decide. Please verify '
                              'every college before you lock your choices - the final decision, and responsibility '
                              'for it, is yours.'), border='L', fill=True, new_x='LMARGIN', new_y='NEXT')
    pdf.set_fill_color(255, 255, 255)
    want = {x.strip().lower() for x in (groups or []) if x.strip()}
    for grp in data['states']:
        if want and grp['state'].lower() not in want:
            continue
        if pdf.get_y() > 245:
            pdf.add_page()
        pdf.ln(4); pdf.set_font('Helvetica', 'B', 12); pdf.set_text_color(*_NAVY)
        pdf.cell(0, 7, _t(f"{grp['state']} ({len(grp['items'])})"), new_x='LMARGIN', new_y='NEXT')
        _flex_table(pdf, grp['items'], with_state=False)
    slug = re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_')
    tail = ('_' + '_'.join(re.sub(r'[^A-Za-z0-9]+', '', x.title()) for x in sorted(want))[:60]) if want else ''
    return bytes(pdf.output()), f'GooCampus_Recommended_Colleges_{slug}_2026{tail}.pdf'


def _flex_table(pdf, items, with_state):
    """Only the columns that have content: Grade / Remarks are dropped when nothing is filled in."""
    from pg_admin.routes.rankings import _table
    has_grade = any((it.get('label') or '') for it in items)
    has_note = any((it.get('note') or '').strip() for it in items)
    cols = [('#', 9, 'CENTER', lambda i, it: str(i)),
            ('College', 0, 'LEFT', lambda i, it: it['college'] + ('  [New]' if it['is_new'] else ''))]
    if with_state:
        cols.append(('State', 30, 'LEFT', lambda i, it: it.get('state') or ''))
    if has_grade:
        cols.append(('Grade', 20, 'LEFT', lambda i, it: it.get('label') or ''))
    cols.append(('Seats', 17, 'RIGHT', lambda i, it: str(it['seats'])))
    if has_note:
        cols.append(('Remarks', 50, 'LEFT', lambda i, it: it.get('note') or ''))
    fixed = sum(w for _h, w, _a, _f in cols)
    widths = tuple(w if w else 186 - fixed for _h, w, _a, _f in cols)
    _table(pdf, [[f(i, it) for _h, _w, _a, f in cols] for i, it in enumerate(items, start=1)],
           tuple(h for h, _w, _a, _f in cols), widths, tuple(a for _h, _w, a, _f in cols))


def list_pdf(lid):
    """GET ?states=Karnataka,Tamil Nadu (optional) → the branded PDF."""
    who, err = _guard()
    if err:
        return err
    conn = get_db()
    try:
        ensure_tables(conn)
        sts = [x for x in (request.args.get('states') or '').split(',') if x.strip()]
        pdf, fn = build_pdf(conn, lid, sts)
        if not pdf:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': f'attachment; filename="{fn}"'})
    finally:
        conn.close()


# ── Email this PDF (founder 2026-10-31) ──────────────────────────────────────
# To a test address, ONE doctor, or every Internal + Paid doctor linked to the list's state(s) (home state,
# counselling-state chip or followed news state — the news "state" audience). All-India lists: every Internal +
# Paid doctor. Sent in the background, throttled; every send is logged.
def _ensure_email_log(conn):
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_college_list_email_log (
            id SERIAL PRIMARY KEY,
            list_id INTEGER,
            list_name TEXT DEFAULT '',
            kind TEXT DEFAULT 'state',         -- test | doctor | state | all
            groups TEXT DEFAULT '',            -- sections included in the PDF ('' = all)
            requested_by TEXT DEFAULT '',
            recipients INTEGER DEFAULT 0,
            sent INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'queued',      -- queued | sending | done
            test_to TEXT DEFAULT '',
            doctor_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP
        )''')
        conn.commit()
    except Exception:
        try: conn.rollback()
        except Exception: pass


def _list_states(conn, l, groups=None):
    """The state(s) a list is about — its doctors are the 'state' audience. [] = all-India list."""
    from pg_admin import authorities as A
    if _is_state(l):
        a = A.get_authority((l.get('kind') or '')[6:])
        return list(a['covers_states']) if a else [_state_name(conn, l.get('kind'))]
    if (l.get('mode') or 'by_state') == 'all_india':
        return []
    try:
        only = json.loads(l.get('states_filter') or '[]') if isinstance(l.get('states_filter'), str) else (l.get('states_filter') or [])
    except Exception:
        only = []
    return [x for x in (groups or only) if _s(x)]


def _email_recipients(conn, l, audience, doctor_id=None, groups=None):
    from pg_admin.routes.desk_api import _type_sql
    from pg_admin.news_email import _state_filter_sql
    where, params = ["x.t IN ('internal','paid')", "COALESCE(x.email,'') <> ''", "strpos(x.email, '@') > 0"], []
    if audience == 'doctor':
        where.append("x.id = ?"); params.append(int(doctor_id or 0))
    elif audience == 'state':
        sts = _list_states(conn, l, groups)
        if not sts:
            return []
        ors = []
        for st in sts:
            sql, p = _state_filter_sql(st)
            ors.append(sql); params += p
        where.append('(' + ' OR '.join(ors) + ')')
    rows = conn.execute(
        f"SELECT x.id, x.name, LOWER(TRIM(x.email)) AS email FROM (SELECT u.*, {_type_sql('u')} AS t FROM pg_users u "
        f"WHERE COALESCE(u.is_blocked,0)=0) x JOIN pg_users u ON u.id = x.id WHERE " + ' AND '.join(where), params).fetchall()
    seen, out = set(), []
    for r in rows:
        if r['email'] in seen:
            continue
        seen.add(r['email']); out.append({'email': r['email'], 'name': r['name'] or '', 'id': r['id']})
    return out


def _email_html(name, sender, title, what):
    from email_utils import render_branded_email
    from core.helpers import format_dr_name
    from html import escape
    dr = format_dr_name(name) if (name or '').strip() else 'Doctor'      # "Dr. <name>" (idempotent)
    inner = (f"<p style='margin:0 0 14px;font-size:15px;color:#0F1B33;'>Dear {escape(dr)},</p>"
             f"<p style='margin:0 0 14px;font-size:14px;color:#374151;line-height:1.6;'>Please find attached "
             f"<b>{escape(title)}</b> — {escape(what)}, in the order the GooCampus counselling team recommends.</p>"
             "<p style='margin:0 0 14px;font-size:14px;color:#374151;line-height:1.6;'>Use it alongside your "
             "personalised choice list on <a href='https://goocampus.in/dashboard' style='color:#EA6C1E;'>"
             "goocampus.in</a>. Your counsellor is happy to talk it through.</p>"
             "<p style='margin:0 0 16px;font-size:12px;color:#6b7280;line-height:1.55;border-left:3px solid #fdba74;"
             "padding:6px 10px;background:#fff7ed;'>This is GooCampus guidance — a suggestion only. Please verify "
             "every college before you lock your choices; the final decision is yours.</p>"
             f"<p style='margin:0;font-size:14px;color:#374151;'>Warm regards,<br>{escape(sender)}<br>Team GooCampus</p>")
    return render_branded_email(title, inner, preheader='GooCampus Recommended Colleges 2026')


def _send_list(log_id, lid, groups, recips, sender, test):
    import base64, time
    from email_utils import send_email
    from pg_admin import email_tracking as ET
    conn = get_db()
    try:
        pdf, fn = build_pdf(conn, lid, groups)
        l = dict(conn.execute("SELECT * FROM pg_team_college_lists WHERE id=?", [lid]).fetchone())
        if _is_state(l):
            name = _state_name(conn, l.get('kind'))
            title, what = f'GooCampus Recommended Colleges — {name} 2026', \
                f"the MD/MS colleges in {name}'s state counselling, by seat type"
        else:
            title, what = 'GooCampus Recommended Colleges — Deemed Universities 2026', \
                "the deemed university colleges in MCC's 2026 counselling"
        conn.execute("UPDATE pg_college_list_email_log SET status='sending', recipients=? WHERE id=?", [len(recips), log_id])
        conn.commit()
    except Exception as e:
        logging.error("college list email prepare: %s", e)
        try: conn.rollback()
        except Exception: pass
        conn.close()
        return
    atts = [{'filename': fn, 'content': base64.b64encode(pdf).decode('ascii')}]
    sent = failed = 0
    for r in recips:
        try:
            html, tok = _email_html(r['name'], sender, title, what), None
            if not test:
                html, tok = ET.wrap(conn, html, kind='college_list', email=r['email'], subject=title,
                                    ref_id=log_id, ref_label=title, user_id=r.get('id'))
            ok = send_email([r['email']], title, html, from_address='GooCampus <info@goocampus.in>', attachments=atts)
            ET.mark_sent(conn, tok, ok)
            sent += 1 if ok else 0
            failed += 0 if ok else 1
        except Exception as e:
            failed += 1
            logging.error("college list email to %s: %s", r['email'], e)
        time.sleep(0.4)            # Resend: 2 req/sec
    try:
        conn.execute("UPDATE pg_college_list_email_log SET status='done', sent=?, failed=?, finished_at=CURRENT_TIMESTAMP "
                     "WHERE id=?", [sent, failed, log_id])
        conn.commit()
    finally:
        conn.close()


def list_email(lid):
    """GET → who the list's "state doctors" are (count + states) + recent sends.
    POST {test_to} → one test email; {doctor_id} → that Internal / Paid doctor; {audience:'state', confirm:true}
    → every Internal + Paid doctor of the list's state(s) ('all' for an All-India list). Optional groups:[..]
    = the sections to include (as "PDF for selected states")."""
    import re, threading
    who, err = _guard()
    if err:
        return err
    conn = get_db()
    try:
        ensure_tables(conn)
        _ensure_email_log(conn)
        r = conn.execute("SELECT * FROM pg_team_college_lists WHERE id=?", [lid]).fetchone()
        if not r:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        l = dict(r)
        default_aud = 'all' if (not _is_state(l) and (l.get('mode') or '') == 'all_india') else 'state'
        if request.method == 'GET':
            log = [dict(x) for x in conn.execute(
                "SELECT kind, groups, requested_by, recipients, sent, failed, status, test_to, doctor_id, created_at, "
                "finished_at FROM pg_college_list_email_log WHERE list_id=? ORDER BY id DESC LIMIT 20", [lid]).fetchall()]
            for x in log:
                for k in ('created_at', 'finished_at'):
                    x[k] = str(x[k])[:19] if x.get(k) else ''
            return jsonify({'ok': True, 'audience': default_aud, 'states': _list_states(conn, l),
                            'recipients': len(_email_recipients(conn, l, default_aud)), 'log': log})
        body = request.get_json(silent=True) or {}
        groups = [_s(x) for x in (body.get('groups') or []) if _s(x)]
        test_to = _s(body.get('test_to'))
        doctor_id = body.get('doctor_id')
        if test_to:
            if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', test_to):
                return jsonify({'ok': False, 'error': 'bad_email'}), 400
            kind, recips = 'test', [{'email': test_to.lower(), 'name': '', 'id': None}]
        elif doctor_id:
            kind, recips = 'doctor', _email_recipients(conn, l, 'doctor', doctor_id)
            if not recips:
                return jsonify({'ok': False, 'error': 'doctor_not_eligible',
                                'message': 'That doctor is not an Internal / Paid doctor with an email.'}), 400
        else:
            aud = _s(body.get('audience')) or default_aud
            if aud not in ('state', 'all'):
                return jsonify({'ok': False, 'error': 'bad_audience'}), 400
            if not body.get('confirm'):
                return jsonify({'ok': False, 'error': 'confirm_required',
                                'message': 'Send {confirm:true} to email these doctors.'}), 400
            kind, recips = aud, _email_recipients(conn, l, aud, groups=groups)
            if not recips:
                return jsonify({'ok': False, 'error': 'no_recipients'}), 400
        log_id = conn.execute(
            "INSERT INTO pg_college_list_email_log (list_id, list_name, kind, groups, requested_by, test_to, doctor_id) "
            "VALUES (?,?,?,?,?,?,?) RETURNING id",
            [lid, l.get('name') or '', kind, ', '.join(groups), who, test_to,
             int(doctor_id) if doctor_id else None]).fetchone()['id']
        conn.commit()
    finally:
        conn.close()
    threading.Thread(target=_send_list, args=(log_id, lid, groups, recips, who, kind == 'test'), daemon=True).start()
    return jsonify({'ok': True, 'queued': len(recips), 'log_id': log_id, 'kind': kind})
