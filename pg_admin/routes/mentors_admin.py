"""Admin Mentor Management screen (goocampus.org staff). True-admin gated — this
section isn't wired into Access Master yet, so we restrict to is_admin exactly like
the NEET-PG PDF admin does.

CRUD every pg_mentors field + publish/verify/available toggles + photo upload to R2.
Mirrors the old React DoctorManagement screen's fields.
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

# Weekdays used to build the availability JSON from the form.
_WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday',
             'friday', 'saturday', 'sunday']
_SERVICE_TYPES = ('consultation', 'counselling', 'both')
_ALLOWED_IMG = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}


def _require_admin():
    """Return the logged-in admin user, or None (caller redirects/aborts)."""
    user = get_user()
    if not user or not user.get('is_admin'):
        return None
    return user


def _parse_csv_list(raw):
    """'Emergency Care, Trauma' -> ['Emergency Care', 'Trauma'] (deduped, order-kept)."""
    out, seen = [], set()
    for part in (raw or '').split(','):
        s = part.strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def _parse_availability(form):
    """Build the availability JSON from per-weekday start/end form fields.
    avail_<day>_start / avail_<day>_end → {"monday":[{"start":"18:00","end":"20:00"}]}."""
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
    """List + filter mentors with the stat cards, and render the CRUD screen."""
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))

    q = (request.args.get('q') or '').strip()
    f_spec = (request.args.get('specialization') or '').strip()
    f_pub = (request.args.get('published') or '').strip()      # '', 'true', 'false'
    f_avail = (request.args.get('available') or '').strip()    # '', 'true', 'false'

    conds = ["is_active"]   # hide soft-deleted from the working list
    params = []
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
        # Stat cards (across all non-deleted mentors, ignoring the filters).
        stats = {
            'total': conn.execute(
                "SELECT COUNT(*) AS c FROM pg_mentors WHERE is_active").fetchone()['c'],
            'published': conn.execute(
                "SELECT COUNT(*) AS c FROM pg_mentors WHERE is_active AND is_published").fetchone()['c'],
            'available': conn.execute(
                "SELECT COUNT(*) AS c FROM pg_mentors WHERE is_active AND is_available").fetchone()['c'],
            'verified': conn.execute(
                "SELECT COUNT(*) AS c FROM pg_mentors WHERE is_active AND is_verified").fetchone()['c'],
        }
        # Specialization options for the filter dropdown (distinct, non-empty).
        spec_rows = conn.execute(
            "SELECT DISTINCT specialization FROM pg_mentors "
            "WHERE is_active AND specialization <> '' ORDER BY specialization"
        ).fetchall()
        specializations = [r['specialization'] for r in spec_rows]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error("mentors_admin: %s", e)
        mentors, stats, specializations = [], {'total': 0, 'published': 0, 'available': 0, 'verified': 0}, []
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Pre-decode the JSON columns for the template (avail form + specialty/language chips).
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
                           service_types=_SERVICE_TYPES,
                           q=q, f_spec=f_spec, f_pub=f_pub, f_avail=f_avail,
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
    if not name or not specialization or not qualification:
        flash('Name, specialization and qualification are required.', 'error')
        return redirect(url_for('pg_mentors_admin'))

    service_type = (form.get('service_type') or 'counselling').strip()
    if service_type not in _SERVICE_TYPES:
        service_type = 'counselling'

    fields = {
        'name': name,
        'email': (form.get('email') or '').strip(),
        'phone': (form.get('phone') or '').strip(),
        'specialization': specialization,
        'qualification': qualification,
        'designation': (form.get('designation') or '').strip(),
        'experience_years': _int_or_none(form.get('experience_years')),
        'specialties': json.dumps(_parse_csv_list(form.get('specialties'))),
        'languages': json.dumps(_parse_csv_list(form.get('languages'))),
        'bio': (form.get('bio') or '').strip(),
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
                vals + [user.get('id'), mentor_id]
            )
        else:
            cols = list(fields.keys()) + ['created_by', 'updated_by']
            placeholders = ", ".join(["?"] * len(cols))
            vals = [fields[c] for c in fields] + [user.get('id'), user.get('id')]
            row = conn.execute(
                f"INSERT INTO pg_mentors ({', '.join(cols)}) "
                f"VALUES ({placeholders}) RETURNING id",
                vals
            ).fetchone()
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
        return redirect(url_for('pg_mentors_admin'))

    # ── Optional photo upload → R2 (photo_url stores the R2 object key) ──
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
    return redirect(url_for('pg_mentors_admin'))


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
            (user.get('id'), mentor_id)
        )
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
    return redirect(url_for('pg_mentors_admin'))


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
            (user.get('id'), mentor_id)
        )
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
    return redirect(url_for('pg_mentors_admin'))


@login_required
def mentor_photo_admin(mentor_id):
    """Admin photo preview — 302 to a presigned R2 URL (works for drafts too)."""
    user = _require_admin()
    if not user:
        abort(403)
    conn = get_db()
    try:
        row = conn.execute("SELECT photo_url FROM pg_mentors WHERE id = ?",
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
    key = row.get('photo_url') if row else None
    if not key:
        abort(404)
    url = storage.presigned_get_url(key)
    if not url:
        abort(404)
    return redirect(url, code=302)
