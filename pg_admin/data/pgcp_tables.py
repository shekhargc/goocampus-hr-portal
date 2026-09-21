"""Indian PGCP counselling onboarding (founder spec, build 2026-09-21).

Invitation-only. The team creates an invitation (amount + discount + client type);
the doctor logs in on goocampus.in and fills a 4-step, save-and-continue form
(Personal → Academic → Preferences → Payment). Managed in the goocampus.in Admin
('Indian PGCP' section) on goocampus.org.

Two client types:
  - paying   : new client invited by the team, pays the invited amount − discount.
  - internal : existing Consulting/UAE client, auto-upgraded free into ₹2L Premium.

Flexible/repeating parts (specialities, fee bands, preferred colleges/states, seat
preference order, sponsor) are stored as JSON text so the form can evolve without a
migration.
"""
import logging
from db import get_db


def ensure_pgcp_tables():
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_pgcp_invitations (
            id SERIAL PRIMARY KEY,
            token TEXT UNIQUE,                 -- opaque invite link id
            client_name TEXT DEFAULT '',
            mobile TEXT DEFAULT '',            -- links the doctor's login to this invite
            email TEXT DEFAULT '',
            client_type TEXT DEFAULT 'paying', -- paying | internal
            invited_amount NUMERIC(14,2),      -- total counselling fee quoted
            discount NUMERIC(14,2) DEFAULT 0,
            plan_code TEXT DEFAULT '',         -- optional pg_plans.code to grant
            status TEXT DEFAULT 'invited',     -- invited|started|submitted|paid|completed|cancelled
            notes TEXT DEFAULT '',
            created_by TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pgcp_inv_mobile ON pg_pgcp_invitations (mobile)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pgcp_inv_status ON pg_pgcp_invitations (status)")

        conn.execute('''CREATE TABLE IF NOT EXISTS pg_pgcp_onboarding (
            id SERIAL PRIMARY KEY,
            invitation_id INTEGER,
            user_id INTEGER,                   -- pg_users.id once the doctor logs in
            step INTEGER DEFAULT 1,            -- furthest step reached (1..4)
            status TEXT DEFAULT 'draft',       -- draft | submitted | paid | completed
            -- Step 1 · Personal
            photo_url TEXT DEFAULT '',
            official_name TEXT DEFAULT '',     -- exactly as on the PG registration
            mobile TEXT DEFAULT '',
            email TEXT DEFAULT '',
            state TEXT DEFAULT '',
            city TEXT DEFAULT '',
            -- Step 2 · Academic
            mbbs_college TEXT DEFAULT '',
            mbbs_college_id INTEGER,           -- pg_college_master.id when picked from the DB
            mbbs_year TEXT DEFAULT '',
            neet_attempt TEXT DEFAULT '',      -- first | second
            prev_year TEXT DEFAULT '',
            prev_score TEXT DEFAULT '',
            prev_rank TEXT DEFAULT '',
            neetpg2026_score TEXT DEFAULT '',  -- optional, blank until results
            neetpg2026_rank TEXT DEFAULT '',
            -- Step 3 · Preferences (JSON text)
            specialities TEXT DEFAULT '[]',    -- ["Radiology","Medicine",...] up to 3
            only_one_speciality INTEGER DEFAULT 0,
            ack_single INTEGER DEFAULT 0,      -- acknowledgement tick when only one
            fee_bands TEXT DEFAULT '{}',       -- {"Radiology":{"min":..,"max":..}, ...}
            preferred_colleges TEXT DEFAULT '[]',
            preferred_states TEXT DEFAULT '[]',
            anywhere_india INTEGER DEFAULT 0,
            seat_pref_order TEXT DEFAULT '[]', -- ordered ["govt","private","management","nri"]
            seat_pref_interest TEXT DEFAULT '{}', -- {"govt":true,"nri":false,...}
            nri_interested INTEGER DEFAULT 0,
            sponsor_name TEXT DEFAULT '',
            sponsor_relationship TEXT DEFAULT '',
            sponsor_country TEXT DEFAULT '',
            -- Step 4 · Payment
            payment_mode TEXT DEFAULT '',      -- online | transfer_declared
            payment_ref TEXT DEFAULT '',
            amount_paid NUMERIC(14,2),
            submitted_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pgcp_onb_inv ON pg_pgcp_onboarding (invitation_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pgcp_onb_user ON pg_pgcp_onboarding (user_id)")
        conn.commit()
        logging.info("pg_pgcp tables ensured")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ensure_pgcp_tables: {e}")
    finally:
        try: conn.close()
        except Exception: pass
