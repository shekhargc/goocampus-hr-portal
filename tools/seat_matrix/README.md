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
Body "Odisha — State Counselling", authority Odisha (PG (Medical) Counselling Committee, MKCG Brahmapur). Round 1
matrices REVISED 30.10.2026 "after redressal of grievances": notices No. 58 MD/MS, No. 59 Post-MBBS Diploma,
No. 60 Post-MBBS DNB (they replace No. 46/47/48 of 26.10.2026); the MD/MS was revised again on 31.10.2026 (No. 65,
"typographical error" corrected — it replaces No. 58; diploma No. 59 and DNB No. 60 stay). The tables are transcribed in the script cell by
cell and pinned to the PDFs' SHA-256 (a re-issued file stops the script — re-transcribe it). The MD/MS and diploma
PDFs now have a text layer: every transcribed cell is re-read from it and must match (the MD/MS layer draws some
labels twice at the same spot — repeated glyphs are dropped first). The DNB PDF is still SCANNED (transcribed from
the image). MD/MS: In-service State Quota (left half) and Direct State Quota (right half), 11 colleges each (count +
category list "1-SEBC 1-SC 3-UR"), then the Hi-Tech BBSR / Hi-Tech Rourkela / DRIEMS management columns (counts
only). Quotas: State Quota, In-service Quota, Management Quota, Management Quota (In-service) → 2025 Government Quota /
Government Quota-Inservice / Management Quota / Management Quota-Inservice, matched exactly ('$'). Diploma → section
diploma, Diploma Quota (2025 Odisha diplomas: Government Quota, then -Inservice); DNB → `DNB - <course> (Post-MBBS)`,
section dnb, DNB Quota. Categories UR / SC / ST / SEBC / EWS with "-GC" (green card → 2025 GCH/GC), "-ES"
(ex-serviceman → ES), "-PwD" (→ PH). Checks: each cell's count = its category list, every row = its Total, every
column = the TOTAL / Grand Total row (MD/MS, MGT, diploma, DNB), and the text layer. The two 26.10 MKCG in-service
misprints (Community Medicine, General Medicine) are fixed in the revision, so `MISPRINTS` is empty. 2026-27
(revised): 463 MD/MS (In-service 193 + 38 MGT, Direct 193 + 39 MGT) + 43 diploma + 18 DNB = 524 seats — same
totals as 26.10; the revision only moves seats between in-service and direct (SCB / MKCG / VIMSAR) and relabels
categories. Diploma and DNB are unchanged. No. 65 (31.10) keeps every total (still 524) and only re-labels SCB /
MKCG seats: General Medicine — in-service SCB 8 → 7 / MKCG 3 → 4 (one SC seat moves SCB → MKCG), direct SCB 7 → 8 /
MKCG 4 → 3 (one UR seat moves MKCG → SCB); in-service General Surgery — SCB one UR → SC, MKCG one SC → UR.

## Jammu & Kashmir (`jammu_kashmir.py`)
    /usr/bin/python3 tools/seat_matrix/jammu_kashmir.py <bopee.pdf> <cutoffs2025.json> <out.json>
Body "Jammu and Kashmir — State Counselling", authority BOPEE ("OPERATIVE V 1.01 · REVISED", 31.10.2026; replaces
V 1.0 of 28.10.2026 — same two pages, MD/MS + PG Diploma). p1 MD/MS, p2 PG
Diploma (section diploma) + the category table. Government colleges print TOTAL / OM / "CAT. & UT LADAKH" per
course — reserved categories are NOT split per college, so those seats are category "Reserved (CAT & UT Ladakh)"
and bridge to the 2025 OM rank. ASCOMS Jammu: OM (G) → Government Quota (OM), OM (M) → Management Quota (OM),
HM → Hindu Minority Quota, NRI → NRI Quota (bridged to 2025 HM / NRI). Checks: every row (TOTAL = OM + CAT;
ASCOMS Total = G + M + HM + NRI), every column to the Total row, and the category table (its 360 total, OM 138 =
government OM seats, the rest = government CAT seats, PG Diploma column, and V 1.01's "342 … JK ONLY" = total − STK/STL); the one
reserved PG Diploma seat takes the diploma column's only reserved category (RBA). 2026 Round 1 (revised): 405 MD/MS +
2 PG Diploma = 407 seats (V 1.0: 409 + 2 = 411; category table 360 → 356, OM 138 → 137). The revision only drops 4 GMC
Kathua seats (Anaesthesiology, General Medicine, Pathology 2 → 1 each — one reserved seat; General Surgery 2 → 1 — one
OM seat); PG Diploma unchanged.

## Jharkhand (`jharkhand.py`)
    /usr/bin/python3 tools/seat_matrix/jharkhand.py <jh.pdf> <cutoffs2025.json> <out.json>
Body "Jharkhand — State Counselling", authority Jharkhand (state-quota seat matrix per Health Dept. letters
615 (9) / 616 (9), 15–16.10.2026). One table: institute × course, "50% State Quota Seats" and "In Service"; no
categories (bridge = 2025 UR rank). Quotas: State Quota → 2025 'Government Quota$', In-service Quota →
'Government Quota-Inservice'. D.G.O. / D.C.H. / D.M.R.D. → section diploma; "Post M.B.B.S DNB (Obs. & Gynae.)"
→ `DNB - Obstetrics and Gynaecology (Post-MBBS)`, section dnb. New: Sadar Hospital Ranchi, RINPAS Kanke
("Phychiatry" read as MD - Psychiatry). Checks: each institute's Total line and the notice's 122 State Quota + 7
In-service. 2026: 129 seats.

## West Bengal (`west_bengal.py`)
    /usr/bin/python3 tools/seat_matrix/west_bengal.py <matrix.pdf> <cutoffs2025.json> <out.json>
Body "West Bengal — State Counselling", authority `wbmcc` (WBMCC "West Bengal PG Medical Counselling 2026 · Round No: 1 ·
Seat Matrix", printed 30/10/2026, 121 pages; re-issued as the REVISED print of 31/10/2026 — same 878 lines and seats,
only Institute of Child Health and RKMSP VIMS re-typed Private → State Government, which does not change the output
because 2025 colleges take their type from the 2025 cut-offs). Pages are stored rotated 90°: words are turned to the visible page and read
by column position. One line per institute × program × quota (SNo, Institute Name / Type, Program Name, Stream, Quota,
UR, UR PwD, EWS, EWS PwD, OBC, OBC PwD, SC, SC PwD, ST, ST PwD, Total Seats); cell text wraps mid-word, so names are
matched with white space removed. College codes `WB-<STANDARD-NAME>`; 29 colleges map to their 2025 cut-off names
(`COLLEGES`, e.g. MEDICAL COLLEGE KOLKATA → 'Government Medical College, Kolkata'), 37 new colleges / district hospitals
get a standard name (`NEW_COLLEGES`). Quotas: Open Seat → State Quota (2025 'State Quota$'), In Service → In-service
Quota ('State Quota-Inservice$'), Private Management → Management Quota, NRI → NRI Quota, In Service DNB Quota →
DNB Quota (In-service) for "(NBEMS)" programs (section dnb, `DNB - <course> (Post-MBBS)`; the two direct 6-year
programs use MCC DNB's `DNB - … (Direct 6 Years Course)`) or Diploma Quota (In-service) for "(NBEMS- DIPLOMA)"
programs (section diploma, `Diploma in …`). WB 2025 has no DNB cut-offs, so those are all new. Categories as printed,
PwD as "-PwD" (bridged to 2025 "-PH", then the base category); OBC (one column in 2026) bridges to 2025 OBC, then
OBC-A, then OBC-B; Management → MQ; NRI → UR, then NRI. The PDF prints NO totals (no page / institute / grand
total), so the checks are: headings + page header + "Page No." on every page, SNo 1…878 continuous, every line's
categories = its Total Seats, every cell one whole number, and the output re-adds to the Total Seats column.
2026 Round 1: 878 lines / 66 colleges / 1,459 seats (1,272 MD/MS/MPH + 127 diploma + 60 DNB).

## Karnataka (`karnataka.py`)
    /usr/bin/python3 tools/seat_matrix/karnataka.py <medical.pdf> <stjohns.pdf> <dnb_regular.pdf> <dnb_diploma.pdf> <cutoffs2025.json> <out.json>
Body "Karnataka — State Counselling", authority `kea`, section `state` (KEA "PROVISIONAL SEAT MATRIX - 2026 (30/10/2026)",
four PDFs, all with a text layer, read with `grids()`). Medical: 65 colleges (M01 …, printed name must match `COLLEGES`
exactly → 2025 name), one KK (Kalyana Karnataka) + one RK (Rest of Karnataka) line per course, columns NON-INSERVICE /
INSERVICE / PWD × (CAT1 2A 2B 3A 3B ST SCA SCB SCC SCC(20%) GM) + HK-RK total, and on the RK line the private columns
GMP GMPH OPN NRI OTH(Q) MMH MEH MC MM MK MU MA ME + Total Seats. St John's (M48) RC1 / RC2 / RC3 are a separate PDF.
DNB Regular (Q…) and DNB Diploma (V…) are in-service seats at government hospitals, same KK / RK layout.
Quotas (2025 KEA names, matched exactly with '$'): non-inservice → Government Quota (govt + private colleges' govt seats),
category as printed + " (KK)" on the KK line, PwD → "-PwD"; in-service → In-service Quota (no 2025 KEA in-service rows,
so never bridged); GMP / GMPH → Private Quota - GMP; OPN → Private Quota - Open; NRI → NRI Quota; OTH(Q) → Management
Quota (2025 MNG); MMH … ME and St John's RC1-3 → Private Quota - Minority. Government seats bridge to KEA's 2025 codes:
2A → 2AG, 2A (KK) → 2AH, CAT1 → 1G, SC-A → SC-AG, PwD → P-prefix (PGM, P2AG), then GM / GMH (KK seats then RK);
SC-C (20%) bridges as SC-C. DNB Regular → `DNB - <course> (Post-MBBS)`, section dnb, DNB Quota (In-service); DNB Diploma →
`DNB Diploma - <course>`, section dnb (hidden), Diploma Quota (In-service) — all 30 seats (founder 2026-10-30: the file
lists General Medicine / Surgery, which have no diploma, so it is treated as DNB until KEA clarifies). The two ESIC colleges get hand-made
codes (`CODE_FIX`, the 40-char cut collides). Checks: column headings on every page, every KK / RK line = its HK-RK,
every course's Total Seats = KK + RK + private, college Sr No 1…n, every column = the GRAND TOTAL lines (all four files),
and the files' grand totals. 2026 Round 1: 4,724 medical (4,718 MD/MS + 6 diploma) + 94 St John's + 44 DNB + 30 DNB
diploma = 4,892 seats; 85 institutes (64 in 2025 + Chikkamagaluru IMS + 20 hospitals).

## Kerala (`kerala.py`)
    /usr/bin/python3 tools/seat_matrix/kerala.py <go.pdf> <cutoffs2025.json> <out.json>
Body "Kerala — State Counselling", authority `cee_kerala` (CEE Kerala), section `state`. Source: the Government Order
G.O.(Ms)No.360/2026/H&FWD (30-10-2026) approving the 2026-27 PG Medical seat matrix (24 pages, text layer, read with
`grids()`). p1-2 are the order; the annexure "PG MEDICAL - 2026" has one table per institute ("<CODE>:<name>", one line
per course with Total + category columns, a Total line) and a Summary line per group: Government medical colleges +
RCC Thiruvananthapuram + Malabar Cancer Centre (State Quota seats EXCLUDING in-service; UR SC ST EZ BH MU LA BX KU EW,
<cat>-PD, UR-XS, UR-DK), Self Financing (Non Minority) (excluding NRI; UR … KU EW) and Self Financing (Non Minority &
Minority) (excluding Minority/NRI; UR … KU). So only state-merit seats are in the GO — no AIQ, in-service, NRI or
minority-community seats (none stored; nothing to keep out of the rankings). Institute code + printed name must match
`COLLEGES` (→ 2025 CEE name, codes `KL-<STANDARD-NAME>`); bracket code + course name must match `COURSES`.
Quotas: government → 'Government Quota' (2025 'Government Quota$'), self-financing → 'Private Quota' (2025
'Private Quota$', not '- Minority' / NRI). Categories as printed; bridge UR → SM (CEE's state-merit code), X-PD → PD,
X, SM, UR-XS / UR-DK → SM, others same code then SM. "Diploma in Clinical Pathology" → 'Diploma in Pathology', section
diploma. No DNB. Checks: group headings + page ranges, column headings, every course line = its Total, every institute =
its Total line, every group = its Summary line, every number on p3-24 inside a parsed table, output = sum of the three
Summary totals. 2026-27: 911 seats (Government 442 + SF Non Minority 183 + SF Non Minority & Minority 286; 908 MD/MS +
3 diploma), 29 institutes, all in 2025 (Travancore Medical College, Kollam is in 2025 but not in the GO).

## Tamil Nadu (`tamil_nadu.py`)
    /usr/bin/python3 tools/seat_matrix/tamil_nadu.py <vacancy.pdf> <cutoffs2025.json> <out.json>
Body "Tamil Nadu — State Counselling", authority `dmer_tn`, section `state` (Selection Committee / DMER "TENTATIVE VACANCY
FOR PG DEGREE/DIPLOMA COURSE 2026-2027 … AS ON 31-10-2026", 64 pages, text layer; per the Rounds rule this Round 1 vacancy
list is the full matrix). Three tables, one block per speciality (runs on across pages, ends with a TOTAL line):
GOVERNMENT MEDICAL COLLEGES pp 1-33 (state share only — the 50% AIQ is MCC's; 26 colleges), SELF FINANCING pp 34-58 (21
private colleges / hospitals incl. CMC Vellore and ESI-PGIMSR K.K. Nagar), PRIVATE pp 59-62 (Sri Venkateswaraa, private
university); pp 63-64 split CMC Vellore's 50% management seats per branch into MNW / IP / S / GM. Not covered: deemed
universities, AIQ, DNB. Pages are stored rotated 90°: words and ruling lines are turned and cells read by the drawn rules.
On government pages the management / OVER ALL TOTAL columns are hidden under white boxes but still in the text layer —
checked empty (OVER ALL TOTAL = TOTAL). College codes `TN-<STANDARD-NAME>` = the 2025 DMER names (`COLLEGES`; all 48
colleges are in the 2025 cut-offs), so the 2025-based rankings' Desk tiers carry over.
Quotas (2025 TN names, matched exactly with '$'): OPEN → Government Quota; SERVICE → Government Quota-Service (in-service,
left out of rankings); CMC 20% → CMC 20% Quota (category blank — not split in 2026; bridges OC, then BC / MBC&DNC);
MQ → Management Quota (category OPEN); CMC 50% → CMC 50% Quota, categories CMC-Minority Network / -Institutional
Preference / -Service / -General Merit from pp 63-64; TM / MM / CM → Management Quota-Minority (Telugu / Malayalam /
Christian Minority); NRI → NRI Quota (NRI). Categories OC BC BCM MBC&DNC SC SCA ST as printed; with no same-category
2025 rank a government / service seat uses the 2025 OC rank. Sections: MD / MS / M.Ch 6-year Neuro Surgery → mdms;
D.A. / D.C.H. / D.C.P. / D.D.V.L. / D.G.O / D.O. / D.ORTHO / Dip. in Diabetology → diploma.
Checks: page count, titles, column / group headings and positions in every block, the footer key, SNO 1…n per block,
every line (OPEN + SERVICE + CMC 20% = TOTAL, MQ … NRI = management TOTAL, both = OVER ALL TOTAL), every column = the
block's TOTAL line, CMC 50% cells = pp 63-64 per branch (MNW + IP + S + GM = CMC 50%, Total line 127), output = sum of
the printed OVER ALL TOTALs. 2026-27 Round 1 (31.10.2026): 2,336 seats (govt 1,231 + self-financing 1,056 + private
49; 2,317 MD/MS/MCh + 19 diploma). The earlier 62-page issue of the same date has identical pages 1-62 — only the
CMC 50% breakdown (pp 63-64) was added.

## Maharashtra (`maharashtra.py`)
    /usr/bin/python3 tools/seat_matrix/maharashtra.py <govt.pdf> <private.pdf> <diploma.pdf> <cutoffs2025.json> <out.json>
Body "Maharashtra — State Counselling", authority `cetcell_mh` (State CET Cell), section `state`. Three provisional
matrices dated 02.11.2026, merged: Govt/Corporation/Central-Govt/Aided MD/MS (summary page + one page per college, each
category split GEN / INS / GEN PWD / INS PWD), Private/Minority MD/MS (Total, Inst., Avail., categories, MGT, NRI) and the
PG Diploma page (LTMC Mumbai). Quotas: State Quota, In-service Quota (INS), Institutional Quota (MGT), NRI Quota,
Minority Quota (JIIU Jalna), All India Quota (Vikhe Patil + NKP Salve print AIQ in place of MGT — no 2025 Maharashtra
cut-off → new). Orphan seats ("1 ORP AB", "1 + 1 ORP C") are stored as "<category>-Orphan" and must equal the summary's
ORPHAN A-B / C columns. 2025 spellings bridged by cat_match (NT1/NT2/NT3, "IS-" in-service, "-PH", IQ, NRI, Minority).
Checks: every subject line adds to its State / Avail. seats, every page's columns to its Total line, private Inst. = MGT
+ NRI and Total = Inst. + Avail., both summary pages = the sum of the college pages (the private summary leaves out JIIU
and the two AIQ colleges); printed category-total cells that skipped ORP-annotated cells are listed (soft) in
printed_total_cells_off. 2026 R1 provisional: 2,759 seats, 54 colleges (govt 1,581 + private 1,164 + diploma 14;
State 1,832, In-service 323, Institutional 315, NRI 163, AIQ 104, Minority 22); 2,472 seats bridged to a 2025 cut-off.
