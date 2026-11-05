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

## Rajasthan (`rajasthan.py`)
    /usr/bin/python3 tools/results/rajasthan.py <allotment.pdf> <out.json> [--merit <ruhs_state_merit.json>] [--nbems <neet2026.json>]
RUHS / SMS Medical College publishes notice pages + one line per **allotted** candidate (no not-allotted lines).
Round, status (Indicative/Provisional → `provisional`, Final → `final`) and date are read from the notice.
- **No personal data:** Reg ID, NEET roll no, name, gender and domicile are dropped as each line is read (the roll is
  held in memory only for the `--nbems` check).
- **Ranks:** `rank` = State Merit Rank, `rank_ai` = the printed All India Rank (2025 RJ cut-offs are All-India ranks).
  `--merit` checks every (state rank, AI rank) pair against the loaded RUHS state merit list, `--nbems` checks the
  AI rank against NBEMS by roll.
- **Quota** = the seat type in brackets after the college + Service Status, in 2025 RJ spellings: `Government` /
  `State` / `AI` / `Management` × `In-Service` / `Non-Service` → `Government Quota-In Service`, `All India Quota-Non
  Service` …; Post-MBBS Diplomas (printed `Government (In-Service)`) → `Diploma Quota-In Service`; Post-MBBS DNB →
  `DNB Quota-In Service` (new, section `dnb`). **Category** `General`→`GEN`, `OBC NCL`→`OBC-NCL`, `MBC NCL`→`MBC-NCL`,
  SC ST EWS. `candidate_category` = "Additional Category (Filled)" (`STA` / `PwBD`, the candidate's claim).
- A college printed without its "(Seat Type)" stops the run unless it is in `SEAT_MISSING` (hand-checked, keyed by
  S.No + college + course; reported in `checks.seat_type_inferred`).
2026 Round 1 indicative (31.10.2026): 1,366 allotted (1,269 MD/MS, 95 Diploma, 2 DNB), 46 colleges; S.No 1297 seat
type not printed → AI inferred; AI rank matches the merit list and NBEMS for 1,366/1,366.

## Goa (`goa.py`)
    /usr/bin/python3 tools/results/goa.py <allotment.pdf> <out.json> [--seat-matrix <Goa seat rows.json>] [--nbems <neet2026.json>]
DTE Goa publishes the whole merit list (Goa Medical College only) under GROUP headings, with the allotted programme
code or blank / `OCNA` (no seat — counted and skipped). Reg no and name are dropped as each line is read.
- `rank` = MERIT NO., `rank_ai` = printed NEET PG RANK; quota `Government Quota` (page 2 "state quota seats").
- **The seat category is not printed** (the colour key only colours the candidate's own category cell), so
  `allotted_category` = the candidate's CATEGORY 2 (`-` → GEN, PwD → DR-GEN as in 2025; EWS new) and
  `allotted_category_raw` is empty. `--seat-matrix` walks the 2026 seat matrix in merit order and lists where a
  candidate would sit on another category's seat (`checks.seat_matrix_walk`).
- Checks: merit numbers 1..N, NEET rank never drops within a group, allotted per programme = page-2 seats, total = TOTAL.
2026 Round 1 (31.10.2026, PDF date): 161 lines — 72 allotted (all MD/MS), 37 OCNA, 52 blank; seat-matrix walk
agrees on 68/72 (3 GEN candidates on de-reserved EWS seats, 1 knock-on in Psychiatry).

## Tamil Nadu (`tamil_nadu.py`)
    /usr/bin/python3 tools/results/tamil_nadu.py <pwd_allotment.pdf> <out.json> --bridge <dmer_tn_gq.json>
Reads the Government Quota **PwD** provisional allotment list (SNO, GRANK, ARNO, NAME, COMMUNITY, SERVICE, T.MARK,
ALLOTTED TO = "GQ - course" + college). ARNO and NAME are never read. Stored as its own round, `Round 1 (PwD)`, so
the main Round 1 list doesn't replace it.
- `rank` = GRANK; `rank_ai` is not printed — looked up by GRANK in the loaded TN GQ merit list; 'nA' addendum ranks
  share rank n there, so the line with the same COMMUNITY and total marks is taken (none / two → stop).
- Quota `GQ` → `Government Quota`; seat category not printed → `allotted_category: PwD`, `candidate_category` =
  community + ` PwD` (`OC PwD`, `MBC&DNC PwD` …), `remarks` = `Service` for in-service candidates.
- NB: the 2025 TN cut-offs hold **TN merit ranks** (GRANK), not All-India ranks.
2026 Round 1 PwD provisional (31.10.2026): 12 allotted (all MD/MS, 6 colleges); rank_ai 12/12 (all GRANKs unique).

## Gujarat (`gujarat.py`)
    /usr/bin/python3 tools/results/gujarat.py <meritwise.pdf> <institutewise.pdf> <last_merit.pdf> <out.json> [--bridge <acpmec merit list.json>]
ACPPGMEC publishes three PDFs per round: **Meritwise** allotment list (main source, one line per allotted seat),
**Institute Wise** list (same seats grouped by college — gives the printed college NAME) and **Last Merit** (closing
merit per college × branch × quota block × category). Authority `acpmec`.
- **No personal data:** student name, User ID, the gender flag and (institute-wise) pass college are dropped as each line
  is read. Cells are read as PDF spans by column position (some cells are clipped: `NAMOME` = NAMOMED, `NService-n` =
  `INService-n`; both repaired and recorded in checks).
- **Ranks:** `rank` = MERITNO (state merit; half numbers like `256.5` are PwD candidates inserted later → floor, exact
  number in `remarks`), `rank_ai` = the printed **AIQ Rank** (NEET PG AIR). `--bridge` checks every (merit, AIR) pair
  against the loaded general merit list.
- **Quota** (2025 Gujarat spellings): GQ → `Government Quota`, UQ → `Institutional Quota`, IQ →
  `Government Quota-Inservice`, MQ → `Management Quota`, NQ → `NRI Quota` (`quota_raw` = the code). **Category** =
  ADM Cat: `OP SE EW SC ST` (+ `-PH`, e.g. `SEPH` → `SE-PH`), `MQ`, `NRI`. `remarks` also carries Adm Type Merit
  (`GU-3.0` university merit for UQ, `INService-1.0`, `NRI-…`).
- **Courses:** same branch map as `tools/seat_matrix/gujarat.py`; Diplomas → section `diploma`; `<Branch> (DNB)` →
  `DNB - <Branch>`, section `dnb`. `institute_raw` = the college name printed in the institute-wise list for the code.
- **Cross-checks (stop on failure):** SR 1..N; every meritwise line equals an institute-wise line (college × course ×
  quota × category × merit × AIR × candidate category × Adm Type Merit), so all institute × course × quota × category
  counts agree; every printed Last Merit group equals our highest merit in that group — Government OPEN + Management =
  MERITNO, Government EWS/SC/ST/SE = Cat Merit, Institutional / Inservice / NRI = the Adm Type Merit number; the `PWD`
  lines (Government PwD merit, not printed in the allotment lists) are checked for presence and order; 99999 = seat
  conversion.
2026 Round 1 provisional (31.10.2026): 2,329 seats — 2,319 MD/MS, 9 Diploma, 1 DNB; GQ 1,542 · UQ 489 · MQ 253 ·
NQ 37 · IQ 8; institute-wise 2,329/2,329 lines (1,785 groups) match; Last Merit 1,777/1,777 printed groups match
(8 one-seat groups are not printed there); rank_ai 2,329/2,329 printed, all pairs found in the merit list.

## Chhattisgarh (`chhattisgarh.py`)
    /usr/bin/python3 tools/results/chhattisgarh.py <allotment.pdf> <out.json> [--nbems neet2026.json] [--merit dme_cg merit.json] [--matrix cg seat matrix out.json]
DME CG prints one table line per allotted seat (no names): SN, roll no, candidate category, PH, institute, program,
preference, quota, allotted category, allotted / candidate gender, All India NEET Rank, State Rank, scores, candidature
type. Authority `dme_cg`.
- **No personal data:** the roll number is used in memory only (`--nbems` / `--merit` check the printed AIR and state
  rank against the NBEMS result and the loaded CG merit list by roll) and dropped; candidate gender dropped.
- **Ranks:** `rank` = State Rank, `rank_ai` = All India NEET Rank (both printed).
- **Quota:** the 2025 CG cut-offs are filed by **candidature** (`Government Quota-MBBS Passout / -Domicile /
  -Non-Domicile / -Inservice`), so `quota` comes from the Candidature Type column; the printed seat quota (`State
  Institutional Quota` / `State Open Quota`) is `quota_raw`, the candidature text is `remarks`.
- **Category:** `UR-NC` → `UR`, `UR-Female` → `UR-F` (2025 spelling; allotted gender must agree); PH = Y → `-PwD`.
- **Checks:** SN 1..N, roll numbers in the page text = table lines read, reserved seats only to that category,
  `--matrix`: allotted per college × course ≤ the state seats of the seat matrix. No totals are printed.
2026 Round 1 provisional (PDF dated 31.10.2026): 278 seats, all MD/MS, 10 colleges (223 Institutional, 55 Open);
AIR + state rank 278/278 printed and verified (NBEMS 278/278, merit list 278/278); 110 groups within the matrix.

## Kerala (`kerala.py`)
    /usr/bin/python3 tools/results/kerala.py <allotment.pdf> <out.json> [--merit cee_kerala_state_merit_final.json]
CEE Kerala → cee.kerala.gov.in/pgm2026 → Allotment List → "Phase 1 - Allotment List Provisional"
(`list/allot_p1_provi.pdf`, "First Phase Allotment List (Provisional)"). Phase n = Round n. Authority `cee_kerala`.
One table line per seat: Sl.No, ApplNo (dropped as read), Rank, `CODE- College`, `CC- Course`, candidate category,
allotted category, option no. No names.
- **Ranks:** the printed Rank is the **NEET PG AIR** (every value is an AIR of the Kerala State Merit List; the list runs
  in AIR order) → `rank_ai`. `rank` = Kerala state merit rank looked up by AIR in the loaded final State Merit List.
- **Quota** (not printed) from college type + category, 2025 CEE spellings: government college (Govt. MCs, RCC, Malabar
  Cancer Centre) → `Government Quota`, self-financing → `Private Quota`, AC / MM → `Private Quota - Minority`,
  NR → `NRI Quota`, NC / NM → `NRI Quota - Minority`.
- **Category** as printed (`SM` = state merit, SC ST EZ BH MU LA BX KU EW …); `#` (subject to screening committee) and
  `*` (NRI provisionally allowed) are cut off into `remarks`. `XS` (ex-serviceman) is new in 2026 — kept as `XS`.
- **Checks:** Sl.No 1..N, application numbers in page text = lines read, AIR strictly increasing, state ranks in list
  order, course code + name both known, minority/NRI codes only at self-financing colleges. No totals are printed.
2026 Phase 1 provisional (31.10.2026): 1,082 seats (1,080 MD/MS, 2 Diploma), 30 colleges; rank_ai 1,082/1,082 printed,
state rank 1,082/1,082 from the merit list.

## Punjab (`punjab.py`)
    /usr/bin/python3 tools/results/punjab.py <selection.pdf> <out.json> --merit bfuhs_r1_main.json [--nri bfuhs_r1_nri.json] [--nbems neet2026.json] [--round 1] [--status provisional]
BFUHS Faridkot "Provisional selection list for admission to PG Courses under NEET PG 2026": one 10-column table (M No,
Regn No., NEET PG Rollno, NAME, Category, University, Allotted College, Branch, Quota, Category); no title/date printed
(published_on = PDF creation date). Regn No, name and university are never read into the output; the roll is used in
memory only. `rank` = M No (checked against the Round 1 merit list by roll), `rank_ai` = AIR by roll (merit list,
then NBEMS). NRI lines print no M No → `rank` empty, NRI list position in `remarks`. Private-college quotas map to the
2025 college-specific spellings (DMC = Dayanand + Gian Sagar, CMC, SGRD, Adesh); CMC quota "A" and SGRD's
ultrasonography "Sikh Minority Management Seats" have no 2025 equivalent → kept as new quotas. Post-MBBS DNB → section
dnb; diplomas, DCH/DA/Sports Medicine and Ultrasonography batches → section diploma.
2026 Round 1 provisional (02.11.2026): 578 lines (505 MD/MS, 45 diploma, 28 DNB), 572 merit numbers match the merit list,
578 AIRs match NBEMS.

## Jharkhand (`jharkhand.py`)
    /usr/bin/python3 tools/results/jharkhand.py <allotment.pdf> <out.json> --seat-matrix <jh seat-matrix out.json> [--nbems neet2026.json] [--round "Round 1"] [--round-order 1] [--status provisional]
JCECEB "Provisional Seat Allotment List" of the State Quota PG Medical counselling: one 20-column table (Sl. No., App.
No., Roll No., Name, Gender, D.O.B., Category, Is EWS, Is PWD, DisabilityType, Incentive %, CML Rank, Category / EWS /
PTG / D.Q. Rank, Allotted Institute, Allotted Course, Seat Opted Category, Roster Point). App no, name, gender and DOB
are never read into the output; the roll is used in memory only. Authority `jceceb`. `rank` = CML Rank (state merit),
`rank_ai` = AIR from NBEMS 2026 by roll. No quota is printed: a seat is 'Government Quota-Inservice' when the 2026
seat matrix has ONLY in-service seats for that institute + course, 'Government Quota' when only state seats; a course
with both stops the run. Category = Seat Opted Category (UR ST SC EWS BC-I BC-II UR-PH); in-service incentive % in
`remarks`. Post-MBBS DNB (Sadar Hospital, RINPAS, SNMMCH DNB) → section dnb.
2026 Round 1 provisional (03.11.2026): 110 allotments, 5 in-service, CML 1–303, AIR 1,907–159,060 (110/110 from NBEMS).

## West Bengal (`west_bengal.py`)
    /usr/bin/python3 tools/results/west_bengal.py <result.pdf> <out.json> [--seat-matrix <WB seat rows.json>] [--nbems <neet2026.json>]
WBMCC prints one line per allotted seat: ROUND, ALL INDIA RANK, CHOICE NO., INSTITUTE, COURSE, ALLOTTED QUOTA,
ALLOTTED CATEGORY, CANDIDATE CATEGORY, STATUS — no names or roll numbers. `rank` = `rank_ai` = AIR.
Quota: Open → State Quota, In-service → State Quota-Inservice, Private Management → Management Quota, In-service DNB
→ DNB Quota-Inservice (NBEMS courses, section dnb). Checks: AIR strictly ascending, allotted ≤ seat-matrix seats per
college × course (all quotas together).
2026 Round 1 provisional (published 04.11.2026; PDF dated 3 Nov): 918 allotted (859 MD/MS, 25 Diploma, 34 DNB), 43
institutes, 352 college × course groups within the 1,459-seat matrix.

## Karnataka (`karnataka.py`)
    /usr/bin/python3 tools/results/karnataka.py <allotment.pdf> <out.json> [--seat-matrix <KA seat-matrix dump.json>]
KEA "PG NEET-2026 MEDICAL (MD/MS) PROVISIONAL ROUND SEAT ALLOTMENT": one 8-column table (SL.NO, All India Rank, Course
Code, College, Course Name, Allotted Category, Course fees, Status) — no names or roll numbers; the fee is checked but
not stored. Authority `kea`. `rank` = `rank_ai` = the printed AIR (strictly ascending).
- **Quota** from the seat-type letter of the course code (`M01GC5` = college M01 · seat G · course C5): G → Government
  Quota, P → Private Quota - GMP (GMP/GMPH) / - Open (OPN) / - Minority (ME MEH MM MMH MU MC MA RC1-3), Q → Management
  Quota (MNG), N → NRI Quota; a category outside its seat type stops the run.
- **Category** in the 2025 KEA code spellings (GM, 2AG, 1G, STG; …H = Kalyana Karnataka; P prefix = PwD). KEA's new
  S1-S4 codes = SC-A, SC-B, SC-C, SC-C (20%) — the only order that fits the seat matrix (others overshoot 61-213
  seats) — stored as SC-AG / SC-BH … and `SC-C (20%)G` / `SC-C (20%)H` (no 2025 equivalent).
- `--seat-matrix`: every allotment within its college × course × quota × category seats of the 2026 KEA matrix (strict).
2026 Round 1 provisional (05.11.2026): 3,272 seats (3,266 MD/MS, 6 Diploma, no DNB / in-service lines), 65 colleges;
Government 1,574 (RK 1,307, KK 267) · GMP 577 · Open 443 · Minority 440 · Management 219 · NRI 19; 863 college × course
(2,481 college × course × quota × category) groups all within the matrix.

## Maharashtra (`maharashtra.py`)
    /usr/bin/python3 tools/results/maharashtra.py <selection.pdf> <cetcell_mh_common_provisional.json> <cetcell_mh_inservice_provisional.json> <out.json> [--seat-matrix <MH seat rows.json>]
State CET Cell "PROVISIONAL SELECTION LIST FOR NEET(PG)-CET 2026" (MD/MS/Diploma, Round 1.0): a fixed-width list, one
line per merit-list candidate in SML order — allotted (Code CCSSq : subject, college, city, quota, remark) or "Choice Not
Available" (counted, skipped). Authority `cetcell_mh`. FormNo and Name are cut out of each line as it is read.
- **Ranks:** `rank` = SML (state merit no.), `rank_ai` = AIR from the final provisional common merit list by SML; the
  printed Cat. must equal the merit list's category for that SML (≤ 3 differences tolerated + listed), in-service
  candidates (`I`/`IB`) are checked against the in-service list (soft, listed).
- **Quota/category** (2025 spellings): state categories → `State Quota` (VJA→VJ, NTB/NTC/NTD→NT1/NT2/NT3, `PH X` → `X-PH`,
  earmarked `EMX` → X, ORPHAN → `Orphan`, Orphan-C OBC → `OBC-Orphan`); `IS X` → `State Quota-Inservice` / `IS-X`;
  MINORITY → `State Quota-Minority` / `Minority`; `I.Q.` → `Institutional Quota` / `IQ` (incl. the Vikhe Patil + NKP
  Salve seats, code suffix A, that the 2026 seat matrix files as All India Quota — 2025 had them as Institutional);
  NRI → `NRI Quota` / `NRI`. Diplomas (LTMC only) → section `diploma`.
- **Checks:** SrNo 1..N, SML ascending, form numbers in text = lines, code ↔ printed college/subject, quota ↔ seat type,
  PH/NRI/minority/in-service seats only to such candidates; `--seat-matrix`: every college × course × quota exists and
  allotted ≤ seats (LTMC diplomas compared all quotas together — the list fills the INS diploma cells from the state pool).
2026 Round 1 provisional (05.11.2026): 6,885 lines — 2,112 allotted (2,102 MD/MS, 10 Diploma), 4,773 Choice Not
Available; State 1,676 · Institutional 356 (96 AIQ-coded) · In-service 52 · Minority 22 · NRI 6; 675 college × course
groups all within the 2,759-seat matrix (no category cell over); rank_ai 2,112/2,112; Cat. = merit list 6,884/6,885
(SML 2103 SEBC vs OPEN); in-service 63/64 on the in-service list (SML 5611 not).
