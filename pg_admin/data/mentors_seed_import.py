"""One-time (re-runnable) importer that loads the mentors scraped from the live site
(goocampusworld.com) into pg_mentors, and migrates each profile photo from the old
S3 bucket into our own R2.

# Pathway country inferred from the mentor's topic where it is unambiguous
# (PLAB -> UK, AMC -> Australia, USMLE -> USA...). Only ~40 of 160 can be derived
# this way; the rest stay blank for the team to set in the admin, rather than
# guessing a country onto a real person's profile. (founder 2026-07-28)
_COUNTRY_HINTS = [
    ('plab', 'UK'), ('mrcp', 'UK'), ('mrcs', 'UK'), ('nhs', 'UK'), ('united kingdom', 'UK'),
    ('amc', 'Australia'), ('austral', 'Australia'),
    ('usmle', 'USA'), ('united states', 'USA'),
    ('mccqe', 'Canada'), ('canada', 'Canada'),
    ('ireland', 'Ireland'), ('rcsi', 'Ireland'),
    ('new zealand', 'New Zealand'), ('nzrex', 'New Zealand'),
    ('germany', 'Germany'), ('fsp', 'Germany'),
]


def _infer_country(*texts):
    blob = ' '.join((t or '') for t in texts).lower()
    for frag, country in _COUNTRY_HINTS:
        if frag in blob:
            return country
    return ''


Design notes
------------
- **Idempotent** on (source, external_id): re-running updates the SOURCE-derived content
  fields (name, bio, fee, specialties, …) but NEVER touches admin-controlled flags
  (is_published / is_verified / is_available / admin_notes) — so a staff member's
  publish/verify decisions survive a re-import.
- **Images** are pulled from S3 and pushed to R2 only once (skipped when photo_url is
  already an R2 key), so re-imports are cheap. Runs only where R2 is configured
  (i.e. on the server), and degrades gracefully to "no image" locally.
- Triggered by an explicit admin action — NOT at boot — so it never writes to the
  shared live DB uncontrolled.
"""
import os
import json
import logging

# The source-derived content columns refreshed on every import (id/flags excluded).
_CONTENT_COLS = [
    'mentor_type', 'name', 'designation', 'specialization', 'qualification',
    'experience_years', 'experience_range', 'specialties', 'languages', 'bio',
    'awards', 'certifications', 'counselling_fee', 'rating', 'reviews_count',
    'total_mentees', 'mentorship_hours', 'source_photo_url', 'profile_source_url',
]


def _seed_path():
    return os.path.join(os.path.dirname(__file__), 'mentors_seed.json')


def load_seed():
    with open(_seed_path(), 'r', encoding='utf-8') as fh:
        return json.load(fh)


def _row_values(m):
    """Map a seed dict to the ordered tuple for _CONTENT_COLS (JSON-encode list cols)."""
    return (
        (m.get('mentor_type') or 'specialist'),
        (m.get('name') or ''),
        (m.get('designation') or ''),
        (m.get('specialization') or ''),
        (m.get('qualification') or ''),
        m.get('experience_years'),
        (m.get('experience_range') or ''),
        json.dumps(m.get('specialties') or []),
        json.dumps(m.get('languages') or []),
        (m.get('bio') or ''),
        (m.get('awards') or ''),
        (m.get('certifications') or ''),
        m.get('counselling_fee'),
        (m.get('rating') or 0),
        (m.get('reviews_count') or 0),
        (m.get('total_mentees') or ''),
        (m.get('mentorship_hours') or ''),
        (m.get('source_photo_url') or ''),
        (m.get('profile_source_url') or ''),
    )


def _migrate_photo(conn, mentor_id, source_url, current_photo):
    """Download the S3 photo and upload to R2; set photo_url to the R2 key.
    Returns 'migrated' / 'skipped' / 'failed'. Idempotent: skips if already an R2 key."""
    if not source_url:
        return 'skipped'
    if current_photo and current_photo.startswith('pg_mentors/'):
        return 'skipped'  # already migrated
    try:
        from core import storage
    except Exception:
        return 'failed'
    if not storage.is_configured():
        return 'skipped'  # no R2 here (e.g. local dev) — leave source_photo_url for later
    try:
        import requests
        resp = requests.get(source_url, timeout=30)
        if resp.status_code != 200 or not resp.content:
            return 'failed'
        ctype = resp.headers.get('Content-Type', 'image/jpeg').split(';')[0]
        ext = {'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/png': 'png',
               'image/webp': 'webp', 'image/gif': 'gif'}.get(ctype.lower(), 'jpg')
        key = f"pg_mentors/{mentor_id}/photo.{ext}"
        if not storage.upload_bytes(key, resp.content, content_type=ctype):
            return 'failed'
        conn.execute("UPDATE pg_mentors SET photo_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (key, mentor_id))
        conn.commit()
        return 'migrated'
    except Exception as e:
        logging.error("mentor image migrate (id=%s): %s", mentor_id, e)
        try:
            conn.rollback()
        except Exception:
            pass
        return 'failed'


def import_mentors_from_seed(conn, created_by=None, do_images=True, publish=True):
    """Upsert every seed mentor. Returns a summary dict.

    `publish=True` marks NEW rows published (they are already public on the old site);
    existing rows keep whatever publish/verify/available state admins have set.
    """
    seed = load_seed()
    set_clause = ", ".join(f"{c} = ?" for c in _CONTENT_COLS)
    insert_cols = _CONTENT_COLS + ['source', 'external_id', 'is_published', 'is_active',
                                   'is_available', 'is_verified', 'service_type', 'created_by', 'updated_by']
    placeholders = ", ".join(["?"] * len(insert_cols))

    created = updated = 0
    imgs = {'migrated': 0, 'skipped': 0, 'failed': 0}
    errors = []

    for m in seed:
        src = m.get('source') or 'goocampusworld.com'
        ext_id = str(m.get('external_id') or '')
        if not ext_id:
            continue
        try:
            existing = conn.execute(
                "SELECT id, photo_url FROM pg_mentors WHERE source = ? AND external_id = ?",
                (src, ext_id)).fetchone()
            vals = _row_values(m)
            if existing:
                mentor_id = existing['id']
                conn.execute(
                    f"UPDATE pg_mentors SET {set_clause}, updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    list(vals) + [created_by, mentor_id])
                conn.commit()
                updated += 1
                cur_photo = existing['photo_url']
            else:
                row = conn.execute(
                    f"INSERT INTO pg_mentors ({', '.join(insert_cols)}) VALUES ({placeholders}) RETURNING id",
                    list(vals) + [src, ext_id, bool(publish), True, True, False, 'counselling', created_by, created_by]
                ).fetchone()
                conn.commit()
                mentor_id = row['id'] if row else None
                created += 1
                cur_photo = ''
            if do_images and mentor_id:
                imgs[_migrate_photo(conn, mentor_id, m.get('source_photo_url') or '', cur_photo)] += 1
        except Exception as e:
            logging.error("import mentor ext_id=%s: %s", ext_id, e)
            try:
                conn.rollback()
            except Exception:
                pass
            errors.append(ext_id)

    return {'created': created, 'updated': updated, 'total_seed': len(seed),
            'images': imgs, 'errors': errors}
