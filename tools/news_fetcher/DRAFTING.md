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
dated step for EVERY round (this fills the authority's calendar automatically when posted):

```json
"events": [
  {"round": "Round 1", "event": "registration",  "label": "Registration & fee payment",
   "start": "2026-10-12", "end": "2026-10-21", "time": "till 12 noon on 21 Oct", "quote": "exact text"},
  {"round": "Round 1", "event": "choice_filling", "label": "Choice filling", "start": "2026-10-13", "end": "2026-10-22", "time": "till 10 AM", "quote": "..."},
  {"round": "Round 1", "event": "choice_locking", "label": "Choice locking", "start": "2026-10-21", "end": "2026-10-22", "time": "4 PM 21 Oct – 10 AM 22 Oct", "quote": "..."},
  {"round": "Round 1", "event": "result",         "label": "Result",          "start": "2026-10-24", "end": "", "time": "", "quote": "..."},
  {"round": "Round 1", "event": "reporting",      "label": "Reporting / joining", "start": "2026-10-26", "end": "2026-11-02", "time": "", "quote": "..."},
  {"round": "Round 2", "event": "registration",  ...}
]
```
- `event` is one of: registration | verification | choice_filling | choice_locking | payment |
  seat_processing | result | reporting | other. `round`: "Round 1", "Round 2", "Round 3", "Round 4",
  "Stray", "Mop-up", "Special", or "" if not round-specific (e.g. session start → event "other").
- `start` / `end` = YYYY-MM-DD; `end` only for a range. Only dates the notice states — never guess.
- One entry per step per round. Omit `events` if the notice has no schedule.

Category `bulletin` = the authority's Information Bulletin / Prospectus / Brochure for the year
(the reviewer will also save it as that authority's main brochure document).

Rules for `dates`:
- `round`: exactly one of "Round 1", "Round 2", "Round 3", "Round 4", "Mop-up", "Stray", "Special Stray",
  or omit it if the notice doesn't say. `dates` holds ONE round (the earliest upcoming); every other
  round's dates go in `events` (the calendar), never extra keys here.
- Include a key ONLY if the notice explicitly states that date. Omit the key otherwise —
  never guess, never infer from another round or another year.
- `quote` = the exact text from the notice that shows it (≤300 chars), so the reviewer can
  verify in seconds. `time` is optional.
- If the notice gives a schedule for several rounds, use the earliest upcoming round's dates
  and mention the other rounds in the article.
- Indian notices often write dates as DD-MM-YYYY or DD/MM/YYYY — convert carefully to YYYY-MM-DD.

If a PDF can't be read (scanned image you can't make out, corrupt), still write a draft from
the title with `"dates": {}` and say in `summary` that the notice should be checked manually.
