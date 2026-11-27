"""College Database duplicates → review one pair at a time → merge into ONE college (founder 2026-11-27).

Founder: "the main college database should not have 2 college listings with the same name with different
spellings … 25 and 26 match to the same college database … keep the history of where it is matched."

  GET  /admin/pg/college-merge                 review page (pairs that look like one college + wrong links)
  GET  /admin/pg/college-merge/preview         what a merge would move (JSON, read-only)
  POST /admin/pg/college-merge/apply           merge dup → keep (one pair, founder-approved)
  POST /admin/pg/college-merge/not-same        remember "these are different colleges"
  POST /admin/pg/college-merge/move-alias      a spelling sits on the wrong college → move it (or unlink)

A merge never deletes anything:
  - every name of the duplicate becomes a remembered alias of the kept college (with a note of where from);
  - courses / favourites move unless the kept college already has the same one;
  - choice-list items + doctors' MBBS-college picks point at the kept college;
  - OUR 2026 imports (results, name memory, seat-matrix links that are not a 2025 cut-off name) move to the
    kept college's standard name. 2025 pg_cutoffs rows are never touched — they link through the moved alias;
  - the duplicate is hidden (kind='merged'), and a log row keeps a snapshot + every count for undo.
"""
import json
import logging
import re
import time
from collections import defaultdict
from itertools import combinations
from flask import render_template, request, redirect, url_for, flash, jsonify
from db import get_db
from core.users import get_user
from core.auth import login_required

GEN = set((
    'government govt gov medical college colleges hospital hospitals institute instt inst of and the sciences '
    'science research centre center general district state university health autonomous society medicine dr shri '
    'sri smt late pt pandit new campus amp prev previously known as erstwhile india formerly formely sector road '
    'mc gmc s rajkiya allopathic super speciality multi teaching rural for in at with attached associated group '
    'post graduate education civil hq headquarters head quarter quarters').split())
_CACHE = {}          # pair list kept 15 min until a merge / decision / alias change (speed, 2026-11-27)
GOVT = {'government', 'govt', 'autonomous', 'rajkiya', 'gmc', 'state'}


def norm(s):
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


def _nstate(s):
    s = norm(s).replace(' and ', ' ').replace('orissa', 'odisha').replace('pondicherry', 'puducherry')
    return s


def _admin():
    u = get_user()
    return u if (u and u.get('is_admin')) else None


def _who(u):
    return (u or {}).get('emp_code') or (u or {}).get('name') or 'admin'


def ensure_merge_tables(conn):
    """Boot-time only (called from ensure_college_master_tables) — never on a request path."""
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_college_merge_log (
        id SERIAL PRIMARY KEY, keep_id INTEGER, dup_id INTEGER, keep_name TEXT, dup_name TEXT,
        action TEXT DEFAULT 'merge', done_by TEXT DEFAULT '', done_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        detail TEXT DEFAULT '')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_college_pair_decision (
        id SERIAL PRIMARY KEY, a_id INTEGER NOT NULL, b_id INTEGER NOT NULL, decision TEXT DEFAULT 'not_same',
        decided_by TEXT DEFAULT '', decided_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_college_pair ON pg_college_pair_decision (a_id, b_id)")
    conn.execute("ALTER TABLE pg_college_alias ADD COLUMN IF NOT EXISTS note TEXT DEFAULT ''")


# ── evidence per college ─────────────────────────────────────────────────────
def _load(conn):
    ms = {r['id']: dict(r) for r in conn.execute(
        "SELECT id, kind, college_name, COALESCE(city,'') AS city, COALESCE(district,'') AS district, "
        "COALESCE(state,'') AS state, COALESCE(college_type,'') AS college_type FROM pg_college_master "
        "WHERE kind = 'medical'").fetchall()}
    for m in ms.values():
        m.update(names=[m['college_name']], aliases=[], cut={}, res={}, courses=0, favs=0)
    key2m = defaultdict(set)
    for a in conn.execute("SELECT id, master_id, alias_name, alias_key, alias_source, COALESCE(note,'') AS note "
                          "FROM pg_college_alias WHERE COALESCE(is_active,1)=1 ORDER BY id").fetchall():
        m = ms.get(a['master_id'])
        if not m:
            continue
        m['aliases'].append(dict(a))
        if a['alias_name'] not in m['names']:
            m['names'].append(a['alias_name'])
    for m in ms.values():
        for n in m['names']:
            key2m[norm(n)].add(m['id'])
    for c in conn.execute("SELECT institute, authority, COUNT(*) AS n FROM pg_cutoffs WHERE year=2025 "
                          "AND COALESCE(institute,'')<>'' GROUP BY institute, authority").fetchall():
        for mid in key2m.get(norm(c['institute']), ()):
            ms[mid]['cut'].setdefault(c['institute'], {})[c['authority'] or ''] = c['n']
    try:
        for r in conn.execute("SELECT institute, authority_code, COUNT(*) AS n FROM pg_results "
                              "WHERE COALESCE(institute,'')<>'' AND COALESCE(section,'')<>'dnb' "
                              "GROUP BY institute, authority_code").fetchall():
            for mid in key2m.get(norm(r['institute']), ()):
                ms[mid]['res'][(r['authority_code'] or '').upper()] = \
                    ms[mid]['res'].get((r['authority_code'] or '').upper(), 0) + r['n']
    except Exception:
        conn.rollback()
    for r in conn.execute("SELECT master_id, COUNT(*) AS n FROM pg_college_course GROUP BY master_id").fetchall():
        if r['master_id'] in ms:
            ms[r['master_id']]['courses'] = r['n']
    for r in conn.execute("SELECT master_id, COUNT(*) AS n FROM pg_college_favorites GROUP BY master_id").fetchall():
        if r['master_id'] in ms:
            ms[r['master_id']]['favs'] = r['n']
    return ms


def _pairs(conn, ms):
    from difflib import SequenceMatcher

    def nm(x):                                  # "Nizam's" = "Nizams"
        return norm(re.sub(r"['’`]", '', x or ''))
    loc = set()
    for m in ms.values():
        for f in ('city', 'district', 'state'):
            loc |= set(nm(m[f]).split())
    cache = {}

    def toks(x):
        if x not in cache:
            cache[x] = nm(x).split()
        return cache[x]

    def dcore(x):
        return {t for t in toks(x) if t not in GEN and t not in loc and t != 's'}

    def tmatch(a, b):                          # same word, allowing a small spelling slip
        return a == b or (len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a)
                                                            or SequenceMatcher(None, a, b).ratio() >= 0.85))

    def jac(da, db):
        hit_a = {x for x in da if any(tmatch(x, y) for y in db)}
        hit_b = {y for y in db if any(tmatch(x, y) for x in da)}
        union = len(da) + len(db) - min(len(hit_a), len(hit_b))
        return hit_a, (min(len(hit_a), len(hit_b)) / union if union else 0)

    def govtish(m):
        return any(t in GOVT for n in m['names'] for t in toks(n))

    def hosp_only(m):                          # a district / civil hospital, not a medical college
        n = nm(m['college_name']).split()
        return 'hospital' in n and not ({'college', 'institute', 'university', 'medical'} & set(n))

    def city(m):
        return ' '.join(toks(m['city']))

    def bad_city(m):
        c = city(m)
        return not c or c == ' '.join(toks(m['state'])) or 'prev' in c.split() or len(c) > 30

    core_c, close_c = {}, {}

    def core(x):
        if x not in core_c:
            core_c[x] = ' '.join(t for t in toks(x) if t not in GEN)
        return core_c[x]

    def close_names(a, b):                    # compare without the boiler-plate words (medical, college, …)
        k = (a['id'], b['id'])
        if k not in close_c:
            close_c[k] = max(SequenceMatcher(None, core(x), core(y)).ratio() for x in a['names'] for y in b['names'])
        return close_c[k]

    def same_place(a, b):
        ca, cb = city(a), city(b)
        if (bad_city(a) or bad_city(b)) and close_names(a, b) >= 0.8:
            return True
        if ca and cb and (ca == cb or (len(ca) >= 6 and SequenceMatcher(None, ca, cb).ratio() >= 0.88)):
            return True
        for x, y in ((a, b), (b, a)):            # "Saifai, Etawah": the other's town is written in this name
            cx = city(x)
            if cx and len(cx) >= 4 and any(f' {cx} ' in f' {nm(n)} ' for n in y['names']):
                return True
        return False

    decided = {(r['a_id'], r['b_id']) for r in conn.execute(
        "SELECT a_id, b_id FROM pg_college_pair_decision").fetchall()}
    by_state = defaultdict(list)
    for m in ms.values():
        by_state[_nstate(m['state'])].append(m)
    out = []
    for group in by_state.values():
        for a, b in combinations(sorted(group, key=lambda m: m['id']), 2):
            if (a['id'], b['id']) in decided or not same_place(a, b):     # different towns: skip early (speed)
                continue
            best, why = 0.0, ''
            for x in a['names']:
                for y in b['names']:
                    dx, dy = dcore(x), dcore(y)
                    if dx and dy:
                        hit, j = jac(dx, dy)
                        if j > best:
                            best, why = j, 'same name words: ' + ', '.join(sorted(hit))
                    elif not dx and not dy and 0.6 > best:
                        best, why = 0.6, 'both named only by place'
            if best < 0.9 and close_names(a, b) >= 0.8:
                da = set().union(*(dcore(x) for x in a['names'])); db = set().union(*(dcore(y) for y in b['names']))
                clash = (da and db and not jac(da, db)[0]) or ((not da or not db) and govtish(a) != govtish(b))
                if not clash:
                    best, why = 0.9, 'nearly the same name'
            if best < 0.5:
                continue
            if why.startswith('both named') and not (govtish(a) or govtish(b)):
                continue
            ac, bc = bool(a['cut']), bool(b['cut'])
            split = (ac and not bc and b['res']) or (bc and not ac and a['res'])
            mixed = hosp_only(a) != hosp_only(b)
            aa = {au for d in a['cut'].values() for au in d}
            ba = {au for d in b['cut'].values() for au in d}
            two_lists = ac and bc and not (aa & ba)     # e.g. the state list spells it one way, MCC another
            prio = 3 if mixed else 2 if two_lists else 3 if (ac and bc) else 1 if split else 2 if ac != bc else 3
            if two_lists:
                why += ' · 2025: one spelling in ' + '/'.join(sorted(aa)) + ', the other in ' + '/'.join(sorted(ba))
            if mixed:
                why += ' · one is a hospital, the other a medical college'
            keep = a if (ac and not bc) or (ac == bc and (len(a['res']) + a['courses']) >= (len(b['res']) + b['courses'])) else b
            out.append({'a': a, 'b': b, 'score': round(best, 2), 'why': why, 'prio': prio,
                        'keep': keep['id'], 'both_cut': ac and bc and not two_lists})
    out.sort(key=lambda p: (p['prio'], -p['score'], p['a']['state'], p['a']['college_name']))
    return out


def _wrong_links(ms):
    """Colleges holding 2+ different 2025 cut-off spellings — usually the same college printed two ways
    (state vs MCC), but sometimes a different college's name got attached here."""
    out = []
    for m in ms.values():
        if len(m['cut']) > 1:
            out.append(m)
    out.sort(key=lambda m: (m['state'], m['college_name']))
    return out


# ── review page ──────────────────────────────────────────────────────────────
@login_required
def college_merge_page():
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    show = (request.args.get('show') or 'pairs').strip()
    conn = get_db()
    pairs, links, log, ms = [], [], [], {}
    try:
        ver = tuple(conn.execute(
            "SELECT (SELECT COALESCE(MAX(id),0) FROM pg_college_merge_log) AS a, "
            "(SELECT COALESCE(MAX(id),0) FROM pg_college_pair_decision) AS b, "
            "(SELECT COUNT(*) FROM pg_college_alias) AS c, (SELECT COUNT(*) FROM pg_college_master) AS d").fetchone().values())
        hit = _CACHE.get('ver') == ver and time.time() - _CACHE.get('at', 0) < 900
        ms = _CACHE['ms'] if hit else _load(conn)
        if show == 'pairs':
            pairs = _CACHE['pairs'] if hit and _CACHE.get('pairs') is not None else _pairs(conn, ms)
            _CACHE.update(ver=ver, at=time.time(), ms=ms, pairs=pairs)
        elif show == 'links':
            links = _wrong_links(ms)
        log = [dict(r) for r in conn.execute(
            "SELECT id, keep_id, dup_id, keep_name, dup_name, action, done_by, done_at FROM pg_college_merge_log "
            "ORDER BY id DESC LIMIT 200").fetchall()]
        nd = [dict(r) for r in conn.execute(
            "SELECT a_id, b_id, decided_by, decided_at FROM pg_college_pair_decision ORDER BY id DESC LIMIT 200"
        ).fetchall()]
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("college_merge_page: %s", e)
        flash(f'Could not load the review list: {e}', 'error')
        nd = []
    finally:
        conn.close()
    all_names = sorted((m['college_name'], m['id'], m['state']) for m in ms.values())
    return render_template('pg_admin/college_merge.html', show=show, pairs=pairs, links=links, log=log,
                           not_same=nd, ms=ms, all_names=all_names, active_section='goocampus_in')


# ── merge ────────────────────────────────────────────────────────────────────
def _std_name(conn, mid):
    r = conn.execute("SELECT alias_name FROM pg_college_alias WHERE master_id=? AND alias_source='cutoff' "
                     "AND COALESCE(is_active,1)=1 ORDER BY id LIMIT 1", [mid]).fetchone()
    if r:
        return r['alias_name']
    r = conn.execute("SELECT college_name FROM pg_college_master WHERE id=?", [mid]).fetchone()
    return r['college_name'] if r else ''


def _names(conn, mid):
    m = conn.execute("SELECT college_name FROM pg_college_master WHERE id=?", [mid]).fetchone()
    out = [m['college_name']] if m else []
    for r in conn.execute("SELECT alias_name FROM pg_college_alias WHERE master_id=? AND COALESCE(is_active,1)=1",
                          [mid]).fetchall():
        if r['alias_name'] not in out:
            out.append(r['alias_name'])
    return out


def _has_col(conn, table, col):
    return bool(conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name=? AND column_name=?",
                             [table, col]).fetchone())


_ID_LINKS = [('pg_choice_items', 'master_id'), ('pg_users', 'mbbs_college_id'), ('pg_users', 'pg_college_id'),
             ('pg_pathway_profile', 'mbbs_college_id')]


def _merge(conn, keep, dup, who, dry):
    km = conn.execute("SELECT * FROM pg_college_master WHERE id=?", [keep]).fetchone()
    dm = conn.execute("SELECT * FROM pg_college_master WHERE id=?", [dup]).fetchone()
    if not km or not dm or keep == dup:
        raise ValueError('pick two different colleges')
    if km['kind'] == 'merged' or dm['kind'] == 'merged':
        raise ValueError('one of these colleges was already merged')
    if km['kind'] != dm['kind']:
        raise ValueError('a medical college and a DNB hospital cannot be merged')
    std_before = _std_name(conn, keep)
    dup_names = _names(conn, dup)
    c = {}

    def n(sql, p):
        return conn.execute(sql, p).fetchone()['n']
    c['aliases_moved'] = n("SELECT COUNT(*) AS n FROM pg_college_alias WHERE master_id=?", [dup])
    c['courses_moved'] = n(
        "SELECT COUNT(*) AS n FROM pg_college_course d WHERE d.master_id=? AND NOT EXISTS (SELECT 1 FROM "
        "pg_college_course k WHERE k.master_id=? AND lower(COALESCE(k.course,''))=lower(COALESCE(d.course,'')) "
        "AND COALESCE(k.course_category,'')=COALESCE(d.course_category,''))", [dup, keep])
    c['courses_already_there'] = n("SELECT COUNT(*) AS n FROM pg_college_course WHERE master_id=?", [dup]) - c['courses_moved']
    c['favourites_moved'] = n(
        "SELECT COUNT(*) AS n FROM pg_college_favorites d WHERE d.master_id=? AND NOT EXISTS (SELECT 1 FROM "
        "pg_college_favorites k WHERE k.master_id=? AND k.user_id=d.user_id)", [dup, keep])
    links = [(t, col) for t, col in _ID_LINKS if _has_col(conn, t, col)]
    for t, col in links:
        c[f'{t}.{col}'] = n(f"SELECT COUNT(*) AS n FROM {t} WHERE {col}=?", [dup])
    # the kept college's standard name AFTER the merge (its first 2025 cut-off spelling)
    if dry:
        std_after = std_before
        if not conn.execute("SELECT 1 FROM pg_college_alias WHERE master_id=? AND alias_source='cutoff' "
                            "AND COALESCE(is_active,1)=1", [keep]).fetchone():
            r = conn.execute("SELECT alias_name FROM pg_college_alias WHERE master_id=? AND alias_source='cutoff' "
                             "AND COALESCE(is_active,1)=1 ORDER BY id LIMIT 1", [dup]).fetchone()
            std_after = r['alias_name'] if r else std_before
    old = [x for x in dup_names + [std_before]]
    cut_names = {r['institute'] for r in conn.execute(
        "SELECT DISTINCT institute FROM pg_cutoffs WHERE institute = ANY(?)", [old]).fetchall()}
    c['results_2026_rows'] = n("SELECT COUNT(*) AS n FROM pg_results WHERE institute = ANY(?)", [dup_names])
    c['name_memory_rows'] = n("SELECT COUNT(*) AS n FROM pg_name_memory WHERE kind='college' AND std_name = ANY(?)",
                              [dup_names])
    sm_names = [x for x in dup_names if x not in cut_names]
    c['seat_matrix_rows'] = n("SELECT COUNT(*) AS n FROM pg_seat_matrix WHERE cutoff_institute = ANY(?)", [sm_names]) \
        if sm_names else 0
    dup_cut = [x for x in dup_names if x in cut_names]       # 2025 cut-off spellings that now link to the kept college
    c['cutoffs_2025_names'] = dup_cut
    c['cutoffs_2025_rows_linked'] = n("SELECT COUNT(*) AS n FROM pg_cutoffs WHERE institute = ANY(?)",
                                      [dup_cut]) if dup_cut else 0
    if dry:
        c['std_after'] = std_after
        return c
    note = f"from #{dup} ({dm['college_name']}) merged by {who}"
    conn.execute("UPDATE pg_college_alias SET master_id=?, alias_source=CASE WHEN alias_source='canonical' "
                 "THEN 'variant' ELSE alias_source END, note=TRIM(COALESCE(note,'') || ' ' || ?) WHERE master_id=?",
                 [keep, note, dup])
    if not conn.execute("SELECT 1 FROM pg_college_alias WHERE master_id=? AND alias_key=?",
                        [keep, norm(dm['college_name'])]).fetchone():
        conn.execute("INSERT INTO pg_college_alias (master_id, alias_name, alias_key, alias_source, note) "
                     "VALUES (?,?,?,?,?)", [keep, dm['college_name'], norm(dm['college_name']), 'variant', note])
    conn.execute("UPDATE pg_college_course d SET master_id=? WHERE d.master_id=? AND NOT EXISTS (SELECT 1 FROM "
                 "pg_college_course k WHERE k.master_id=? AND lower(COALESCE(k.course,''))=lower(COALESCE(d.course,'')) "
                 "AND COALESCE(k.course_category,'')=COALESCE(d.course_category,''))", [keep, dup, keep])
    conn.execute("UPDATE pg_college_favorites d SET master_id=? WHERE d.master_id=? AND NOT EXISTS (SELECT 1 FROM "
                 "pg_college_favorites k WHERE k.master_id=? AND k.user_id=d.user_id)", [keep, dup, keep])
    for t, col in links:
        conn.execute(f"UPDATE {t} SET {col}=? WHERE {col}=?", [keep, dup])
    std_after = _std_name(conn, keep)
    old = [x for x in dup_names + [std_before] if x != std_after]
    conn.execute("UPDATE pg_results SET institute=? WHERE institute = ANY(?)", [std_after, old])
    conn.execute("UPDATE pg_name_memory SET std_name=? WHERE kind='college' AND std_name = ANY(?)", [std_after, old])
    sm_old = [x for x in old if x not in cut_names]
    if sm_old:
        conn.execute("UPDATE pg_seat_matrix SET cutoff_institute=? WHERE cutoff_institute = ANY(?)", [std_after, sm_old])
    conn.execute("UPDATE pg_college_master SET kind='merged', master_key=COALESCE(master_key,'') || '|merged#' || id::text "
                 "WHERE id=?", [dup])
    c['std_after'] = std_after
    snap = {k: (v if isinstance(v, (int, float, str, type(None))) else str(v)) for k, v in dict(dm).items()}
    conn.execute("INSERT INTO pg_college_merge_log (keep_id, dup_id, keep_name, dup_name, action, done_by, detail) "
                 "VALUES (?,?,?,?,?,?,?)", [keep, dup, km['college_name'], dm['college_name'], 'merge', who,
                                            json.dumps({'counts': c, 'dup_names': dup_names, 'std_before': std_before,
                                                        'dup_row': snap})])
    return c


@login_required
def college_merge_preview():
    if not _admin():
        return jsonify({'ok': False, 'error': 'admin only'}), 403
    conn = get_db()
    try:
        c = _merge(conn, int(request.args.get('keep') or 0), int(request.args.get('dup') or 0), '', dry=True)
        return jsonify({'ok': True, 'counts': c})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        return jsonify({'ok': False, 'error': str(e)})
    finally:
        conn.close()


@login_required
def college_merge_apply():
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    keep, dup = int(request.form.get('keep') or 0), int(request.form.get('dup') or 0)
    conn = get_db()
    try:
        c = _merge(conn, keep, dup, _who(u), dry=False)
        conn.commit()
        if request.headers.get('X-Requested-With') == 'fetch':
            return jsonify({'ok': True, 'keep': keep, 'dup': dup, 'counts': c})
        flash(f"Merged: #{dup} is now part of #{keep} ({c['std_after']}). Moved {c['aliases_moved']} names, "
              f"{c['courses_moved']} courses, {c['results_2026_rows']} 2026 result seats. Nothing was deleted.",
              'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("college_merge_apply: %s", e)
        if request.headers.get('X-Requested-With') == 'fetch':
            return jsonify({'ok': False, 'error': str(e)})
        flash(f'Merge failed — nothing changed: {e}', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_college_merge', show=request.form.get('show') or 'pairs'))


@login_required
def college_merge_not_same():
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    a, b = sorted([int(request.form.get('a') or 0), int(request.form.get('b') or 0)])
    conn = get_db()
    try:
        conn.execute("INSERT INTO pg_college_pair_decision (a_id, b_id, decision, decided_by) VALUES (?,?,?,?) "
                     "ON CONFLICT (a_id, b_id) DO NOTHING", [a, b, 'not_same', _who(u)])
        conn.commit()
        if request.headers.get('X-Requested-With') == 'fetch':
            return jsonify({'ok': True})
        flash('Saved: these are two different colleges — they will not be suggested again.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        flash(f'Could not save: {e}', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_college_merge', show='pairs'))


@login_required
def college_merge_move_alias():
    """A spelling is attached to the wrong college → attach it to the right one (or unlink it). Never deleted."""
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    aid = int(request.form.get('alias_id') or 0)
    target = request.form.get('target') or ''
    conn = get_db()
    try:
        a = conn.execute("SELECT * FROM pg_college_alias WHERE id=?", [aid]).fetchone()
        if not a:
            raise ValueError('name not found')
        if target.isdigit():
            t = conn.execute("SELECT id, college_name FROM pg_college_master WHERE id=? AND kind<>'merged'",
                             [int(target)]).fetchone()
            if not t:
                raise ValueError('college not found')
            conn.execute("UPDATE pg_college_alias SET master_id=?, note=TRIM(COALESCE(note,'') || ' ' || ?) WHERE id=?",
                         [t['id'], f"moved from #{a['master_id']} by {_who(u)}", aid])
            msg = f"Moved “{a['alias_name']}” to {t['college_name']}."
        else:
            conn.execute("UPDATE pg_college_alias SET is_active=0, note=TRIM(COALESCE(note,'') || ' ' || ?) WHERE id=?",
                         [f"unlinked from #{a['master_id']} by {_who(u)}", aid])
            msg = f"Unlinked “{a['alias_name']}” (kept on record, no longer attached)."
        conn.execute("INSERT INTO pg_college_merge_log (keep_id, dup_id, keep_name, dup_name, action, done_by, detail) "
                     "VALUES (?,?,?,?,?,?,?)", [int(target) if target.isdigit() else None, a['master_id'],
                                                '', a['alias_name'], 'move_alias', _who(u),
                                                json.dumps({'alias_id': aid, 'from': a['master_id'], 'to': target})])
        conn.commit()
        flash(msg, 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        flash(f'Could not move: {e}', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_college_merge', show='links'))
