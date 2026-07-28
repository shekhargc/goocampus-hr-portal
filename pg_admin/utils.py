"""Shared helpers for the pg_admin module (JSON coercion, public serialization)."""
import json


def as_list(val):
    """A JSONB list column comes back as a Python list on Postgres (RealDictCursor)
    but as a TEXT string on SQLite. Normalise either to a list."""
    if val is None or val == '':
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            out = json.loads(val)
            return out if isinstance(out, list) else []
        except Exception:
            return []
    return []


def as_dict(val):
    """Same as as_list but for a JSONB object column (e.g. availability)."""
    if val is None or val == '':
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            out = json.loads(val)
            return out if isinstance(out, dict) else {}
        except Exception:
            return {}
    return {}


def _num(val):
    """NUMERIC comes back as Decimal on Postgres — make it JSON-friendly."""
    if val is None:
        return None
    try:
        f = float(val)
        return int(f) if f == int(f) else f
    except Exception:
        return None


def mentor_public_dict(row, photo_base_url):
    """Map a pg_mentors row to the PUBLIC shape the goocampus.in site renders.

    Admin-only fields (email, phone, medical council no./state, admin_notes,
    created_by/updated_by) are NEVER included. `photo_base_url` is the absolute
    origin (e.g. https://goocampus.org) used to build the stable photo URL.
    """
    # Only advertise a photo we can actually serve — i.e. one migrated to R2.
    # source_photo_url points at the old goocampus-s3bucket, which is PRIVATE (403),
    # so promising a photo on the strength of that field made the site render a
    # broken image for every mentor. Better no photo (the site draws its own
    # initials placeholder) than a broken one. (founder 2026-07-28)
    photo = None
    if row.get('photo_url'):
        photo = f"{photo_base_url}/api/pg/mentors/{row['id']}/photo"
    return {
        'id': row['id'],
        'mentor_type': row.get('mentor_type') or 'specialist',
        'name': row['name'],
        'specialization': row.get('specialization') or '',
        'qualification': row.get('qualification') or '',
        'designation': row.get('designation') or '',
        'experience_years': row.get('experience_years'),
        'experience_range': row.get('experience_range') or '',
        'specialties': as_list(row.get('specialties')),
        'languages': as_list(row.get('languages')),
        'bio': row.get('bio') or '',
        'awards': row.get('awards') or '',
        'certifications': row.get('certifications') or '',
        'photo_url': photo,
        'hospital_name': row.get('hospital_name') or '',
        'counselling_fee': _num(row.get('counselling_fee')),
        'consultation_fee': _num(row.get('consultation_fee')),
        'service_type': row.get('service_type') or 'counselling',
        'total_mentees': row.get('total_mentees') or '',
        'is_available': bool(row.get('is_available')),
        'is_verified': bool(row.get('is_verified')),
        'rating': _num(row.get('rating')) or 0,
        'total_reviews': row.get('reviews_count') or row.get('total_reviews') or 0,
    }
