"""Exam engine tables — all NEW, all prefixed ex_, additive only (founder 2026-11-13).

The engine lives inside the portal for now (no new Render cost) but is kept self-contained so it can
move to its own service + database later: no foreign keys into portal tables, every row carries
tenant_id (1 = goocampus.in; 12thPlus later) and exam_code ('neet_pg'; 'neet_ug', 'kcet', 'jee' later).

  ex_tenants            who the content belongs to
  ex_exam_patterns      the exam pattern as editable settings (NBEMS changes it), versioned
  ex_subjects           subjects per exam (NEET PG: the 19 NBEMS subjects)
  ex_subject_aliases    tag → subject ("CARDIOLOGY" → Medicine); seeded + learned from the team's choices
  ex_import_batches     one uploaded file: its check report and status
  ex_questions          the question bank (draft → approved / rejected), with version number
  ex_question_images    pictures + diagrams of a question (R2; bytes in the row only when R2 is off)
  ex_question_versions  every earlier version of an edited question
"""
import json
import logging

from db import get_db
from exam_engine.subjects import SUBJECTS, SEED_ALIASES

TENANT_GOOCAMPUS_IN = 1

NEET_PG_2026 = {
    'name': 'NEET PG 2026',
    'source': 'NBEMS Information Bulletin, 1 Jul 2026 (as reported by Careers360 / Medical Dialogues; '
              'confirm against natboard.edu.in)',
    'options_per_question': 4,
    'marking': {'correct': 4, 'wrong': -1, 'unattempted': 0},
    'sections': [{'code': c, 'name': f'Section {c}', 'questions': 36, 'minutes': 42} for c in 'ABCDE'],
    'total_questions': 180, 'total_minutes': 210, 'max_marks': 720,
    'section_lock': True,              # a closed section can't be reopened
    'section_runs_full_time': True,    # finishing early does not open the next section
    'marked_unanswered_scores': 0,     # "marked for review" without an answer = unattempted
    'language': 'English',
}


# Default subject mix for auto-filling a full mock — an APPROXIMATION of recent NEET PG papers (per 200
# questions, scaled to the paper size). The team edits it on the Pattern page; it's only a starting point.
BLUEPRINT_PER_200 = {
    'Anatomy': 10, 'Physiology': 10, 'Biochemistry': 10, 'Pathology': 12, 'Pharmacology': 13, 'Microbiology': 13,
    'Forensic Medicine': 8, 'Community Medicine': 18, 'ENT': 10, 'Ophthalmology': 10, 'Medicine': 20,
    'Surgery': 20, 'Obstetrics & Gynaecology': 18, 'Paediatrics': 7, 'Orthopaedics': 5, 'Dermatology': 4,
    'Psychiatry': 4, 'Anaesthesia': 4, 'Radiology': 4,
}


def scale_blueprint(per_200, total):
    """Largest-remainder scaling so the counts add up to exactly `total`."""
    base = sum(per_200.values()) or 1
    raw = {k: v * total / base for k, v in per_200.items()}
    out = {k: int(v) for k, v in raw.items()}
    left = total - sum(out.values())
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[:max(0, left)]:
        out[k] += 1
    return out


NEET_PG_2026['blueprint'] = scale_blueprint(BLUEPRINT_PER_200, NEET_PG_2026['total_questions'])
NEET_PG_2026['blueprint_note'] = 'Approximate subject mix of recent NEET PG papers — edit to match your view.'
# subject tests / mini tests (founder's packages: 19 subject tests, mini tests in Pro) — editable defaults
NEET_PG_2026['subject_test'] = {'questions': 60, 'minutes': 70}
NEET_PG_2026['mini_test'] = {'questions': 30, 'minutes': 35}


def ensure_exam_tables():
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS ex_tenants (
            id INTEGER PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("INSERT INTO ex_tenants (id, code, name) VALUES (?, 'goocampus_in', 'goocampus.in') "
                     "ON CONFLICT (id) DO NOTHING", (TENANT_GOOCAMPUS_IN,))

        conn.execute('''CREATE TABLE IF NOT EXISTS ex_exam_patterns (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            exam_code TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL,
            config_json TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            UNIQUE (tenant_id, exam_code, version)
        )''')
        conn.execute("INSERT INTO ex_exam_patterns (tenant_id, exam_code, version, name, config_json) "
                     "VALUES (?, 'neet_pg', 1, ?, ?) ON CONFLICT (tenant_id, exam_code, version) DO NOTHING",
                     (TENANT_GOOCAMPUS_IN, NEET_PG_2026['name'], json.dumps(NEET_PG_2026)))

        # older rows (seeded before the blueprint existed) get the new keys, nothing else changes
        for r in conn.execute("SELECT id, config_json FROM ex_exam_patterns WHERE exam_code='neet_pg'").fetchall():
            try:
                cfg = json.loads(r['config_json'] or '{}')
            except Exception:
                continue
            missing = {k: NEET_PG_2026[k] for k in ('blueprint', 'blueprint_note', 'subject_test', 'mini_test')
                       if k not in cfg}
            if missing:
                cfg.update(missing)
                conn.execute("UPDATE ex_exam_patterns SET config_json=? WHERE id=?", (json.dumps(cfg), r['id']))

        conn.execute('''CREATE TABLE IF NOT EXISTS ex_subjects (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            exam_code TEXT NOT NULL,
            name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            UNIQUE (tenant_id, exam_code, name)
        )''')
        for exam_code, names in SUBJECTS.items():
            for i, name in enumerate(names, 1):
                conn.execute("INSERT INTO ex_subjects (tenant_id, exam_code, name, sort_order) VALUES (?, ?, ?, ?) "
                             "ON CONFLICT (tenant_id, exam_code, name) DO NOTHING",
                             (TENANT_GOOCAMPUS_IN, exam_code, name, i))

        conn.execute('''CREATE TABLE IF NOT EXISTS ex_subject_aliases (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            exam_code TEXT NOT NULL,
            alias_key TEXT NOT NULL,              -- normalised tag (subjects.norm_tag)
            subject_id INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT 'seed',  -- seed | team
            created_by TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (tenant_id, exam_code, alias_key)
        )''')
        for exam_code, aliases in SEED_ALIASES.items():
            ids = {r['name']: r['id'] for r in conn.execute(
                "SELECT id, name FROM ex_subjects WHERE tenant_id=? AND exam_code=?",
                (TENANT_GOOCAMPUS_IN, exam_code)).fetchall()}
            for key, subject in aliases.items():
                if subject in ids:
                    conn.execute("INSERT INTO ex_subject_aliases (tenant_id, exam_code, alias_key, subject_id) "
                                 "VALUES (?, ?, ?, ?) ON CONFLICT (tenant_id, exam_code, alias_key) DO NOTHING",
                                 (TENANT_GOOCAMPUS_IN, exam_code, key, ids[subject]))

        conn.execute('''CREATE TABLE IF NOT EXISTS ex_import_batches (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            exam_code TEXT NOT NULL DEFAULT 'neet_pg',
            kind TEXT NOT NULL,                   -- docx | pdf | xlsx
            filename TEXT NOT NULL,
            file_key TEXT DEFAULT '',             -- R2 key of the original file
            file_data BYTEA,                      -- only when R2 isn't configured
            file_size INTEGER DEFAULT 0,
            file_sha1 TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'parsing',  -- parsing | ready | failed
            error TEXT DEFAULT '',
            total INTEGER DEFAULT 0,
            with_errors INTEGER DEFAULT 0,
            summary_json TEXT DEFAULT '{}',
            notes_json TEXT DEFAULT '[]',
            info_json TEXT DEFAULT '{}',
            note TEXT DEFAULT '',
            uploaded_by TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            parsed_at TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ex_batches_tenant ON ex_import_batches (tenant_id, exam_code, id)")

        conn.execute('''CREATE TABLE IF NOT EXISTS ex_questions (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            exam_code TEXT NOT NULL DEFAULT 'neet_pg',
            batch_id INTEGER,
            source_no INTEGER,                    -- question number in the uploaded file
            source_ref TEXT DEFAULT '',           -- e.g. 'Sheet1 row 12'
            page_from INTEGER DEFAULT 0,          -- PDF pages the question sits on (0 = not a PDF)
            page_to INTEGER DEFAULT 0,
            stem TEXT NOT NULL DEFAULT '',
            image_desc TEXT DEFAULT '',           -- "image finding" text from the file — team only
            options_json TEXT NOT NULL DEFAULT '[]',   -- [["A","text"], …]
            answer TEXT DEFAULT '',               -- 'A'…'D'
            sections_json TEXT DEFAULT '[]',      -- explanation: [["How to solve","…"], …]
            subject_id INTEGER,
            topic TEXT DEFAULT '',
            tags_raw TEXT DEFAULT '',
            lead_tag TEXT DEFAULT '',
            flags_json TEXT DEFAULT '[]',
            n_errors INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft', -- draft | approved | rejected
            reject_reason TEXT DEFAULT '',
            fingerprint TEXT DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            approved_by TEXT DEFAULT '',
            approved_at TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ex_q_batch ON ex_questions (batch_id, source_no)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ex_q_fp ON ex_questions (tenant_id, exam_code, fingerprint)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ex_q_status ON ex_questions (tenant_id, exam_code, status, subject_id)")

        conn.execute('''CREATE TABLE IF NOT EXISTS ex_question_images (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            question_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'stem',    -- stem | explanation
            sort_order INTEGER DEFAULT 0,
            file_key TEXT DEFAULT '',
            data BYTEA,                           -- only when R2 isn't configured
            content_type TEXT DEFAULT 'image/png',
            ext TEXT DEFAULT 'png',
            width INTEGER, height INTEGER,
            source TEXT DEFAULT '',               -- docx | pdf_image | crop | upload
            page INTEGER DEFAULT 0,
            created_by TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ex_qimg_q ON ex_question_images (question_id, role, sort_order)")

        conn.execute('''CREATE TABLE IF NOT EXISTS ex_question_versions (
            id SERIAL PRIMARY KEY,
            question_id INTEGER NOT NULL,
            version INTEGER NOT NULL,
            snapshot_json TEXT NOT NULL,
            changed_by TEXT DEFAULT '',
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            note TEXT DEFAULT ''
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ex_qver_q ON ex_question_versions (question_id, version)")

        # ── Step 4: papers (a mock = sections of questions; locked before it is published) ──
        conn.execute('''CREATE TABLE IF NOT EXISTS ex_papers (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            exam_code TEXT NOT NULL DEFAULT 'neet_pg',
            title TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'full',     -- full | subject | mini
            subject_id INTEGER,                    -- subject tests only
            description TEXT DEFAULT '',
            pattern_json TEXT NOT NULL,            -- sections, minutes, marking — copied from the pattern
            status TEXT NOT NULL DEFAULT 'draft',  -- draft | locked | published | retired
            is_free_sample INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            created_by TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            locked_by TEXT DEFAULT '',
            locked_at TIMESTAMP,
            published_by TEXT DEFAULT '',
            published_at TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ex_papers_t ON ex_papers (tenant_id, exam_code, status)")
        conn.execute('''CREATE TABLE IF NOT EXISTS ex_paper_items (
            id SERIAL PRIMARY KEY,
            paper_id INTEGER NOT NULL,
            section_code TEXT NOT NULL,
            position INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            question_version INTEGER,              -- set at lock
            snapshot_json TEXT,                    -- frozen copy of the question at lock (later edits don't change it)
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (paper_id, question_id)
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ex_pitems_p ON ex_paper_items (paper_id, section_code, position)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ex_pitems_q ON ex_paper_items (question_id)")
        conn.commit()
    except Exception as e:
        logging.error(f"ensure_exam_tables: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass
