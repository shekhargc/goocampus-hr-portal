"""Official PDFs too big to keep inside the database live in R2 storage (founder 2026-10-17:
EVERY authority PDF — brochures, merit lists, results, seat matrices, fee structures — must be
archived, whatever its size, because the authority sites delete them later; e.g. Maharashtra's
NEET-PG 2026 information brochure is 128 MB).

The office Mac uploads a big file straight to R2 (signed PUT link from /api/pg/news-inbox/upload-url)
and the row keeps only the R2 object key. Every file endpoint that finds a key instead of bytes
redirects to a short-lived signed R2 link.
"""
import logging
import re

from flask import redirect

INLINE_MAX = 20 * 1024 * 1024        # up to this size the PDF is still stored in the database

_READY = False


def ensure_cols(conn):
    """Add the R2-key columns (once per process; request-time so a cold-start skip can't bite)."""
    global _READY
    if _READY:
        return
    try:
        for table, cols in (('pg_news_inbox', ('pdf_r2_key TEXT', 'pdf_size BIGINT', 'pdf_sha256 TEXT')),
                            ('pg_news', ('pdf_r2_key TEXT',)),
                            ('pg_authority_docs', ('file_r2_key TEXT',))):
            for c in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {c}")
        conn.commit()
        _READY = True
    except Exception as e:
        logging.warning("big_files ensure: %s", e)
        try: conn.rollback()
        except Exception: pass


def make_key(authority_code, sha256, name):
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', name or 'notice.pdf').strip('_')[-80:] or 'notice.pdf'
    return f"authority-pdfs/{re.sub(r'[^a-z0-9_]+', '_', (authority_code or 'other').lower())}/{(sha256 or 'x')[:16]}-{safe}"


def r2_redirect(key):
    """302 to a signed R2 link for this object, or None if storage isn't available."""
    if not key:
        return None
    from core import storage
    url = storage.presigned_get_url(key, ttl_seconds=900)
    return redirect(url, code=302) if url else None
