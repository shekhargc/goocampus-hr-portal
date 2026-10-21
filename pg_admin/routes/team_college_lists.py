"""Team college lists — the counselling team's own, judgement-based order of colleges (founder 2026-10-15).

Data (last year's ranks) can't judge deemed colleges well: their demand follows FEES, so a cheaper
average college "fills fast" while a better, costlier one looks slow. So the counsellor makes her
own list: every deemed college in MCC's 2026 matrix (last year's + new ones), grouped STATE BY
STATE, which she orders within each state (and orders the states), with an optional Top / Good /
Average label and a one-line note per college. Team-only (never shown to doctors); she downloads a
GooCampus-branded PDF and sends it on WhatsApp herself. Several named lists can exist (e.g. a
general one + a variant for a particular doctor) — "copy_from" duplicates one.
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
    return {'list': l, 'states': [{'state': s, 'items': by[s]} for s in states],
            'labels': [x for x in _LABELS if x]}


def _guard():
    from pg_admin.routes.desk_api import _guard as g, _actor_name
    m, _, err = g()
    return (None, err) if err else (_actor_name(m), None)


def _create(conn, who, name, mode, only):
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


def _generate_all(conn, who):
    """Make sure there is ONE All-India list + ONE list per state (12 today). Idempotent — creates
    only what is missing (matched by mode + states), never touches an existing list's order."""
    have = set()
    for r in conn.execute("SELECT mode, states_filter FROM pg_team_college_lists").fetchall():
        try:
            f = json.loads(r['states_filter'] or '[]')
        except Exception:
            f = []
        have.add(((r['mode'] or 'by_state'), tuple(sorted(x.lower() for x in f))))
    made = 0
    if ('all_india', ()) not in have:
        _create(conn, who, _BASE + ' — All India', 'all_india', []); made += 1
    for st in sorted({(r['state'] or '') for r in _deemed_colleges(conn) if r['state']}):
        if ('by_state', (st.lower(),)) not in have:
            _create(conn, who, f'{_BASE} — {st}', 'by_state', [st]); made += 1
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
            rows = [dict(r) for r in conn.execute(
                "SELECT l.id, l.name, l.kind, COALESCE(l.mode,'by_state') AS mode, l.states_filter, "
                "l.created_by, l.updated_by, l.updated_at, "
                "(SELECT COUNT(*) FROM pg_team_college_list_items i WHERE i.list_id=l.id) AS colleges "
                "FROM pg_team_college_lists l ORDER BY (COALESCE(l.mode,'')<>'all_india'), l.name").fetchall()]
            for r in rows:
                r['updated_at'] = str(r['updated_at'])[:16] if r.get('updated_at') else ''
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
        if src:
            sr = conn.execute("SELECT mode, states_filter FROM pg_team_college_lists WHERE id=?", [src]).fetchone()
            if sr:
                mode = sr['mode'] or 'by_state'
                try:
                    only = json.loads(sr['states_filter'] or '[]')
                except Exception:
                    only = []
        default = (_BASE + (' — All India' if mode == 'all_india' else '')
                   + ((' — ' + ', '.join(only)) if only else ''))
        name = _s(body.get('name')) or default
        if not src:
            lid = _create(conn, who, name, mode, only)
        else:
            lid = conn.execute("INSERT INTO pg_team_college_lists (name, kind, created_by, updated_by, mode, states_filter) "
                               "VALUES (?, 'deemed', ?, ?, ?, ?) RETURNING id",
                               [name, who, who, mode, json.dumps(only)]).fetchone()['id']
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
                                 "WHERE list_id=? AND college_code=?",
                                 [pos, lab, _s(it.get('note'))[:300], lid, code])
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
    pdf = _pdf_base('GooCampus Recommended Colleges', 'Deemed universities · MCC PG 2026 · ' +
                    ('all India' if data['list'].get('mode') == 'all_india' else 'state by state'))
    pdf.footer_note = 'GooCampus Recommended Colleges - a suggestion only; the final decision is yours.'
    pdf.set_font('Helvetica', '', 8.8); pdf.set_text_color(*_GREY)
    pdf.multi_cell(0, 4.6, _t(
        "Deemed university colleges in MCC's 2026 seat matrix, in the order GooCampus recommends "
        + ("across India" if data['list'].get('mode') == 'all_india' else "within each state") + " - based on each college's clinical exposure, faculty and standing, not on last year's cut-offs or "
        "fees. Colleges marked 'New' are new in 2026."), new_x='LMARGIN', new_y='NEXT')
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
    cols.append(('2026 seats', 17, 'RIGHT', lambda i, it: str(it['seats'])))
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
