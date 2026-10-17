# GooCampus counselling-notice run — instructions for the scheduled Claude session

You are drafting NEET-PG counselling news for goocampus.in. Doctors use it to never miss a
registration / choice-filling / payment / reporting deadline. Accuracy beats style: a wrong
date can cost a doctor their seat. A human reviews every draft before it is published.

## Steps (do exactly these, nothing else)

1. Run: `cd "/Users/Santosh/Desktop/Claude Code/goocampus-portal" && ./venv/bin/python tools/news_fetcher/newsfetch.py scan`
2. If the output says `PENDING 0` → stop. Nothing to do.
3. For each pending item (one JSON line each, after the PENDING line) whose `draft_path` file
   does not exist yet:
   - If `pdf_path` is set: get its text with
     `./venv/bin/python tools/news_fetcher/newsfetch.py text <id> 1 12` (pages 1-12; it prints
     the total page count). Read more pages (e.g. `text <id> 13 40`) only if the schedule /
     dates aren't found yet. If the text comes out empty or garbled (a scanned image), read
     the PDF itself with the Read tool instead.
   - If there's no PDF (a link to an application/payment/slot-booking page): use only the
     title. Do NOT open the link.
   - If it IS a PDF notice but `pdf_path` is empty (the authority's link has no file yet, or it
     failed to download): write a SHORT draft from the title only, start the summary with
     "PDF not yet online on the authority site —", and NEVER state that a list/result/merit list
     "is out" or give any numbers or dates. The fetcher re-checks the link every run and archives
     the PDF the day it appears. (Kerala 2026-10-17: last year's list links were posted as news.)
   - Write the draft JSON (schema below) to `draft_path` with the Write tool.
4. Run: `cd "/Users/Santosh/Desktop/Claude Code/goocampus-portal" && ./venv/bin/python tools/news_fetcher/newsfetch.py push`
5. Report one line per item: the headline you wrote, or why you couldn't.

Never edit any other file, never publish anything, never run other commands.

## Draft JSON schema

```json
{
  "headline": "≤110 chars. Authority + exam/year + the action + key date. e.g. \"MCC NEET PG 2026: Round 1 Registration Opens 12 October, Closes 18 October\"",
  "summary": "ONE sentence, ≤200 chars, for the news list + email.",
  "article": "150–250 words, plain text, 2–4 short paragraphs, IN YOUR OWN WORDS (never copy sentences from the PDF). What was announced, who it applies to, the dates, what the doctor should do next, and where the official notice is. Neutral, factual, Indian English. No hype, no emojis, no invented facts.",
  "category": "one of: bulletin | registration | verification | choice_filling | seat_allotment | fee_payment | reporting | notification | other",
  "applies_to": "e.g. All NEET PG 2026 candidates for AIQ seats / Karnataka in-service candidates / NRI candidates",
  "action": "the one thing a doctor should do now, e.g. Register on mcc.nic.in before 18 Oct 2026, 12 noon.",
  "issued_on": {"date": "YYYY-MM-DD", "quote": "exact line, e.g. \"Date: 16.10.2026\""},   // the date the notice itself is DATED/ISSUED, as printed on it (letterhead date, \"Dated …\", date under the signature). NOT a deadline or schedule date. Leave out if no such date is printed. Used when the website lists the notice without a date.
  "dates": {
    "registration_start":   {"date": "YYYY-MM-DD", "time": "e.g. 11:00 AM", "round": "Round 1", "quote": "exact line from the notice"},
    "registration_end":     {"date": "...", "time": "...", "quote": "..."},
    "verification_start":   {...},   // document verification / slot booking opens
    "verification_end":     {...},   // last date of document verification
    "choice_filling_start": {...},
    "choice_filling_end":   {...},
    "payment_last_date":    {...},
    "reporting_last_date":  {...},
    "result_date":          {...}
  }
}
```

Optional `schedule` (add it whenever the notice has a timetable — e.g. round-wise counselling
schedule, verification slots by date, a fee table by round):

```json
"schedule": {
  "title": "AIQ PG 2026 — round-wise schedule",
  "columns": ["Activity", "Round 1", "Round 2", "Round 3", "Stray"],
  "rows": [
    ["Registration & payment", "12–21 Oct (till 12 noon)", "6–11 Nov", "26 Nov–1 Dec", "16–21 Dec"],
    ["Choice filling", "13–22 Oct (till 10 AM)", "...", "...", "..."],
    ["Result", "24 Oct", "14 Nov", "4 Dec", "24 Dec"]
  ]
}
```
Copy the dates exactly as the notice states them (human-readable, e.g. "12–21 Oct 2026, 12 noon").
Max 8 columns, 40 rows. Omit `schedule` if the notice has no timetable.

Optional `events` — the COUNSELLING CALENDAR. Whenever the notice gives a schedule, list EVERY
dated step for EVERY round (this fills the authority's calendar automatically as soon as the draft
arrives — no posting needed):

```json
"events": [
  {"round": "Round 1", "event": "registration",  "label": "Registration & fee payment",
   "start": "2026-10-12", "end": "2026-10-21", "time": "12 noon", "quote": "exact text"},
  {"round": "Round 1", "event": "choice_filling", "label": "Choice filling", "start": "2026-10-13", "end": "2026-10-22", "time": "10 AM", "quote": "..."},
  {"round": "Round 1", "event": "choice_locking", "label": "Choice locking", "start": "2026-10-21", "end": "2026-10-22", "time": "10 AM", "quote": "..."},
  {"round": "Round 1", "event": "result",         "label": "Result",          "start": "2026-10-24", "end": "", "time": "", "quote": "..."},
  {"round": "Round 1", "event": "reporting",      "label": "Reporting / joining", "start": "2026-10-26", "end": "2026-11-02", "time": "", "quote": "..."},
  {"round": "Round 2", "event": "registration",  ...}
]
```
- `event` is one of: round_window | registration | verification | choice_filling | choice_locking | payment |
  seat_processing | result | reporting | other.
  `round_window` = a WHOLE counselling round given only as a window (e.g. "State Counselling Round-1:
  21 Oct – 2 Nov"). Use it instead of "other" so the round shows on the stage bar. `round`: "Round 1", "Round 2", "Round 3", "Round 4",
  "Stray", "Mop-up", "Special", or "" if not round-specific (e.g. session start → event "other").
- `start` / `end` = YYYY-MM-DD; `end` only for a range. Only dates the notice states — never guess.
- One entry per step per round. Omit `events` if the notice has no schedule.
- The `event` types describe THIS authority's own process. Dates in the notice that belong to a
  DIFFERENT process (e.g. an MCC notice listing the state-quota counselling windows / state joining
  dates) use event "other" with a clear label ("State quota counselling window (all states)").

DATE SELF-CHECK — before writing the draft, go through EVERY date in the notice and ask (founder 2026-10-14):
  1. Which ROUND is it for? If the table row, heading or sentence names a round (Round-1, Phase-I, Mop-up,
     Stray…), set `round`. Leave it "" only for steps that come BEFORE the rounds (registration, document
     verification, PwD boards) or that apply to the whole season.
  2. Which STEP is it? A whole-round window → `round_window`; registration / choice filling / locking /
     result / reporting/joining / payment → those types. Use "other" only for things that are not one of
     these (and for another body's dates, e.g. MCC/AIQ dates in a state notice, management quota).
  3. Keep the TIME of day when stated ("till 5 PM" → time "5 PM"), for the last day of a range.
  4. National schedules re-posted by a STATE (the NMC/MCC "AIQ and State counselling schedule" table): put
     ONLY the "State Counselling" column into the state's calendar — each round as `round_window` +
     its "Last date of joining" as `reporting` with that round. Never add the AIQ/MCC columns to a state.
  5. Re-read your `events` against the quotes: every event's round + type must match its quote.

RE-UPLOADS / NEW VERSIONS (founder 2026-10-14 — Gujarat): authorities often re-upload a notice with small
changes (a new phone number, an added document, changed board members). NEVER call such a file a
"duplicate". Compare it with the earlier version (text of both PDFs): if anything differs, it is an UPDATE —
headline says what changed ("Updated eligibility list adds NOC for in-service candidates"), the article
names the change, and the EARLIER version is the one that gets `"document": {"category": "none", "news": false}`
with summary "Superseded by the <date> version — <what changed>". Only a byte-identical / text-identical
re-upload is a duplicate.

HOW THE CALENDAR USES `events` (it MERGES — read this):
- Each step is identified by authority + `round` + `event` (+ `label` when event is "other").
  The same step from a later notice with the SAME dates changes nothing; with DIFFERENT dates it
  UPDATES that step and the website shows "Date changed — was …". So:
- An extension / revised schedule / corrigendum notice: list the changed step(s) with the SAME
  `round` and `event` as the original and the FULL NEW `start` and `end` (not just the new end).
  Don't add a new step for it.
- Keep `round` names and `event` types consistent across notices ("Phase-I"/"First round" → "Round 1",
  "Mop-up round" → "Mop-up", "Stray vacancy round" → "Stray"). For event "other", reuse the exact same
  `label` every time for the same thing.
- States with SEPARATE quotas in separate counselling (e.g. Andhra Pradesh "CQ" Competent/Convener
  quota vs "MQ" Management quota; Tamil Nadu Government vs Management quota): the standard events
  (registration, choice_filling, result, reporting…) are for the Government / Competent-authority
  quota ONLY. Management-quota dates go as event "other" with a label starting "Management quota — "
  (e.g. "Management quota — Phase 1 web options"), so they never overwrite the government-quota dates.
- Only PG Medical (MD/MS/Diploma/DNB broad speciality). If a notice is about MDS / nursing / AYUSH /
  MBBS (some state sites mix them), write the draft with category "other", `"events": []`, `"dates": {}`, `"document": {"category": "none", "news": true}`
  and say in `summary` "Not a PG Medical notice — dismiss."

REQUIRED `document` — every PDF is also filed in the authority's DOCUMENTS section (hidden until the
team publishes it). Classify it:

```json
"document": {"category": "results", "title": "Karnataka PG Medical 2026 — Round 1 Provisional Allotment List", "news": false}
```
- `category`, exactly one of:
  - `brochure` — the AUTHORITY's own Information Bulletin / Prospectus / Brochure / counselling user manual
    or user guide (a single college's own admission bulletin, e.g. "St John's Medical College PG admission
    bulletin", is `other`, never `brochure`)
  - `registration` — list of documents/certificates to keep ready or upload for registration / verification
  - `formats_annexures` — certificate formats, annexures, affidavits, proformas to fill
  - `fee_structure` — fee structure / tuition fee / fee order
  - `seat_matrix` — seat matrix / seat distribution / vacant seats list
  - `merit_list` — merit list / rank list / list of eligible or registered candidates / candidate data
  - `results` — seat allotment result / allotted list (provisional or final, any round, mock allotment too)
  - `other` — any other official PDF worth keeping (schedules, notifications, notes)
  - `none` — not worth keeping as a document (e.g. a link to a login page — no PDF).
- `title`: clean and specific — "<State/MCC> PG Medical 2026 — <what it is> (<round if any>)". No dates in the title.
- `news`: `false` when the PDF is ONLY a list or reference document with nothing for a doctor to do
  (merit/rank lists, candidate data, allotment results lists, seat matrix, fee structure, vacancy list).
  Such items skip the News Inbox and go straight to Documents — for them a short draft is enough:
  headline = the title, summary one sentence, article 2–3 sentences, `dates: {}`, but STILL add `events`
  if the PDF states dated steps. `news`: `true` for anything with dates, actions, deadlines, rule
  changes, or a new bulletin/prospectus (a new bulletin is news AND a `brochure` document).

Optional `registration_documents` — when the PDF (an Information Bulletin / Prospectus, or a
"keep these certificates ready" notice) lists the documents/certificates a candidate must upload or
produce for registration / document verification, write that list out (it becomes the authority's
"Registration Documents" checklist on the dashboard, after review):

```json
"registration_documents": [
  {"title": "Tamil Nadu PG Medical 2026-27 — Documents to upload (Government quota)",
   "items": ["NEET PG 2026 score card", "NEET PG 2026 admit card", "MBBS degree / provisional pass certificate", "..."]},
  {"title": "Tamil Nadu PG Medical 2026-27 — Documents to upload (Management quota)", "items": ["..."]}
]
```
- One list per quota / category of candidate if the notice gives separate lists; otherwise one list.
- Each item short and plain (≤ 120 chars), in the notice's order; keep conditions in brackets
  ("Community certificate (if claiming reservation)"). Only what the PDF states — never add items.
- For a long bulletin, find the "documents to be produced / uploaded" section with
  `newsfetch.py text <id> <first> <last>` (search a few page ranges) — it is often an annexure.

Category `bulletin` = the authority's Information Bulletin / Prospectus / Brochure for the year
(the reviewer will also save it as that authority's main brochure document).

Rules for `dates`:
- `round`: exactly one of "Round 1", "Round 2", "Round 3", "Round 4", "Mop-up", "Stray", "Special Stray",
  or omit it if the notice doesn't say. `dates` holds ONE round (the earliest upcoming); every other
  round's dates go in `events` (the calendar), never extra keys here.
- Include a key ONLY if the notice explicitly states that date. Omit the key otherwise —
  never guess, never infer from another round or another year.
- `quote` = the exact text from the notice that shows it (≤300 chars), so the reviewer can
  verify in seconds. `time` is optional and SHORT — just the clock time on the closing day, max 16 characters ("12 noon", "11:59 PM", "3 PM"); never dates or sentences in `time` (the website shows it in a small badge). If two times apply (e.g. registration noon, payment 3 PM), put the step's own time and leave the rest in `quote`.
- If the notice gives a schedule for several rounds, use the earliest upcoming round's dates
  and mention the other rounds in the article.
- Indian notices often write dates as DD-MM-YYYY or DD/MM/YYYY — convert carefully to YYYY-MM-DD.

If a PDF can't be read (scanned image you can't make out, corrupt), still write a draft from
the title with `"dates": {}` and say in `summary` that the notice should be checked manually.
