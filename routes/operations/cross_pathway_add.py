"""
routes/operations/cross_pathway_add.py — add an existing client to the
Training pathway list WITHOUT re-registering them.

Business need (2026-07-01): a doctor who signed up for AMC Consulting or
AUS PGCP sometimes also has to appear in the Training pathway list (e.g.
under the AMC 1 / AMC MCQ training). Rather than re-keying every detail,
ops opens the source client's profile, clicks "Add to Training Pathway",
confirms a small pre-filled form (only the fields Training actually needs),
and a NEW plab_clients row with pathway='training' is created — linked back
to the source via the existing referral_* columns.

This is NOT an internal transfer: the source registration is left
untouched; the client now exists in BOTH lists.

Design notes (first version — founder to review):
- The training entry gets its OWN new GCTRN/<FY>/NNN registration number.
- Only identity + the training service fields are captured. Financials are
  left blank for the training team to fill later, per "only take the
  details needed here in the training pathway".
- A duplicate guard warns (but still allows) if this source client was
  already added to training — so AMC 1 and AMC 2 can be two entries if
  genuinely needed.
"""

import logging
from datetime import date

from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db
from core.registration import (
    PATHWAY_REG_PREFIX,
    indian_financial_year,
    _next_sequence,
)
from routes.operations._form_lookups import section_client_lookups

# Training plan_type -> the product it maps to (drives product_id).
_TRAINING_PRODUCT_BY_PLAN = {'AMC 1': 'AMC MCQ', 'AMC 2': 'AMC Clinical'}

# Identity fields copied straight across from the source client. These are
# the only personal details Training needs; everything else (financials,
# section records) starts blank on the new training entry.
_COPY_FIELDS = [
    'prefix', 'first_name', 'last_name', 'mobile', 'whatsapp1', 'whatsapp2',
    'email', 'dob', 'city', 'state',
    'father_name', 'father_phone', 'mother_name', 'mother_phone', 'parents_email',
    'counsellor', 'counsellor_email', 'counsellor_number',
]


def _training_reg_number(conn):
    """Next GCTRN/<FY>/NNN. Built directly from the training prefix — the
    plan-name based generator would misroute 'AMC Clinical' to australia."""
    prefix = PATHWAY_REG_PREFIX['training']
    fy = indian_financial_year()
    seq = _next_sequence(conn, prefix, fy)
    return f"{prefix}/{fy}/{seq:03d}"


def _existing_training_for(conn, src):
    """Return any Training-pathway rows that already represent this person —
    either added from this source before (referral link) or matched by the
    same mobile number. Used to BLOCK a duplicate add."""
    mobile = (src['mobile'] or '').strip()
    return conn.execute(
        "SELECT id, registration_number, plan_type FROM plab_clients "
        "WHERE COALESCE(pathway,'plab') = 'training' "
        "  AND (referral_client_reg = ? OR (? <> '' AND mobile = ?)) "
        "ORDER BY id",
        (src['registration_number'], mobile, mobile),
    ).fetchall()


@admin_required
def ops_add_to_training_form(src_id):
    """GET — pre-filled 'add this client to Training' form."""
    conn = get_db()
    src = conn.execute(
        "SELECT *, COALESCE(pathway,'plab') AS src_pathway FROM plab_clients WHERE id = ?",
        (src_id,),
    ).fetchone()
    if not src:
        conn.close()
        flash('Source client not found.', 'error')
        return redirect(url_for('dashboard'))

    # Already in Training? Then block the add entirely — no duplicate entry.
    existing = _existing_training_for(conn, src)
    if existing:
        first_id = existing[0]['id']
        conn.close()
        flash('This client is already in the Training pathway, so a new entry '
              'was not created. Opening the existing Training record.', 'info')
        return redirect(url_for('ops_training_client_detail', client_id=first_id))

    lk = section_client_lookups('training')
    conn.close()
    return render_template(
        'ops_add_to_training.html',
        user=get_user(),
        src=src,
        existing=existing,
        plan_types=lk.get('plan_types') or ['AMC 1', 'AMC 2'],
        stages=lk.get('plab_stages') or [],
        account_statuses=lk.get('account_statuses') or ['In Process'],
        counsellors=lk.get('counsellors') or [],
        today=date.today().isoformat(),
        active_pathway='training',
    )


@admin_required
def ops_add_to_training_save(src_id):
    """POST — create the training-pathway entry from the confirmed form."""
    conn = get_db()
    try:
        src = conn.execute(
            "SELECT *, COALESCE(pathway,'plab') AS src_pathway FROM plab_clients WHERE id = ?",
            (src_id,),
        ).fetchone()
        if not src:
            flash('Source client not found.', 'error')
            return redirect(url_for('dashboard'))

        # Hard block: never create a second Training entry for someone who is
        # already in the Training pathway.
        existing = _existing_training_for(conn, src)
        if existing:
            conn.close()
            flash('This client is already in the Training pathway — no new '
                  'entry was created.', 'error')
            return redirect(url_for('ops_training_client_detail', client_id=existing[0]['id']))

        f = request.form
        plan_type = (f.get('plan_type') or 'AMC 1').strip()
        product_name = _TRAINING_PRODUCT_BY_PLAN.get(plan_type)
        product_id = None
        if product_name:
            pr = conn.execute(
                "SELECT id FROM products_services WHERE name = ? ORDER BY id LIMIT 1",
                (product_name,),
            ).fetchone()
            product_id = pr['id'] if pr else None

        new_reg = _training_reg_number(conn)

        # Build the insert. Identity comes from the (editable) form, falling
        # back to the source row; service fields come from the form.
        row = {}
        for col in _COPY_FIELDS:
            row[col] = (f.get(col) if f.get(col) is not None else src[col]) or None
        row['registration_number'] = new_reg
        row['pathway'] = 'training'
        row['product_id'] = product_id
        row['plan_type'] = plan_type
        row['current_stage'] = (f.get('current_stage') or '').strip() or None
        row['account_status'] = (f.get('account_status') or 'In Process').strip()
        row['registration_date'] = (f.get('registration_date') or date.today().isoformat()).strip()
        # Cross-pathway linkage back to the source (existing referral_* cols).
        row['referral_source_pathway'] = src['src_pathway']
        row['referral_channel'] = 'Cross-pathway add'
        row['referral_client_reg'] = src['registration_number']
        row['referral_client_name'] = (
            (src['prefix'] or '') + ' ' + (src['first_name'] or '') + ' ' + (src['last_name'] or '')
        ).strip()

        cols = list(row.keys())
        placeholders = ', '.join(['?'] * len(cols))
        conn.execute(
            f"INSERT INTO plab_clients ({', '.join(cols)}) VALUES ({placeholders})",
            [row[c] for c in cols],
        )
        new_id = conn.execute(
            "SELECT id FROM plab_clients WHERE registration_number = ?", (new_reg,)
        ).fetchone()['id']
        conn.commit()
        flash(
            f"Added to Training pathway as {new_reg} ({plan_type}). "
            f"Original {src['registration_number']} is unchanged.",
            'success',
        )
        return redirect(url_for('ops_training_client_detail', client_id=new_id))
    except Exception as e:
        logging.error(f"ops_add_to_training_save: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f'Error adding to Training pathway: {e}', 'error')
        return redirect(url_for('ops_add_to_training_form', src_id=src_id))
    finally:
        conn.close()


def register_routes(app):
    app.add_url_rule(
        '/operations/add-to-training/<int:src_id>',
        endpoint='ops_add_to_training_form',
        view_func=ops_add_to_training_form,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/add-to-training/<int:src_id>',
        endpoint='ops_add_to_training_save',
        view_func=ops_add_to_training_save,
        methods=['POST'],
    )
