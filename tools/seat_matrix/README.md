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

## Gujarat (`gujarat.py`)
    /usr/bin/python3 tools/seat_matrix/gujarat.py <matrix.pdf> <dnb.pdf> [<pwd.pdf>] <cutoffs2025.json> <out.json>
Body "Gujarat — State Counselling", authority `acpmec` (ACPPGMEC). The matrix ("Tentative Vacant Seat for Round - 01") is two columns
of course blocks per page, one line per college code × quota (AMED-GQ …; codes mapped to the 2025 names in `COLLEGES`),
read from word positions (zeros sit on grey fills). Quotas are the PDF's key: GQ State Quota, UQ Institutional Quota,
IQ In-service Quota, MQ Management Quota, NQ NRI Quota; categories OP / SC / ST / SE / EWS as printed (MQ / NQ seats
are all OP). State Quota bridges to 2025 'Government Quota' exactly (`'Government Quota$'`, so it never picks
'Government Quota-Inservice'). Checks: every line adds to its TOT, every block to its total line (S.No. sequence too),
the 1-MD/MS / 2-Diploma / Total lines, and the course × quota and MD / MS / Diploma × quota summary pages.
The DNB file ("In Service Reservation (10%) for NBEMS courses") is a SCANNED image: it is transcribed in the script and
pinned to its SHA-256 (a re-issued file stops the script). Post-MBBS DNB → `DNB - <course> (Post-MBBS)`, section dnb,
DNB Quota (In-service); post-MBBS diploma DNB → `Diploma in …`, section diploma, Diploma Quota (In-service) (as Rajasthan);
categories UR / SC / ST / OBC / EWS as printed. The optional PwD vacancy list repeats matrix lines that hold a PwD seat
(PwD is inside the line's TOT, category not given): it is checked line by line as a subset and adds no seats.
2026-27 Round 1: 2,675 matrix seats + 13 in-service DNB / diploma = 2,688.

## MCC DNB (`mcc_dnb.py`)
    /usr/bin/python3 tools/seat_matrix/mcc_dnb.py <dnb_matrix.pdf> <cutoffs2025.json> <out.json>
Body "All India MCC — DNB", authority `mcc`, section `dnb` (MCC's "FINAL SEATS MATRIX DNB PG COUNSELLING 2026",
503 pages). One PDF line per institute × program with 10 category columns (Open, Open PwD, General-EWS, -PwD, OBC,
-PwD, SC, -PwD, ST, -PwD) + Total; quota is always "DNB Quota". Rows are split per category (zeros dropped).
MCC conventions as the AIQ / CIQ / Deemed bodies: college_code = MCC's 6-digit code, college_name = the PDF's own
institute text (address included, code stripped), institute_type / quota = the PDF's text, category = 2025 cut-off
wording (OPEN / EWS / OBC / SC / ST [+ " PwD"]), category_code = the PDF column. Course = `DNB - <Title>` /
`DNB Diploma - <Title>` (same as tools/results/mcc.py). State = last address line ("State-PIN(code)"), aliases
Orissa / Pondicherry / Uttaranchal, else `STATE_BY_CODE` (cells that print only a city). Bridge only to 2025
MCC (All India) DNB cut-off rows of the same institute (MCC code or exact name), course, DNB quota, category →
else new. Checks: every line adds to its total; the "TOTAL SEATS" row (last page only, never data) per column and
grand total; output rows re-add to it. 2026: 4,487 lines / 1,472 institutes / 9,201 seats.
NOTE: before posting, `recommended._bodies(conn)` (no section) must exclude section `dnb`, or the New-2026 seat
picker and the Rankings "new colleges" list pick up every DNB seat/hospital.

## Uttar Pradesh (`uttar_pradesh.py`)
    /usr/bin/python3 tools/seat_matrix/uttar_pradesh.py <mdms.pdf> <dnb.pdf> <cutoffs2025.json> <out.json>
Body "Uttar Pradesh — State Counselling", authority DGME UP (upneet.gov.in "Seat Matrix For" prints, Round 1).
Two PDFs, one layout: MD/MS (35 Govt + 36 Private college blocks, incl. a few medical-college diplomas DCH/DGO/
D ORTH/DA/DLO/DMRD/DVD) and DNB (51 Govt hospitals: POST MBBS DNB → section `dnb`, "DNB - … (Post-MBBS)";
POST MBBS DIPLOMA → section `diploma`). A diagonal red watermark is dropped before the cells are read.
Quotas: State Quota (all Govt seats), Private Quota, Private Quota (Muslim Minority) / (Jain Minority) for the
minority blocks (bridged to 2025 "Private Quota-Minority"). One line per course × category: UR/OBC/SC/ST/EWS plus
UP's own BS/SS/SG/TS/WE codes, "-PwD" for PH seats; BS/SS/… bridge to 2025 "Government Quota-Inservice" (the only
place those codes occur), every other Govt seat to "Government Quota" only. Quota families match whole 2025 quota
names (UP's nest: "Government Quota" / "Government Quota-Inservice"). Checks: each course row (groups = seat total,
OP + PH = each group), each college block to its Total row, and Total (Govt) / Total (Private) / Grand Total per
column in both files. 2026 Round 1: 3,961 MD/MS-PDF seats + 164 DNB-PDF seats = 4,125.

## Odisha (`odisha.py`)
    /usr/bin/python3 tools/seat_matrix/odisha.py <mdms.pdf> <diploma.pdf> <dnb.pdf> <cutoffs2025.json> <out.json>
Body "Odisha — State Counselling", authority Odisha (PG (Medical) Counselling Committee, MKCG Brahmapur; notices
No. 46 MD/MS, No. 47 Post-MBBS Diploma, No. 48 Post-MBBS DNB, 26.10.2026). All three PDFs are SCANNED images: the
tables are transcribed in the script cell by cell and pinned to the PDFs' SHA-256 (a re-issued file stops the
script — re-transcribe it). MD/MS: In-service State Quota and Direct State Quota, 11 colleges each (count + category
list "1-SEBC 1-SC 3-UR"), then the Hi-Tech BBSR / Hi-Tech Rourkela / DRIEMS management columns (counts only).
Quotas: State Quota, In-service Quota, Management Quota, Management Quota (In-service) → 2025 Government Quota /
Government Quota-Inservice / Management Quota / Management Quota-Inservice, matched exactly ('$'). Diploma → section
diploma, Diploma Quota (2025 Odisha diplomas: Government Quota, then -Inservice); DNB → `DNB - <course> (Post-MBBS)`,
section dnb, DNB Quota. Categories UR / SC / ST / SEBC / EWS with "-GC" (green card → 2025 GCH/GC), "-ES"
(ex-serviceman → ES), "-PwD" (→ PH). Checks: each cell's count = its category list, every row = its Total, every
column = the TOTAL / Grand Total row (MD/MS, MGT, diploma, DNB). Two MKCG in-service cells (Community Medicine,
General Medicine) print a category list that does not match the count — kept with no category (`MISPRINTS`).
2026-27: 463 MD/MS + 43 diploma + 18 DNB = 524 seats.

## Jammu & Kashmir (`jammu_kashmir.py`)
    /usr/bin/python3 tools/seat_matrix/jammu_kashmir.py <bopee.pdf> <cutoffs2025.json> <out.json>
Body "Jammu and Kashmir — State Counselling", authority BOPEE ("OPERATIVE V 1.0", 28.10.2026). p1 MD/MS, p2 PG
Diploma (section diploma) + the category table. Government colleges print TOTAL / OM / "CAT. & UT LADAKH" per
course — reserved categories are NOT split per college, so those seats are category "Reserved (CAT & UT Ladakh)"
and bridge to the 2025 OM rank. ASCOMS Jammu: OM (G) → Government Quota (OM), OM (M) → Management Quota (OM),
HM → Hindu Minority Quota, NRI → NRI Quota (bridged to 2025 HM / NRI). Checks: every row (TOTAL = OM + CAT;
ASCOMS Total = G + M + HM + NRI), every column to the Total row, and the category table (its 360 total, OM 138 =
government OM seats, the rest = government CAT seats, PG Diploma column); the one reserved PG Diploma seat takes
the diploma column's only reserved category (RBA). 2026 Round 1: 409 MD/MS + 2 PG Diploma = 411 seats.

## Jharkhand (`jharkhand.py`)
    /usr/bin/python3 tools/seat_matrix/jharkhand.py <jh.pdf> <cutoffs2025.json> <out.json>
Body "Jharkhand — State Counselling", authority Jharkhand (state-quota seat matrix per Health Dept. letters
615 (9) / 616 (9), 15–16.10.2026). One table: institute × course, "50% State Quota Seats" and "In Service"; no
categories (bridge = 2025 UR rank). Quotas: State Quota → 2025 'Government Quota$', In-service Quota →
'Government Quota-Inservice'. D.G.O. / D.C.H. / D.M.R.D. → section diploma; "Post M.B.B.S DNB (Obs. & Gynae.)"
→ `DNB - Obstetrics and Gynaecology (Post-MBBS)`, section dnb. New: Sadar Hospital Ranchi, RINPAS Kanke
("Phychiatry" read as MD - Psychiatry). Checks: each institute's Total line and the notice's 122 State Quota + 7
In-service. 2026: 129 seats.
