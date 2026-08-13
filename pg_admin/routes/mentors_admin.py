"""Admin Mentor Management screen (goocampus.org staff). True-admin gated — this
section isn't wired into Access Master yet, so we restrict to is_admin exactly like
the NEET-PG PDF admin does.

Two mentor types are managed separately (Specialist vs Peer-to-Peer) via tabs.
CRUD every pg_mentors field + publish/verify/available toggles + photo upload to R2
+ a rich detail view + a one-click import of the goocampusworld.com dataset.
"""
import io
import json
import logging
from flask import (render_template, request, session, redirect, url_for, flash,
                   abort)
from db import get_db
from core.auth import login_required
from core.users import get_user
from core import storage
from pg_admin.utils import as_list, as_dict

_WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday',
             'friday', 'saturday', 'sunday']
_SERVICE_TYPES = ('consultation', 'counselling', 'both')
_MENTOR_TYPES = ('specialist', 'peer_to_peer')
_MENTOR_TYPE_LABELS = {'specialist': 'Specialist', 'peer_to_peer': 'Peer-to-Peer'}
_ALLOWED_IMG = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}


def _require_admin():
    user = get_user()
    if not user or not user.get('is_admin'):
        return None
    return user


def _parse_csv_list(raw):
    out, seen = [], set()
    for part in (raw or '').split(','):
        s = part.strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def _parse_availability(form):
    avail = {}
    for day in _WEEKDAYS:
        start = (form.get(f'avail_{day}_start') or '').strip()
        end = (form.get(f'avail_{day}_end') or '').strip()
        if start and end:
            avail[day] = [{'start': start, 'end': end}]
    return avail


def _num_or_none(raw):
    raw = (raw or '').strip()
    if raw == '':
        return None
    try:
        return float(raw)
    except Exception:
        return None


def _int_or_none(raw):
    raw = (raw or '').strip()
    if raw == '':
        return None
    try:
        return int(float(raw))
    except Exception:
        return None


@login_required
def mentors_admin():
    """List + filter mentors (per type), with stat cards, and render the CRUD screen."""
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))

    mtype = (request.args.get('type') or 'specialist').strip()
    if mtype not in _MENTOR_TYPES and mtype != 'all':
        mtype = 'specialist'
    q = (request.args.get('q') or '').strip()
    f_spec = (request.args.get('specialization') or '').strip()
    f_pub = (request.args.get('published') or '').strip()
    f_avail = (request.args.get('available') or '').strip()
    f_country = (request.args.get('country') or '').strip()

    conds = ["is_active"]
    params = []
    if mtype != 'all':
        conds.append("mentor_type = ?")
        params.append(mtype)
    if q:
        conds.append("(name ILIKE ? OR specialization ILIKE ? OR qualification ILIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    if f_spec:
        conds.append("specialization = ?")
        params.append(f_spec)
    if f_pub == 'true':
        conds.append("is_published")
    elif f_pub == 'false':
        conds.append("NOT is_published")
    if f_country:
        conds.append("country = ?")
        params.append(f_country)
    if f_avail == 'true':
        conds.append("is_available")
    elif f_avail == 'false':
        conds.append("NOT is_available")
    where = " AND ".join(conds)

    conn = get_db()
    try:
        mentors = conn.execute(
            f"SELECT * FROM pg_mentors WHERE {where} ORDER BY updated_at DESC, id DESC",
            params
        ).fetchall()

        def _cnt(extra_sql='', extra=()):
            return conn.execute(
                "SELECT COUNT(*) AS c FROM pg_mentors WHERE is_active" + extra_sql, extra
            ).fetchone()['c']

        # Tab counts per mentor_type
        type_counts = {t: _cnt(" AND mentor_type = ?", (t,)) for t in _MENTOR_TYPES}
        type_counts['all'] = _cnt()

        # Stat cards scoped to the active tab
        scope_sql = "" if mtype == 'all' else " AND mentor_type = ?"
        scope = () if mtype == 'all' else (mtype,)
        stats = {
            'total': _cnt(scope_sql, scope),
            'published': _cnt(scope_sql + " AND is_published", scope),
            'available': _cnt(scope_sql + " AND is_available", scope),
            'verified': _cnt(scope_sql + " AND is_verified", scope),
        }
        spec_rows = conn.execute(
            "SELECT DISTINCT specialization FROM pg_mentors "
            "WHERE is_active AND specialization <> '' ORDER BY specialization"
        ).fetchall()
        specializations = [r['specialization'] for r in spec_rows]
        countries = [r['country'] for r in conn.execute(
            "SELECT DISTINCT country FROM pg_mentors "
            "WHERE is_active AND COALESCE(country,'') <> '' ORDER BY country").fetchall()]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error("mentors_admin: %s", e)
        mentors, specializations, countries = [], [], []
        type_counts = {t: 0 for t in _MENTOR_TYPES}; type_counts['all'] = 0
        stats = {'total': 0, 'published': 0, 'available': 0, 'verified': 0}
    finally:
        try:
            conn.close()
        except Exception:
            pass

    view = []
    for m in mentors:
        d = dict(m)
        d['specialties_list'] = as_list(m.get('specialties'))
        d['languages_list'] = as_list(m.get('languages'))
        d['availability_map'] = as_dict(m.get('availability'))
        view.append(d)

    return render_template('pg_admin/mentors.html',
                           user=user, mentors=view, stats=stats,
                           specializations=specializations, weekdays=_WEEKDAYS,
                           service_types=_SERVICE_TYPES, mentor_types=_MENTOR_TYPES,
                           mentor_type_labels=_MENTOR_TYPE_LABELS,
                           active_type=mtype, type_counts=type_counts,
                           q=q, f_spec=f_spec, f_pub=f_pub, f_avail=f_avail,
                           countries=countries, f_country=f_country,
                           active_section='goocampus_in')


@login_required
def mentor_detail(mentor_id):
    """Rich read-only profile view (mirrors the goocampus.in public profile)."""
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM pg_mentors WHERE id = ?", (mentor_id,)).fetchone()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        row = None
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not row:
        abort(404)
    m = dict(row)
    m['specialties_list'] = as_list(row.get('specialties'))
    m['languages_list'] = as_list(row.get('languages'))
    m['availability_map'] = as_dict(row.get('availability'))
    return render_template('pg_admin/mentor_detail.html', user=user, m=m,
                           mentor_type_labels=_MENTOR_TYPE_LABELS,
                           active_section='goocampus_in')


@login_required
def mentor_save():
    """Create (no id) or update (edit_id set) a mentor, incl. optional photo upload."""
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))

    form = request.form
    edit_id = (form.get('edit_id') or '').strip()
    name = (form.get('name') or '').strip()
    specialization = (form.get('specialization') or '').strip()
    qualification = (form.get('qualification') or '').strip()
    if not name:
        flash('Name is required.', 'error')
        return redirect(url_for('pg_mentors_admin'))

    service_type = (form.get('service_type') or 'counselling').strip()
    if service_type not in _SERVICE_TYPES:
        service_type = 'counselling'
    mentor_type = (form.get('mentor_type') or 'specialist').strip()
    if mentor_type not in _MENTOR_TYPES:
        mentor_type = 'specialist'

    fields = {
        'mentor_type': mentor_type,
        'name': name,
        'email': (form.get('email') or '').strip(),
        'phone': (form.get('phone') or '').strip(),
        'specialization': specialization,
        'country': (form.get('country') or '').strip(),
        'qualification': qualification,
        'designation': (form.get('designation') or '').strip(),
        'experience_years': _int_or_none(form.get('experience_years')),
        'experience_range': (form.get('experience_range') or '').strip(),
        'specialties': json.dumps(_parse_csv_list(form.get('specialties'))),
        'languages': json.dumps(_parse_csv_list(form.get('languages'))),
        'bio': (form.get('bio') or '').strip(),
        'awards': (form.get('awards') or '').strip(),
        'certifications': (form.get('certifications') or '').strip(),
        'medical_council_number': (form.get('medical_council_number') or '').strip(),
        'medical_council_state': (form.get('medical_council_state') or '').strip(),
        'hospital_name': (form.get('hospital_name') or '').strip(),
        'hospital_address': (form.get('hospital_address') or '').strip(),
        'counselling_fee': _num_or_none(form.get('counselling_fee')),
        'consultation_fee': _num_or_none(form.get('consultation_fee')),
        'service_type': service_type,
        'availability': json.dumps(_parse_availability(form)),
        'is_available': form.get('is_available') == 'on',
        'is_verified': form.get('is_verified') == 'on',
        'is_published': form.get('is_published') == 'on',
        'admin_notes': (form.get('admin_notes') or '').strip(),
    }
    # Full-profile fields from the mentors sheet — all admin-editable (founder 2026-08-13).
    for _c in ('gender', 'timezone', 'pricing_currency', 'discount', 'current_state',
               'current_city', 'location_origin', 'special_interest', 'hobbies',
               'completion_yr', 'profession_job_title', 'profession_company',
               'profession_location', 'profession_total_exp', 'profession_curr_work_exp',
               'profession_previous_work_exp', 'pre_work_exp', 'edu_qualification',
               'edu_pg_speciality', 'edu_mbbs_college', 'edu_mbbs_year', 'edu_pg_college',
               'edu_pg_year', 'topics_list', 'intro_video'):
        if _c in form:
            fields[_c] = (form.get(_c) or '').strip()

    conn = get_db()
    mentor_id = None
    try:
        if edit_id:
            mentor_id = int(edit_id)
            cols = list(fields.keys())
            set_clause = ", ".join(f"{c} = ?" for c in cols)
            vals = [fields[c] for c in cols]
            conn.execute(
                f"UPDATE pg_mentors SET {set_clause}, updated_by = ?, "
                f"updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                vals + [user.get('id'), mentor_id])
        else:
            cols = list(fields.keys()) + ['created_by', 'updated_by']
            placeholders = ", ".join(["?"] * len(cols))
            vals = [fields[c] for c in fields] + [user.get('id'), user.get('id')]
            row = conn.execute(
                f"INSERT INTO pg_mentors ({', '.join(cols)}) "
                f"VALUES ({placeholders}) RETURNING id", vals).fetchone()
            mentor_id = row['id'] if row else None
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error("mentor_save: %s", e)
        try:
            conn.close()
        except Exception:
            pass
        flash('Save failed.', 'error')
        return redirect(url_for('pg_mentors_admin', type=mentor_type))

    photo_msg = ''
    file = request.files.get('photo')
    if mentor_id and file and file.filename:
        ctype = (file.mimetype or '').lower()
        if ctype not in _ALLOWED_IMG:
            photo_msg = ' (photo skipped — use JPG/PNG/WebP/GIF)'
        elif not storage.is_configured():
            photo_msg = ' (photo skipped — R2 storage not configured)'
        else:
            data = file.read()
            ext = (file.filename.rsplit('.', 1)[-1] if '.' in file.filename else 'jpg').lower()
            key = f"pg_mentors/{mentor_id}/photo.{ext}"
            if storage.upload_bytes(key, data, content_type=ctype):
                try:
                    conn.execute("UPDATE pg_mentors SET photo_url = ?, "
                                 "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                 (key, mentor_id))
                    conn.commit()
                except Exception as e:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    logging.error("mentor_save photo update: %s", e)
                    photo_msg = ' (photo upload failed to save)'
            else:
                photo_msg = ' (photo upload to R2 failed)'
    try:
        conn.close()
    except Exception:
        pass

    flash(('Mentor updated.' if edit_id else 'Mentor created.') + photo_msg, 'success')
    return redirect(url_for('pg_mentors_admin', type=mentor_type))


@login_required
def mentor_toggle(mentor_id):
    """Flip one boolean flag: ?flag=is_published|is_verified|is_available."""
    user = _require_admin()
    if not user:
        return redirect(url_for('dashboard'))
    flag = (request.args.get('flag') or request.form.get('flag') or '').strip()
    if flag not in ('is_published', 'is_verified', 'is_available'):
        flash('Unknown toggle.', 'error')
        return redirect(url_for('pg_mentors_admin'))
    conn = get_db()
    try:
        conn.execute(
            f"UPDATE pg_mentors SET {flag} = NOT {flag}, "
            f"updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (user.get('id'), mentor_id))
        conn.commit()
        flash('Updated.', 'success')
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error("mentor_toggle(%s, %s): %s", mentor_id, flag, e)
        flash('Update failed.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(request.referrer or url_for('pg_mentors_admin'))


@login_required
def mentor_delete(mentor_id):
    """Soft delete — is_active = FALSE (also unpublishes so it leaves the public list)."""
    user = _require_admin()
    if not user:
        return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        conn.execute(
            "UPDATE pg_mentors SET is_active = FALSE, is_published = FALSE, "
            "updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (user.get('id'), mentor_id))
        conn.commit()
        flash('Mentor removed.', 'success')
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error("mentor_delete(%s): %s", mentor_id, e)
        flash('Delete failed.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(request.referrer or url_for('pg_mentors_admin'))


@login_required
def mentors_import():
    """Import (upsert) the goocampusworld.com mentor dataset + migrate photos to R2.
    Idempotent — safe to re-run; admin publish/verify/available choices are preserved."""
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    do_images = request.form.get('skip_images') != 'on'
    conn = get_db()
    try:
        from pg_admin.data.mentors_seed_import import import_mentors_from_seed
        res = import_mentors_from_seed(conn, created_by=user.get('id'), do_images=do_images)
        img = res['images']
        flash(f"Import done — {res['created']} created, {res['updated']} updated "
              f"(of {res['total_seed']}). Photos: {img['migrated']} migrated, "
              f"{img['skipped']} skipped, {img['failed']} failed."
              + (f" Errors on {len(res['errors'])} rows." if res['errors'] else ''),
              'success' if not res['errors'] else 'warning')
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error("mentors_import: %s", e)
        flash('Import failed — see logs.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(url_for('pg_mentors_admin'))


@login_required
def mentor_photo_admin(mentor_id):
    """Admin photo preview — 302 to a presigned R2 URL, or 302 to the original S3
    photo if it hasn't been migrated to R2 yet (so previews work pre-import)."""
    user = _require_admin()
    if not user:
        abort(403)
    conn = get_db()
    try:
        row = conn.execute("SELECT photo_url, source_photo_url FROM pg_mentors WHERE id = ?",
                           (mentor_id,)).fetchone()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        row = None
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not row:
        abort(404)
    key = row.get('photo_url')
    if key and key.startswith('pg_mentors/'):
        url = storage.presigned_get_url(key)
        if url:
            return redirect(url, code=302)
    # Fallback: not yet migrated — show the original source image.
    src = row.get('source_photo_url')
    if src:
        return redirect(src, code=302)
    abort(404)


@login_required
def mentors_import_xlsx():
    """Upload the founder's authoritative mentors_list.xlsx → upsert every mentor
    (keyed on the sheet's mentor_id) and retire the older auto-scraped set.
    Idempotent: re-uploading refreshes content but keeps admin publish/verify choices."""
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    f = request.files.get('data_file')
    if not f or not f.filename:
        flash('Choose the mentors .xlsx file to upload.', 'error')
        return redirect(url_for('pg_mentors_admin'))
    if not f.filename.lower().endswith(('.xlsx', '.xlsm')):
        flash('Please upload a .xlsx file.', 'error')
        return redirect(url_for('pg_mentors_admin'))
    retire = request.form.get('retire_others') != 'off'
    conn = get_db()
    try:
        from pg_admin.data.mentors_xlsx_import import parse_xlsx, import_mentors_from_xlsx
        rows, _headers = parse_xlsx(f.read())
        if not rows:
            flash('No mentor rows found in that file.', 'error')
            return redirect(url_for('pg_mentors_admin'))
        res = import_mentors_from_xlsx(conn, rows, created_by=user.get('id'),
                                       retire_others=retire)
        msg = (f"Imported {res['created']} new + {res['updated']} updated mentors "
               f"(of {res['total']}).")
        if res['retired']:
            msg += f" Retired {res['retired']} older auto-scraped mentors."
        msg += " Next: click “Copy photos to R2” so images are self-hosted."
        flash(msg + (f" {len(res['errors'])} row error(s) — see logs." if res['errors'] else ''),
              'success' if not res['errors'] else 'warning')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("mentors_import_xlsx: %s", e)
        flash(f'Import failed — nothing changed: {e}', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_mentors_admin'))


@login_required
def mentors_migrate_photos():
    """Copy the next batch of source photos into R2, chunked so it never times out.
    Click again until 0 remain."""
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    try:
        batch = min(int(request.form.get('batch') or 30), 60)
    except (TypeError, ValueError):
        batch = 30
    conn = get_db()
    migrated = failed = remaining = 0
    try:
        from pg_admin.data.mentors_seed_import import _migrate_photo
        # Bind the LIKE pattern as a parameter — a bare '%' literal in the SQL
        # collides with psycopg2's placeholder substitution ("tuple index out of
        # range"), per the %%/bind gotcha in CLAUDE.md.
        todo = conn.execute(
            "SELECT id, source_photo_url, photo_url FROM pg_mentors "
            " WHERE COALESCE(source_photo_url,'') <> '' "
            "   AND COALESCE(photo_url,'') NOT LIKE ? "
            " ORDER BY id LIMIT ?", ('pg_mentors/%', batch)).fetchall()
        for r in todo:
            res = _migrate_photo(conn, r['id'], r['source_photo_url'], r['photo_url'])
            if res == 'migrated':
                migrated += 1
            elif res == 'failed':
                failed += 1
        remaining = conn.execute(
            "SELECT COUNT(*) AS c FROM pg_mentors "
            " WHERE COALESCE(source_photo_url,'') <> '' "
            "   AND COALESCE(photo_url,'') NOT LIKE ?", ('pg_mentors/%',)).fetchone()['c']
        flash(f"Photos: {migrated} copied to R2, {failed} failed. {remaining} remaining"
              + (" — click “Copy photos to R2” again to continue."
                 if remaining else " — all done!"),
              'success' if not failed else 'warning')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("mentors_migrate_photos: %s", e)
        flash(f'Photo migration failed: {e}', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_mentors_admin'))
