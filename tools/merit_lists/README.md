# State merit lists → rank bridge (Mac-side)

Each state merit list is read into rank pairs `{roll, air, state_rank, score, category, quota}`. The readers never
output names, parent names, DOB, gender or application IDs. The rows are posted with
`POST /api/pg/state-merit/ingest` (X-News-Key, mode start → finish) into `pg_state_merit`.

Every printed All-India rank is checked against the NBEMS master result (`pg_neet_result`, loaded from NBEMS's
published result PDF), matching by roll number. When a list prints only roll numbers (Tamil Nadu), the All-India
rank is filled in from that result.

2026 Round 1, all loaded 2026-10-30 with 0 AIR mismatches:
- MP: registered merit list, revised (4,777)
- Rajasthan: R1 state merit, revised provisional (3,165)
- UP: MD/MS/Diploma (6,084) and DNB (96)
- Kerala: final (5,607; 58 withheld rows left out)
- Jharkhand: revised final (305)
- Punjab: main (1,449) and NRI (7)
- Tamil Nadu: GQ (7,963, incl. addendum) and MQ (3,643)
- Gujarat: general (6,095)

2026 Round 1, read 2026-11-01 (outputs written, NOT yet posted):
- Maharashtra (`cetcell_mh`, `read_cetcell_mh.py <pdf>`, auto-detects common vs in-service): Common Provisional SML
  dated 30/10/2026 (7,225; 14 rows printed without an SML number left out; 0 AIR mismatches) and In-Service 20% quota
  SML (65; 1 un-numbered row left out). The in-service "rank" column is CET Cell's rank of the WEIGHTED score
  (NEET x (1 + incentive %), tie-split like 108331.2), not the AIR, so AIR is filled from NBEMS by roll there.
- Andhra Pradesh (`ntruhs`, `read_ntruhs_ap.py <pdf>`, auto-detects non-service vs in-service): CQ Provisional Merit
  List, Non-service (4,131) and In-service (363); state rank = Sl.No; 0 AIR mismatches. Local area (AU/SVU/APNL) is
  counted in checks only. Both write to the nov1/ml1 scratchpad by default (`--out DIR` to change).

Added 2026-11-01 (built, not yet posted; outputs in the session scratchpad `nov1/ml2/`):
- Chhattisgarh (`dme_cg`): Round 1 provisional merit list (874) - `read_dme_cg.py <pdf>`. No names printed.
- Odisha (`ojee`): revised merit list after grievances (31 Oct file), four separate lists - `read_ojee.py <revised.pdf>
  [<earlier.pdf>]`: Direct (1,215), In-service (316, quota `In-service`), DNB (125), Post-MBBS Diploma (187). Rank =
  the printed `Rank-UR` column (the common merit rank every candidate gets); score = New Score (NEET + weightage %).
  The rejected-applications pages are skipped. Versus the 30 Oct file only the Diploma list changed (one candidate
  added at rank 25, ranks below moved down by one).
- Tamil Nadu GQ re-built with addenda A and B of 31 Oct (7,968 rows): `sm4_tn_build.py --gq-only`. Addenda are
  applied in order; B repeats A's four rows (logged as duplicates) and adds one row and two community corrections.
  `--first-addendum-only` reproduces the 30 Oct load exactly.
- Tamil Nadu special-quota eligibility lists (CMC 20% GQ; Christian minority, Telugu minority, NRI MQ) print only
  S.No / application no. / name in application-number order - no rank of their own, so no list is made.
  `sm4_tn_special.py` counts (in memory, by application no.) how many are already in the GQ / MQ rank lists.
- Tamil Nadu 2025-26 (previous session, for the 2025 bridge): GQ (6,989) and MQ (3,912) provisional rank lists of
  8 Nov 2025 (Medical Dialogues copies) - `sm4_tn_2025.py [<gq.pdf> <mq.pdf>]`, writes `dmer_tn_gq_2025.json` /
  `dmer_tn_mq_2025.json`. Same reader as 2026 (`sm4_tn.read`) with 2025 column positions; AIR filled from the NBEMS
  2025 result (`neet2025.json`) by roll; all rolls found, all scores agree. Built 2026-11-01, not yet posted.

Set `MERIT_OUT=<dir>` to choose where the JSON files are written (default: the old scratchpad folder).
`sm4_tn.py` is the shared Tamil Nadu page reader used by `sm4_tn_build.py` and `sm4_tn_special.py`.

The readers were written against the 2026 files and keep their scratchpad paths at the top; adjust the paths for
a new round. `merit_common.py` / `sm4_common.py` hold the NBEMS checks. Ties are kept as published: TN "1980A"
insertions and Gujarat half merit numbers keep their whole-number base.

## Goa (`read_dte_goa.py`) — 2026-11-03
DTE Goa "PG DEGREE ADMISSION 2026 - PROVISIONAL MERIT LIST" (29.10.2026): merit no. + NEET PG rank printed, no roll →
air = printed rank (all 161 found in NBEMS), state_rank = merit no. Merit 157-161 sit after 156 out of AIR order
(pending certificates) — stored as printed. Loaded: 161 rows, list 'PG Degree Admission 2026 Provisional Merit List'.

## Assam (`read_dme_assam.py`) — 2026-11-03
DME Assam provisional merit list (79 pages, text layer — not scanned): roll / category / score / AIR, no printed state
rank → state_rank = list position. Applies the inclusion notice (17.10, '200-A') and the revised-merit-position notice
(29.10, 3 in-service candidates '87-A' / '257-A' / '481-A'; n-A stored as n). 3,583 lines: roll, AIR and score = NBEMS
on every line; loaded 3,584 rows.

## Tamil Nadu addenda 02.11.2026 (`sm4_tn_build.py`)
GQ addendum 5963A and the first MQ addendum 898A (one added candidate each) → GQ 7,969, MQ 3,644; nothing else changed.

## Telangana (`read_knruhs_tg.py`) — 2026-11-08
KNRUHS "Medical PG Degree/Diploma admissions under Competent Authority Quota AY 2026-27 — Provisional Merit List of
registered candidates" (dated 07.11.2026, 104 pages): `read_knruhs_tg.py <pdf> [--out DIR]` → `knruhs_cq_provisional.json`.
One common list (S.No, Rank = AIR, Roll No, Score, Name, Gender, Category, Local, Minority, Service, Remarks); reads
only S.No / Rank / roll / score / category / local / minority / service. state_rank = S.No; in-service ('S') rows get
quota 'In-service', non-service ''. 3,518 rows = the announced total; AIR printed on every row, AIR and score
monotonic. Local '-' = the 171 non-local candidates listed "as per the directions of the Hon'ble High Court".

## Himachal Pradesh (`read_amru_hp.py`) — 2026-11-08
AMRU "Provisional Merit list of MD/MS/DNB 1st Round Counselling 2026" (notice 07.11.2026, 50 pages; page 1 = notice):
`read_amru_hp.py <pdf> [--out DIR]` → `amru_hp_r1_provisional.json`. ONE merit list across all quotas (merit no. 1..795)
with quota per row: HP Direct / In-service / Management / NRI. state_rank = merit no.; air = printed All India Merit
Rank; score = "NEET Score + Service Incentive" (the merit basis; checked = NEET x (1 + incentive %)), so AIR is out of
order only where the incentive lifts in-service rows. Application no. and name are never read.

## Puducherry (`read_centac_py.py`) — 2026-11-08
CENTAC "Draft Merit list of PG NEET Medical (M.D./M.S.) courses (2026-2027)", published 06-11-2026. The web page
(`htmlpages/2026/PgMedical_2026/Draft_merit_list.html`) links each list as a Google-Drive PDF. `read_centac_py.py
<gq_all.pdf> <mq_all.pdf> [--out DIR]` → `centac_gq_draft.json` (GQ-ALL, 298, quota 'GQ', category like 'MBC/FF') and
`centac_mq_draft.json` (MQ-ALL, 851, quota 'MQ', AIQ category). state_rank = SL NO; AIR printed on every row. The
column headed "NEET PERCENTILE" is the NEET score. Words are used, not find_tables (it misses every other striped row).
The FF (21) / PwD (1) / ESM (4) / MQ-Telugu (3) sub-lists are subsets of GQ-ALL / MQ-ALL (the reader refuses them);
the "Overall list of candidates applied" (1,250, AIR order, no merit rank; 150 are in neither list, 71 of them below
the 226 cut-off) is not a merit list and is not read. authority_code is `centac` (pg_admin/authorities.py).
