"""core/academic_sync.py — keep a client's academic record in step across both sides.

Academic details are entered + owned by the CLIENT (in the registration form and,
now, on the client dashboard). They auto-flow into ops_academic_details for each
pathway. When Operations edits that ops row, we mirror the shared fields BACK into
the client's client_academics so the client dashboard always shows the latest — and
vice-versa (the client→ops direction lives in app.py as
`_sync_client_academics_to_ops`). (founder 2026-07-30)
"""
import logging


def sync_ops_academics_to_client(conn, registration_number):
    """Mirror the latest ops_academic_details row for `registration_number` into the
    matching client_academics row(s). Only columns that exist on BOTH tables are
    copied (client_academics is a subset — no speciality_interest / *_2 columns).
    Safe + idempotent; never raises (logs and moves on)."""
    try:
        if not registration_number:
            return
        oa = conn.execute(
            "SELECT * FROM ops_academic_details WHERE registration_number = ? "
            "ORDER BY id DESC LIMIT 1", (registration_number,)).fetchone()
        if not oa:
            return
        oa = dict(oa)
        regs = conn.execute(
            "SELECT id FROM client_registrations WHERE registration_number = ?",
            (registration_number,)).fetchall()
        if not regs:
            return
        ca_cols = {r['column_name'] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'client_academics'").fetchall()}
        shared = [c for c in oa.keys()
                  if c in ca_cols and c not in ('id', 'created_at', 'created_by', 'registration_id')]
        if not shared:
            return
        for rr in regs:
            rid = rr['id']
            exists = conn.execute(
                "SELECT 1 FROM client_academics WHERE registration_id = ?", (rid,)).fetchone()
            if exists:
                sets = ', '.join(f"{c} = ?" for c in shared)
                conn.execute(f"UPDATE client_academics SET {sets} WHERE registration_id = ?",
                             [oa.get(c) for c in shared] + [rid])
            else:
                cols = ['registration_id'] + shared
                conn.execute(
                    f"INSERT INTO client_academics ({', '.join(cols)}) "
                    f"VALUES ({', '.join(['?'] * len(cols))})",
                    [rid] + [oa.get(c) for c in shared])
    except Exception as e:
        logging.warning(f"sync_ops_academics_to_client {registration_number}: {e}")
