# State seat-matrix importers (Mac-side)

Each official state seat matrix is a differently laid-out PDF, so each state has its own parser here.
A parser turns the PDF into standardised rows (college + course names from the 2025 cut-offs /
approved speciality list, quota, seats), bridges each seat to last year's cut-off (closing ranks, fee)
or flags it "new in 2026", and checks every column total against the PDF's printed totals — it stops
on any unknown college / course / hospital instead of guessing.

Rows are posted with POST /api/pg/seat-matrix/ingest (X-News-Key) as their own counselling body.

## Rajasthan (`rajasthan.py`)
    /usr/bin/python3 tools/seat_matrix/rajasthan.py <matrix.pdf> <cutoffs2025.json> <out.json>
Body "Rajasthan — State Counselling", authority `ruhs`, section `state`. College codes are
`RJ-<STANDARD-NAME>` (stable across rounds, so a Round 2 matrix reports colleges added/removed).
Quotas: Government Quota, Management Quota (RUHS / Society), All India Quota / State Quota /
Management Quota (private), Diploma Quota (In-service), DNB Quota (In-service).
After a re-import that is NOT a new round, clear the change record with POST /api/pg/seat-matrix/source
{body, year, previous:{rows:null,...}}.
