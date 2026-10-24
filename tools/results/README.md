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
