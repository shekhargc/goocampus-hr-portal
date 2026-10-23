# State seat-matrix importers (Mac-side)

Each official state seat matrix is a differently laid-out PDF, so each state has its own parser here.
A parser turns the PDF into standardised rows (college + course names from the 2025 cut-offs /
approved speciality list, quota, seats), bridges each seat to last year's cut-off (closing ranks, fee)
or flags it "new in 2026", and checks every column total against the PDF's printed totals — it stops
on any unknown college / course / hospital instead of guessing.

Rows are posted with POST /api/pg/seat-matrix/ingest (X-News-Key) as their own counselling body.
`common.py` holds the shared parts: `grids()` (table cells read from word positions — catches numbers printed
on coloured fills that PyMuPDF's extract() drops), stable college codes `<XX>-<STANDARD-NAME>` (40-char cut),
and `build()` — the bridge to the 2025 cut-off (same college + course, quota family in order of preference,
same category first, else the open/general rank with `cutoff_category` saying which). `cutoff_course` is set
whenever the course name exists anywhere in the cut-offs (health check "courses linked").

**Rounds (founder 2026-10-23):** the Round 1 matrix IS the state's full seat matrix. Later rounds (Round 2,
mop-up, stray) publish *vacancies* — store those as a separate body (e.g. "Rajasthan — Round 2 Vacancies"),
never as a replacement of the Round 1 body.

## Rajasthan (`rajasthan.py`)
    /usr/bin/python3 tools/seat_matrix/rajasthan.py <matrix.pdf> <cutoffs2025.json> <out.json>
Body "Rajasthan — State Counselling", authority `ruhs`, section `state`. College codes are
`RJ-<STANDARD-NAME>` (stable across rounds, so a Round 2 matrix reports colleges added/removed).
Quotas: Government Quota, Management Quota (RUHS / Society), All India Quota / State Quota /
Management Quota (private), Diploma Quota (In-service), DNB Quota (In-service).
After a re-import that is NOT a new round, clear the change record with POST /api/pg/seat-matrix/source
{body, year, previous:{rows:null,...}}.

## Goa (`goa.py`)
    /usr/bin/python3 tools/seat_matrix/goa.py <dte_goa.pdf> <cutoffs2025.json> <out.json>
Body "Goa — State Counselling", authority `dte_goa`. Goa Medical College only; one line per course ×
category (SC/ST/OBC/EWS/GEN, "-PwD" for PwD seats). Quota: Government Quota. Checks every row and the
category totals. 2026-27: 72 seats.

## Chhattisgarh (`chhattisgarh.py`)
    /usr/bin/python3 tools/seat_matrix/chhattisgarh.py <dme_cg.pdf> <cutoffs2025.json> <out.json>
Body "Chhattisgarh — State Counselling", authority `dme_cg`. The PDF is a 200-point roster, one line per
seat (merged to course × category). Quotas: State Quota (govt; the 50% All India part is MCC's),
State Quota (Institutional / Open) and NRI Quota (Institutional / Open) for private colleges.
Categories UR/ST/SC/OBC/EWS, ST-Special (2% special ST), -PwD. Checks each college's header box
(State / NRI) and the "Institutional / Open Quota: N Seats" lines. 2026: 452 seats.

## Madhya Pradesh (`madhya_pradesh.py`)
    /usr/bin/python3 tools/seat_matrix/madhya_pradesh.py <govt.pdf> <private.pdf> <district.pdf> <cutoffs2025.json> <out.json>
Body "Madhya Pradesh — State Counselling", authority `dme_mp` (the three PDFs are merged into one stored file).
Govt: State Quota (Open + PWD), In-service Quota (30%, Open + PWD). Private: NRI Quota, In-service Quota
(Institutional), State Quota (Institutional), State Quota (Non-Institutional), each Open + PWD. District
hospitals: Diploma Quota (Post-MBBS Diploma), DNB Quota (hidden with DNB). Checks: every college row adds up
to its total, every column to the printed Total row (a few are printed blank), every course's colleges to its
Grand Total, and the private pages to the private overview page. 2026-27 First Round: 2,169 seats.
