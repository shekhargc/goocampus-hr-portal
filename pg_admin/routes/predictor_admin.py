"""Predictor Data admin — upload the NEET-PG closing-rank dataset that powers the
goocampus.in College Predictor.

Why this exists: the site shipped the 10 MB cut-off JSON inside its own repo, but
that file is .gitignored, so the deployed site never had it and the predictor fell
back to a tiny sample ("Preview mode"). goocampus.org is the backend for
goocampus.in, so the data belongs here — uploaded once a year by an admin instead
of committed into a front-end repo. (founder 2026-07-24)

Upload format: the same JSON the site used —
    {"year": 2025, "count": N, "rows": [{i,s,q,c,d,n,st,f,r1,r2,r3,r4,stray,sp,by,pen}, ...]}
Short keys are kept so the founder can upload the existing file unchanged.
"""
import json
import logging

from flask import request, redirect, url_for, flash, render_template
from core.auth import login_required
from core.users import get_user
from db import get_db

# Import in batches — 37k+ rows in one statement would blow the parameter limit.
_BATCH = 500

# Upload JSON key -> our column. Keeps the site's existing short-key format.
_FIELD_MAP = [
    ('i', 'institute'), ('s', 'authority'), ('q', 'quota'), ('c', 'category'),
    ('d', 'degree'), ('n', 'course'), ('st', 'state'),
    ('f', 'fee'), ('sp', 'stipend'), ('by', 'bond_years'), ('pen', 'penalty'),
    ('r1', 'r1'), ('r2', 'r2'), ('r3', 'r3'), ('r4', 'r4'), ('stray', 'stray'),
]


def _admin_only():
    user = get_user()
    return bool(user and user['is_admin']), user


def _num(v):
    """None-safe number: '' / None / junk -> None (never 0, which would be a lie)."""
    if v in (None, '', 'NA', 'N/A', '-'):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v):
    n = _num(v)
    return int(n) if n is not None else None


def _closing_rank(row):
    """The LAST round a seat was still available = the most generous closing rank,
    which is what 'is this within reach' should be judged against."""
    ranks = [_int(row.get(k)) for k in ('stray', 'r4', 'r3', 'r2', 'r1')]
    ranks = [r for r in ranks if r and r > 0]
    return max(ranks) if ranks else None


@login_required
def predictor_admin():
    """Show what's loaded + the upload form."""
    ok, _user = _admin_only()
    if not ok:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    conn = get_db()
    years, total, sample = [], 0, []
    try:
        years = [dict(r) for r in conn.execute(
            "SELECT year, COUNT(*) AS rows, MAX(created_at) AS loaded_at "
            "  FROM pg_cutoffs GROUP BY year ORDER BY year DESC").fetchall()]
        total = sum(y['rows'] for y in years)
        if total:
            sample = [dict(r) for r in conn.execute(
                "SELECT institute, course, category, authority, state, closing_rank "
                "  FROM pg_cutoffs ORDER BY id DESC LIMIT 5").fetchall()]
    except Exception as e:
        logging.error("predictor_admin: %s", e)
        flash(f'Could not read the dataset: {e}', 'error')
    finally:
        conn.close()
    return render_template('pg_admin/predictor.html', years=years, total=total,
                           sample=sample, active_section='goocampus_in')


@login_required
def predictor_upload():
    """Import a cut-off JSON. Replaces that YEAR only (never touches other years)."""
    ok, user = _admin_only()
    if not ok:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    f = request.files.get('data_file')
    if not f or not f.filename:
        flash('Choose a JSON file to upload.', 'error')
        return redirect(url_for('pg_predictor_admin'))
    try:
        payload = json.load(f.stream)
    except Exception as e:
        flash(f'That file is not valid JSON: {e}', 'error')
        return redirect(url_for('pg_predictor_admin'))

    rows = payload.get('rows') if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        flash('No "rows" found in the file.', 'error')
        return redirect(url_for('pg_predictor_admin'))
    try:
        year = int(payload.get('year') or request.form.get('year') or 0)
    except (TypeError, ValueError):
        year = 0
    if not year:
        flash('The file has no "year" — add one, or type it in the Year box.', 'error')
        return redirect(url_for('pg_predictor_admin'))

    cols = ['year'] + [c for _k, c in _FIELD_MAP] + ['closing_rank']
    placeholders = ','.join(['?'] * len(cols))
    sql = f"INSERT INTO pg_cutoffs ({','.join(cols)}) VALUES ({placeholders})"

    conn = get_db()
    inserted = skipped = 0
    try:
        # Replace this year only — re-uploading a corrected file is safe, and other
        # years (and everything else in the DB) are untouched.
        conn.execute("DELETE FROM pg_cutoffs WHERE year = ?", (year,))
        batch = []
        for r in rows:
            if not isinstance(r, dict):
                skipped += 1
                continue
            vals = [year]
            for key, col in _FIELD_MAP:
                v = r.get(key)
                if col in ('fee', 'stipend', 'bond_years', 'penalty'):
                    vals.append(_num(v))
                elif col in ('r1', 'r2', 'r3', 'r4', 'stray'):
                    vals.append(_int(v))
                else:
                    vals.append((str(v).strip() if v is not None else ''))
            vals.append(_closing_rank(r))
            batch.append(vals)
            if len(batch) >= _BATCH:
                conn.executemany(sql, batch)
                inserted += len(batch)
                batch = []
        if batch:
            conn.executemany(sql, batch)
            inserted += len(batch)
        conn.commit()
        flash(f'Loaded {inserted:,} rows for {year}'
              + (f' ({skipped} skipped)' if skipped else '') + '.', 'success')
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error("predictor_upload: %s", e)
        flash(f'Import failed — nothing was changed: {e}', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_predictor_admin'))
