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

The readers were written against the 2026 files and keep their scratchpad paths at the top; adjust the paths for
a new round. `merit_common.py` / `sm4_common.py` hold the NBEMS checks. Ties are kept as published: TN "1980A"
insertions and Gujarat half merit numbers keep their whole-number base.
