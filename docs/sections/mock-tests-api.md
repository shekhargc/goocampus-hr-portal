# Mock Tests — API contract for goocampus.in (exam screen, My Mocks)

The **portal** (goocampus.org, `exam_engine/doctor_api.py`) is the exam engine. It owns the clock, the answers, the scoring and who may take what. **goocampus.in** draws the screens.

The browser never talks to the portal directly, except to load question pictures. It calls goocampus.in's own API routes, and those forward server-side with the usual headers:

```
X-PG-Key: <PG_API_KEY>               (server-side only, never in the browser)
Authorization: Bearer <doctor token> (the 30-day token from OTP login)
Content-Type: application/json
```

Errors always look like `{"ok": false, "error": "<code>", "message": "<plain words to show>"}`. The common codes:

| Status | Codes |
|---|---|
| 401 | `unauthorized`, `no_token`, `invalid_token` |
| 403 | `package_required`, `not_published` |
| 404 | `not_found` |
| 409 | `no_attempts_left`, `not_allowed` |
| 500 | `save_failed` |

All times are UTC, in ISO form (`2026-11-14T04:30:00Z`). **Never run the countdown from the device clock alone.** Use `remaining_seconds` from the latest response and count down locally between responses. Every save returns fresh numbers, so drift is corrected within seconds.

---

## 1. `GET /api/pg/mocks`: the doctor's mocks (My Mocks page + dashboard tile)

```json
{"ok": true, "mocks": [
  {"id": 12, "title": "Free Sample — Grand Test", "kind": "full", "kind_label": "Full mock", "subject": "",
   "description": "…", "is_free_sample": true,
   "total_questions": 180, "total_minutes": 210, "max_marks": 720, "sections": 5,
   "access":   {"allowed": true, "via": "free_sample", "reason": null},
   "attempts": {"used": 0, "allowed": 1, "open_attempt_id": null, "last": null}},
  {"id": 13, "title": "Grand Test 1", "kind": "full", …,
   "access":   {"allowed": false, "via": null, "reason": "package_required"},
   "attempts": {"used": 0, "allowed": 1, "open_attempt_id": null, "last": null}}
]}
```

Only **published** mocks are listed. The free sample comes first.

What each card shows:

| Situation | Card shows |
|---|---|
| `attempts.open_attempt_id` is set | **Resume** (time is running) |
| `attempts.last` is set and `used >= allowed` | **View result**: score / max_score |
| `access.allowed` is true | **Start** |
| `access.reason == "package_required"` | Locked, with **Unlock with a package** (the store arrives in step 7) |

`kind` is one of `full`, `subject` or `mini`.

## 2. `POST /api/pg/mocks/<paper_id>/start`: start or resume

Body (optional): `{"client_info": "<user agent / device>"}`.

If the doctor already has an open attempt on this mock, the **same attempt is resumed** on any device. Otherwise a new one starts and **the clock starts now**. Show the instructions page and its "I am ready to begin" button **before** calling this.

The response is the **attempt state** (below). Errors: `package_required` 403, `no_attempts_left` 409, `not_found` 404.

## 3. `GET /api/pg/mocks/attempts/<attempt_id>`: the attempt state

Call it when the exam page loads or reloads, after a save says `section_changed: true`, and after reconnecting.

```json
{"ok": true, "attempt_id": 881, "status": "in_progress", "submit_reason": "",
 "server_time": "2026-11-14T04:30:05Z",
 "paper": {"id": 12, "title": "…", "kind": "full", "total_questions": 180, "total_minutes": 210,
           "max_marks": 720, "marking": {"correct": 4, "wrong": -1, "unattempted": 0},
           "section_lock": true, "can_end_section_early": false},
 "sections": [
   {"code": "A", "name": "Section A", "questions": 36, "minutes": 42, "status": "closed",  "answered": 30, "marked": 2, "visited": 36},
   {"code": "B", "name": "Section B", "questions": 36, "minutes": 42, "status": "current", "answered": 4,  "marked": 1, "visited": 6},
   {"code": "C", …, "status": "upcoming", …}],
 "total_remaining_seconds": 9871,
 "current_section": {
   "index": 1, "code": "B", "name": "Section B",
   "started_at": "…", "ends_at": "2026-11-14T05:12:00Z", "remaining_seconds": 2511,
   "questions": [
     {"item_id": 5521, "number": 1,
      "stem": "A 28-year-old woman …",          // plain text; keep line breaks (white-space: pre-line)
      "images": [{"url": "https://…", "width": 960, "height": 540}],
      "options": [{"key": "C", "text": "Vagal manoeuvres"}, {"key": "A", "text": "Adenosine"}, …],
      "response": {"chosen": null, "marked": false, "visited": true, "time_ms": 41200},
      "palette": "not_answered"}
   ]}}
```

- **Only the current section's questions** are sent. Closed sections can never be reopened (NBEMS rule), and later sections can't be previewed.
- **Options:** show them **in the order given**, labelled A, B, C, D by position. Send back the option's **`key`**, not the label. When shuffling is switched on, the key and the label differ.
- **Pictures:** `images[].url` loads directly in an `<img>` tag; no headers needed. It's a signed link valid for about 6 hours, and a fresh `GET` state gives fresh links.
- **Palette values:**

| Value | Colour (NBEMS) |
|---|---|
| `not_visited` | grey |
| `not_answered` | red / orange |
| `answered` | green |
| `marked` | purple |
| `answered_marked` | purple with a green tick, and it **is** scored |

  Compute the palette from your local `response` as the doctor works; the server value is the starting point.
- When `status` is `"submitted"`, there's no `current_section`. Instead there's a `result` (step 6 makes the result page richer):

```json
"result": {"score": 412, "max_score": 720, "correct": 115, "wrong": 48, "unattempted": 17, "submitted_at": "…"}
```

## 4. `POST /api/pg/mocks/attempts/<attempt_id>/save`: autosave

```json
{"responses": [
   {"item_id": 5521, "chosen": "C", "marked": false, "visited": true, "time_ms": 52000, "client_ts": 1763094605123}
 ],
 "events": [ {"kind": "tab_hidden", "client_ts": 1763094600000, "detail": ""} ]}
```

- **`chosen`** is the option `key`, or `null` to clear the answer.
- **`time_ms`** is the **total** time spent on that question so far, not the increment.
- **`client_ts`** is `Date.now()` at the moment of the change. The newest answer wins across devices.
- Send **only changed questions**. Batching is fine, up to 500 responses per call.
- **`events`** are flags only and never disqualify. Allowed kinds: `tab_hidden`, `tab_visible`, `fullscreen_exit`, `fullscreen_enter`, `offline`, `online`, `resumed`, `copy_attempt`, `right_click`, `devtools`. Anything else is ignored.

Response:

```json
{"ok": true, "status": "in_progress", "saved": 1, "rejected": [{"item_id": 77, "why": "section_closed"}],
 "cur_section": 1, "section_code": "B", "section_changed": false,
 "section_remaining_seconds": 2490, "total_remaining_seconds": 9850, "server_time": "…"}
```

- **`section_changed: true`** means the section's time ran out on the server. Call `GET` state, show the next section, and show a short notice: "Section A has ended."
- **`status: "submitted"`** means time is up. Go to the result screen.
- `rejected[].why` is one of `section_closed`, `bad_option`, `not_in_paper` or `bad_item`. Drop those from the local queue; resending won't help.
- Answers saved **up to 20 seconds after** a section or the whole paper ends still count, which covers network delay.

**Save cadence:**
- within about 2 seconds of any change (debounce);
- immediately on Save & Next, Mark for Review, Clear and section change;
- plus a heartbeat every 30 seconds while the page is open (with an empty `responses` list if nothing changed).

## 5. `POST /api/pg/mocks/attempts/<attempt_id>/next-section`

This finishes the current section early. The body may carry the last `responses`. It is only allowed when `paper.can_end_section_early` is true (subject and mini tests). For NEET PG full mocks it returns 409 `not_allowed`, because each section runs its full 42 minutes. On the last section, it submits. It returns the new state.

## 6. `POST /api/pg/mocks/attempts/<attempt_id>/submit`

The body may carry the final `responses` and `events`. The attempt is submitted (`submit_reason: "doctor"`), scored, and the state with `result` is returned. **Always confirm first**, showing the counts: "You have answered 140, marked 12, not visited 8. Submit?" If time runs out, the server submits by itself (`submit_reason: "time_up"`), **even if the doctor is offline**. A background job does it within about 2 minutes.

---

## The exam screen: required behaviour (NBEMS computer-based-test look)

1. **Instructions page first.** Show the exam pattern (5 sections × 36 questions, 42 minutes each, +4 / −1, no going back to a closed section) and the palette legend, then an "I have read the instructions" tick and **Start**. Call `start` only on Start.
2. **Layout like the NBEMS screen:**
   - header: the doctor's name as **"Dr. <name>"**, the section name, and the section timer (mm:ss, counting down);
   - one question per screen, with pictures under the question text;
   - options as radio buttons;
   - a question palette on the right with the five colours and a legend with counts;
   - the section tabs, with closed sections shown as locked.
3. **Buttons:**
   - **Save & Next**;
   - **Mark for Review & Next** (keeps any chosen answer, giving `answered_marked`);
   - **Clear Response** (sets `chosen: null`);
   - **Back** / **Next**;
   - **Submit** (always with a confirm).

   Clicking a palette number jumps to that question and marks it `visited`.
4. **Timer:** take `remaining_seconds` from the server and count down locally. At 0:
   - call `GET` state;
   - if the next section is open, switch to it with a notice;
   - if the paper ended, show "Time is up. Your answers have been submitted" and the result.

   Never let the doctor go back to a closed section.
5. **Never lose an answer:**
   - write every change to `localStorage` under `ex_attempt_<id>` first, then queue it for save;
   - on a network error, keep the queue, show a small "Offline — answers saved on this device" badge, and retry with backoff;
   - on reload or another device, `GET` state and then merge: for each question, keep whichever of local and server has the newer `client_ts`, and re-send the local ones that are newer.
6. **Light anti-malpractice (flags only):**
   - ask for full screen on Start;
   - send `fullscreen_exit` / `fullscreen_enter`, `tab_hidden` / `tab_visible` (Page Visibility API) and `offline` / `online` as events;
   - optionally disable right-click and copy and send those as events;
   - never block, warn harshly or auto-submit because of them. A gentle one-line notice is fine.
7. **Mobile:** works on a phone (palette as a slide-up drawer), but recommend a laptop on the instructions page, since the real exam is on a desktop.
8. **Light pages, because thousands of saves may arrive in a busy hour:**
   - no polling faster than the 30-second heartbeat;
   - only send changed questions;
   - load pictures lazily.

## Pages to add on goocampus.in

| Page | Uses | Notes |
|---|---|---|
| **My Mocks**: dashboard tile + list page | `GET /api/pg/mocks` | Tile: the free sample's Start / Resume, plus "N mocks in your package" (step 7). |
| **Free sample entry**: a public "Try a free NEET PG mock" card / landing | login → `GET /api/pg/mocks` → the free sample | One full 180-question mock with full results. |
| **Instructions → Exam screen** | `start`, state, `save`, `next-section`, `submit` | As above. |
| **Result**, basic for now | state `result` | Step 6 adds rank, percentile, subject-wise analysis, solutions, predicted NEET rank and colleges. |
| **Package store** | step 7 | Packages: Starter 5 mocks ₹999 · Standard 15 + 19 subject tests ₹2,499 · Pro 30 + subject + mini ₹3,999 (incl. GST). |

**Testing:** on staging, make a team account (`pg_users.is_team_member = 1`). It can take every published mock. Normal accounts can take only the free sample until packages are wired in step 7.
