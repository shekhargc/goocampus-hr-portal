"""Team college lists — Ashwini's own, judgement-based order of colleges (founder 2026-10-15).

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
    items = [dict(r) for r in conn.execute(
        "SELECT id, college_code, college_name, state, position, label, note, seats, is_new "
        "FROM pg_team_college_list_items WHERE list_id=? ORDER BY state, position, id", [lid]).fetchall()]
    by = {}
    for it in items:
        it['college'] = rec._short_name(it.pop('college_name'))
        it['is_new'] = bool(it['is_new'])
        by.setdefault(it['state'], []).append(it)
    states = [s for s in sorder if s in by] + sorted(s for s in by if s not in sorder)
    for k in ('created_at', 'updated_at'):
        l[k] = str(l[k])[:16] if l.get(k) else ''
    l.pop('state_order', None)
    return {'list': l, 'states': [{'state': s, 'items': by[s]} for s in states],
            'labels': [x for x in _LABELS if x]}


def _guard():
    from pg_admin.routes.desk_api import _guard as g, _actor_name
    m, _, err = g()
    return (None, err) if err else (_actor_name(m), None)


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
            rows = [dict(r) for r in conn.execute(
                "SELECT l.id, l.name, l.kind, l.created_by, l.updated_by, l.updated_at, "
                "(SELECT COUNT(*) FROM pg_team_college_list_items i WHERE i.list_id=l.id) AS colleges "
                "FROM pg_team_college_lists l ORDER BY l.updated_at DESC").fetchall()]
            for r in rows:
                r['updated_at'] = str(r['updated_at'])[:16] if r.get('updated_at') else ''
            return jsonify({'ok': True, 'lists': rows})
        body = request.get_json(silent=True) or {}
        name = _s(body.get('name')) or 'Deemed colleges — GooCampus 2026'
        src = body.get('copy_from')
        lid = conn.execute("INSERT INTO pg_team_college_lists (name, kind, created_by, updated_by) "
                           "VALUES (?, 'deemed', ?, ?) RETURNING id", [name, who, who]).fetchone()['id']
        if src:
            s = conn.execute("SELECT state_order FROM pg_team_college_lists WHERE id=?", [src]).fetchone()
            if s:
                conn.execute("UPDATE pg_team_college_lists SET state_order=? WHERE id=?", [s['state_order'], lid])
            conn.execute("INSERT INTO pg_team_college_list_items (list_id, college_code, college_name, state, position, "
                         "label, note, seats, is_new) SELECT ?, college_code, college_name, state, position, label, note, "
                         "seats, is_new FROM pg_team_college_list_items WHERE list_id=?", [lid, src])
        else:
            pos = {}
            for r in _deemed_colleges(conn):
                p = pos[r['state']] = pos.get(r['state'], 0) + 1
                conn.execute("INSERT INTO pg_team_college_list_items (list_id, college_code, college_name, state, "
                             "position, seats, is_new) VALUES (?,?,?,?,?,?,?)",
                             [lid, r['college_code'], r['name'] or '', r['state'] or '', p, int(r['seats'] or 0),
                              1 if r['is_new'] else 0])
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
    pdf = _pdf_base(data['list']['name'], 'GooCampus counsellor\'s recommended order · state by state')
    pdf.set_font('Helvetica', '', 8.8); pdf.set_text_color(*_GREY)
    pdf.multi_cell(0, 4.6, _t(
        "Deemed university colleges in MCC's 2026 seat matrix, in the order our counselling team recommends "
        "within each state - based on our experience of each college's clinical exposure, faculty and standing, "
        "not on last year's cut-offs or fees. Colleges marked 'New' are new in 2026. This is GooCampus guidance - a "
        "suggestion only; please verify before you lock your choices."), new_x='LMARGIN', new_y='NEXT')
    want = {x.strip().lower() for x in (states or []) if x.strip()}
    for grp in data['states']:
        if want and grp['state'].lower() not in want:
            continue
        if pdf.get_y() > 245:
            pdf.add_page()
        pdf.ln(4); pdf.set_font('Helvetica', 'B', 12); pdf.set_text_color(*_NAVY)
        pdf.cell(0, 7, _t(f"{grp['state']} ({len(grp['items'])})"), new_x='LMARGIN', new_y='NEXT')
        _table(pdf, [[str(i), it['college'] + ('  [New]' if it['is_new'] else ''), it['label'] or '',
                      str(it['seats']), it['note'] or ''] for i, it in enumerate(grp['items'], start=1)],
               ('#', 'College', 'GooCampus view', '2026 seats', 'Note'), (9, 86, 26, 17, 48),
               ('CENTER', 'LEFT', 'LEFT', 'RIGHT', 'LEFT'))
    slug = ''.join(ch if ch.isalnum() else '_' for ch in data['list']['name'])[:50]
    return bytes(pdf.output()), f'{slug}.pdf'


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
