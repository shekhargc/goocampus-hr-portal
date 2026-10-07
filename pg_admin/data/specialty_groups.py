"""Clinical / Para-clinical / Pre-clinical grouping of NEET-PG specialities (founder 2026-10-07).

Lets the College Predictor narrow an "any speciality" search to Clinical or Non-clinical
branches. Every course name in pg_cutoffs is grouped AUTOMATICALLY from its subject words;
an admin can override any course on /admin/pg/specialty-groups (stored in pg_course_branch).

Non-clinical = Para-clinical + Pre-clinical. A course the rules can't place stays
"unclassified" — it is excluded from BOTH filters (never guessed) and shown on the admin page
for a decision. Purely additive: the predictor behaves exactly as before unless the optional
`branch` parameter is sent.
"""
import re
import logging

from db import get_db

GROUPS = ('clinical', 'para_clinical', 'pre_clinical', 'non_clinical')
GROUP_LABELS = {'clinical': 'Clinical', 'para_clinical': 'Para-clinical',
                'pre_clinical': 'Pre-clinical', 'non_clinical': 'Non-clinical', '': 'Unclassified'}
# What the public `branch` parameter accepts → which groups it covers. 'non_clinical' (a
# group of its own) = the cut-off file said Non-clinical without saying para/pre.
BRANCH_PARAMS = {
    'clinical': ('clinical',),
    'non_clinical': ('para_clinical', 'pre_clinical', 'non_clinical'),
    'para_clinical': ('para_clinical',),
    'pre_clinical': ('pre_clinical',),
}
NON_CLINICAL = ('para_clinical', 'pre_clinical', 'non_clinical')

# Checked IN ORDER: pre-clinical → para-clinical → clinical. Order matters — e.g.
# "Community Medicine" / "Forensic Medicine" must hit para before the generic "medicine".
_RULES = [
    ('pre_clinical', [r'\banatomy\b', r'\bphysiology\b', r'\bbio ?chemistry\b']),
    ('para_clinical', [
        r'\bpathology\b', r'\bmicro ?biology\b', r'\bpharmacology\b', r'\bforensic\b',
        r'\bcommunity medicine\b', r'\bcommunity health\b', r'\bsocial (and )?preventive\b',
        r'\bpreventive (and )?social\b', r'\bpsm\b', r'\bspm\b',
        r'\bimmuno ?h(a)?ematology\b', r'\bblood transfusion\b', r'\btransfusion medicine\b',
        r'\blaboratory medicine\b', r'\blab medicine\b', r'\bhospital administration\b',
        r'\baerospace\b', r'\baviation medicine\b', r'\belectromyography\b',
        r'\bclinical pathology\b', r'\bdcp\b', r'\bhealth administration\b', r'\bpublic health\b', r'\bbacteriolog', r'\bepidemiolog', r'\bmph\b',
    ]),
    ('clinical', [
        r'\ban(a)?esth', r'\bdermatolog', r'\bvenereolog', r'\bemergency\b', r'\bfamily medicine\b',
        r'\bgeneral medicine\b', r'\binternal medicine\b', r'\bgeriatric', r'\bnuclear medicine\b',
        r'\bp(a)?ediatric', r'\bchild health\b', r'\bneonatolog', r'\bpalliative\b',
        r'\bphysical medicine\b', r'\brehabilitation\b', r'\bpsychiatr', r'\bradiation oncology\b',
        r'\bradio ?therapy\b', r'\bradio ?diagnosis\b', r'\bradiology\b', r'\brespiratory\b',
        r'\btuberculosis\b', r'\bchest\b', r'\bpulmonary\b', r'\bsports medicine\b', r'\btropical\b',
        r'\bent\b', r'\boto ?rhino', r'\botorhinolaryngology\b', r'\bsurgery\b', r'\bsurgical\b',
        r'\bobstetric', r'\bgyna?e?colog', r'\bobg\b', r'\bophthalm', r'\borthop', r'\btrauma',
        r'\bmaternal\b', r'\bvenereology\b', r'\bleprosy\b', r'\be n t\b', r'\bobst\b',
        r'\bgyna?e\b', r'\bgyn\b', r'\bdiabetolog', r'\bultrasonograph', r'\bsonolog', r'\bmedicine\b',
    ]),
]
# Common Indian PG diploma / degree acronyms (dots stripped: "D.M.R.D." → "dmrd").
_ACRONYMS = {
    'clinical': {'dgo', 'dmrd', 'dmrt', 'dmre', 'dpm', 'dch', 'dlo', 'doms', 'do', 'da', 'dortho',
                 'dtcd', 'dtd', 'ddvl', 'dvd', 'dvl', 'dpmr', 'dem'},
    'para_clinical': {'dcp', 'dph', 'dfm', 'dpath', 'dipath'},
}
_COMPILED = [(g, [re.compile(p) for p in pats]) for g, pats in _RULES]


def course_key(course):
    """Normalised key: lowercase, punctuation → space, collapsed."""
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', str(course or '').lower()).split())


def classify(course):
    """Auto group for a course name, or '' when no rule is confident."""
    k = course_key(course)
    if not k:
        return ''
    compact = k.replace(' ', '')
    for group, acr in _ACRONYMS.items():          # whole-name acronyms only (never substrings)
        if compact in acr:
            return group
    for group, pats in _COMPILED:
        if any(p.search(k) for p in pats):
            return group
    return ''


def ensure_course_branch_table(conn=None):
    own = conn is None
    if own:
        conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_course_branch (
            course_key TEXT PRIMARY KEY,
            course_label TEXT DEFAULT '',
            branch_group TEXT DEFAULT '',
            updated_by TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_course_branch_log (
            id SERIAL PRIMARY KEY,
            course_key TEXT, old_group TEXT, new_group TEXT,
            changed_by TEXT DEFAULT '', changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()
    except Exception as e:
        logging.error("ensure_course_branch_table: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        if own:
            try: conn.close()
            except Exception: pass


def overrides(conn):
    """{course_key: branch_group} set by an admin."""
    out = {}
    try:
        for r in conn.execute("SELECT course_key, branch_group FROM pg_course_branch").fetchall():
            out[r['course_key']] = r['branch_group'] or ''
    except Exception as e:
        logging.warning("specialty overrides: %s", e)
        try: conn.rollback()
        except Exception: pass
    return out


def file_type_group(v):
    """Cut-off file's course_type text → group ('' if it isn't a clinical-type value)."""
    t = re.sub(r'[^a-z]', '', str(v or '').lower())
    return {'clinical': 'clinical', 'nonclinical': 'non_clinical', 'paraclinical': 'para_clinical',
            'preclinical': 'pre_clinical'}.get(t, '')


def file_types(conn, year=None):
    """{course_key: {'group', 'raw', 'mixed'}} — the MAJORITY course_type the uploaded cut-off
    file gives each course (optionally for one year). 'mixed' flags inconsistent rows."""
    out = {}
    try:
        sql = ("SELECT course, course_type, COUNT(*) AS n FROM pg_cutoffs "
               "WHERE COALESCE(course,'') <> '' AND COALESCE(course_type,'') <> '' ")
        params = []
        if year:
            sql += "AND year = ? "; params.append(year)
        sql += "GROUP BY course, course_type"
        agg = {}
        for r in conn.execute(sql, params).fetchall():
            g = file_type_group(r['course_type'])
            if not g:
                continue
            k = course_key(r['course'])
            d = agg.setdefault(k, {})
            d[(g, str(r['course_type']).strip())] = d.get((g, str(r['course_type']).strip()), 0) + int(r['n'])
        for k, d in agg.items():
            (g, raw), _n = max(d.items(), key=lambda kv: kv[1])
            out[k] = {'group': g, 'raw': raw, 'mixed': len({gg for gg, _ in d}) > 1}
    except Exception as e:
        logging.warning("specialty file_types: %s", e)
        try: conn.rollback()
        except Exception: pass
    return out


def context(conn, year=None):
    """Everything group_of needs, loaded once per request."""
    return {'ovr': overrides(conn), 'file': file_types(conn, year)}


def group_source(course, ctx):
    """→ (group, source) with source in admin | file | rule | ''.
    Precedence: admin override > cut-off file's course_type > name rules. When the file only
    says 'Non-clinical', the rules may refine it to para/pre — never flip it to clinical."""
    k = course_key(course)
    if k in ctx['ovr']:
        return ctx['ovr'][k], 'admin'
    f = ctx['file'].get(k)
    if f:
        if f['group'] == 'non_clinical':
            r = classify(course)
            return (r if r in ('para_clinical', 'pre_clinical') else 'non_clinical'), 'file'
        return f['group'], 'file'
    r = classify(course)
    return r, ('rule' if r else '')


def group_of(course, ctx):
    return group_source(course, ctx)[0]


def courses_in_branch(conn, year, branch, ctx=None):
    """Exact pg_cutoffs course strings (for `year`) whose effective group falls in `branch`."""
    want = BRANCH_PARAMS.get(branch)
    if not want:
        return None
    ctx = ctx or context(conn, year)
    rows = conn.execute("SELECT DISTINCT course FROM pg_cutoffs WHERE year = ? "
                        "AND COALESCE(course,'') <> ''", (year,)).fetchall()
    return [r['course'] for r in rows if group_of(r['course'], ctx) in want]
