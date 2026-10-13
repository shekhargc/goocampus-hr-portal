"""Main bulletins per counselling authority (founder 2026-10-13, option B): up to MAX_MAIN of the
authority's own brochures can be "main", each with a short label (e.g. Tamil Nadu "Government quota"
+ "Management / NRI quota"; MCC "Information Bulletin" + "User Guide"). The website shows one
bulletin button per main brochure. A single college's own bulletin is never main.
"""
import re

MAX_MAIN = 3
LABEL_SUGGESTIONS = ['Information Bulletin', 'Government quota', 'Management / NRI quota', 'User Guide',
                     'Prospectus']


def ensure_cols(conn):
    conn.execute("ALTER TABLE pg_authority_docs ADD COLUMN IF NOT EXISTS main_label TEXT DEFAULT ''")


def guess_label(title):
    t = (title or '').lower()
    if re.search(r'user\s*(guide|manual)', t):
        return 'User Guide'
    if re.search(r'management|nri|minority', t):
        return 'Management / NRI quota'
    if re.search(r'government|\bgq\b|competent|convener|\bcq\b', t):
        return 'Government quota'
    if 'prospectus' in t:
        return 'Prospectus'
    return 'Information Bulletin'


def main_count(conn, code, exclude_id=None):
    r = conn.execute("SELECT COUNT(*) AS n FROM pg_authority_docs WHERE authority_code = ? AND category = 'brochure' "
                     "AND COALESCE(is_main, FALSE) AND id <> ?", (code, exclude_id or 0)).fetchone()
    return int(r['n'] or 0)


def set_main(conn, doc_id, on=True, label=None):
    """Mark / unmark one brochure as a main bulletin. Returns (ok, message). Caller commits."""
    ensure_cols(conn)
    r = conn.execute("SELECT id, authority_code, category, title, COALESCE(is_main,FALSE) AS is_main, "
                     "COALESCE(main_label,'') AS main_label FROM pg_authority_docs WHERE id = ?", (doc_id,)).fetchone()
    if not r:
        return False, 'Document not found.'
    if not on:
        conn.execute("UPDATE pg_authority_docs SET is_main = FALSE, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (doc_id,))
        return True, 'No longer a main bulletin.'
    if r['category'] != 'brochure':
        return False, 'Only documents under "Counselling Brochure / Bulletin / User Manual" can be a main bulletin.'
    if not r['is_main'] and main_count(conn, r['authority_code'], doc_id) >= MAX_MAIN:
        return False, f'This authority already has {MAX_MAIN} main bulletins — remove one first.'
    lab = (label if label is not None else (r['main_label'] or guess_label(r['title']))).strip()[:40]
    conn.execute("UPDATE pg_authority_docs SET is_main = TRUE, main_label = ?, updated_at = CURRENT_TIMESTAMP "
                 "WHERE id = ?", (lab or guess_label(r['title']), doc_id))
    return True, f'Main bulletin: “{lab or guess_label(r["title"])}”.'
