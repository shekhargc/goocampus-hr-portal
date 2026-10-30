# Counselling result importers (Mac-side)

Each authority publishes its seat-allotment result as a PDF (one line per allotted seat). A reader here turns it
into rows and posts them with `POST /api/pg/results/ingest` (X-News-Key) — one call per authority + round:

    {authority_code, year, round, round_order, status: provisional|final, title, published_on,
     source_file_name, pdf_name, pdf_b64, notes, rows:[{sno, rank, quota_raw, quota, institute_raw,
     course_raw, course, section, allotted_category, allotted_category_raw, candidate_category, remarks}]}

- **Rounds are separate.** A final list replaces the provisional list of the SAME round only (the source row keeps
  `prev_status` / `prev_row_count`). Round 2, mop-up, stray are new rounds with a higher `round_order`.
- **College names** are NOT mapped here: the portal resolves `institute_raw` through the name memory
  (`pg_admin/name_memory.py`, table `pg_name_memory`) — seat-matrix matches, college-workbook aliases, exact names,
  then a clear-winner similarity match. Unsure names wait on **/admin/pg/name-memory** until the team picks the
  college; the choice is remembered for every future file from any authority and back-fills imported results.
- **Course names** are mapped by the reader (checked against `pg_admin/data/specialty_sheet.json`) and taught to the
  memory. DNB courses / the DNB quota are kept as published with `section: dnb` (hidden from doctors, HIDE_DNB) and are
  not put through college matching.
- **Quota / category** use the 2025 cut-off spellings (`All India Quota`, `Management/Paid Seats Quota`, `NRI Quota`,
  `OPEN`, `OBC PwD` …) so 2026 closing ranks line up with the 2025 closing rank of the same round.

## MCC (`mcc.py`)
    /usr/bin/python3 tools/results/mcc.py <result.pdf> <out.json> [--cache <raw.json>]
Checks the serial numbers run 1..N with none missing and stops on any quota / category / course it doesn't know.
2026 Round 1 provisional (23.10.2026): 28,723 seats — 19,518 MD/MS, 138 Diploma, 9,067 DNB quota.

## Madhya Pradesh (`madhya_pradesh.py`)
    /usr/bin/python3 tools/results/madhya_pradesh.py <allotment.pdf> <opening_closing.pdf> <out.json>
DME MP publishes one line per **candidate** (allotted or `NOT ALLOTTED`) plus a separate "Opening Closing" PDF.
- **No personal data:** roll numbers and names are dropped as each line is read; the gender letter is cut off the
  eligible category (`IN_OBC/X/F` → `candidate_category: IN_OBC/X`); `remarks` = candidate type (`Open (INST)` …).
- `NOT ALLOTTED` lines are counted and skipped; S.NO must run 1..N and allotted + not allotted = N.
- **Ranks:** `rank` = State Common Merit Rank (My Allotments matches a doctor's `home_state_rank` against it);
  the NEET PG All-India rank goes in `rank_ai` (not stored by the ingest yet). The 2025 MP cut-offs hold
  **All-India** ranks, so a closing-rank comparison needs `rank_ai`, not `rank`.
- **Quota** = institute type + allotted-category prefix, in 2025 MP spellings: Govt `INST/` → Institutional Quota,
  Govt `IN_` → Government Quota-Inservice, Private `INST/` → Institutional Quota, Private `NON_INST/` → Private
  Quota, Private `IN_` → Private Quota-Inservice, `INST/UR/NRI/OP` → NRI Quota. **Category** = the rest
  (`INST/UR/X/OP` → `UR/X/OP`, `IN_SC/X/OP` stays). Anything else stops the run.
- **Courses:** MD/MS → approved names (checked against `specialty_sheet.json`); `POST MBBS PG DIP` → section
  `diploma`, `POST MBBS DNB` → section `dnb`, both with the MP seat-matrix names (`DNB - Paediatrics (Post-MBBS)`).
- **Cross-check:** every institute × course × subject × allotted category × MBBS-from-MP group must equal the
  official ALLOTTED COUNT, opening/closing AI rank and opening/closing state rank, and the counts must add up to
  the allotted lines — else it stops.
2026 Round 1 provisional (29.10.2026): 3,972 lines — 1,110 allotted (1,099 MD/MS, 10 Diploma, 1 DNB), 2,862 not
allotted; 893/893 opening-closing groups match.
