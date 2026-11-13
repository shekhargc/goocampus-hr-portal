# Mock Tests (NEET PG) — exam engine

Founder-approved brief: `~/Desktop/Claude Code/NEET_PG_Mock_Platform_Brief.md`.

**Decisions (founder, 13 Nov 2026)**
- Practice mocks, taken anytime from a purchased package; one free full sample mock. Fixed-date all-India mocks may come later.
- Packages (prices include GST, valid until NEET PG 2027):
  - Starter: 5 full mocks, ₹999
  - Standard: 15 full mocks + 19 subject tests, ₹2,499
  - Pro: 30 full mocks + subject tests + mini tests, ₹3,999
- The free mock is a full 180-question mock with full results: score, rank, subject-wise analysis, solutions, predicted rank and college list.
- **Runs inside the portal** (no new Render cost). The exam screen will be on goocampus.in (Next.js). The engine is kept self-contained:
  - its own `exam_engine/` folder;
  - its own `ex_*` tables;
  - `tenant_id` on every row;
  - no joins into portal tables.

  So it can move to its own service and database if load ever needs it.

## Build order (from the brief)
1. Competitor research and packages: **done**.
2. Decisions: **done**. Launch date still to come.
3. Question importer: **done**, on staging.
4. Question bank and paper builder: **done** (see below).
5. Exam player (NBEMS style).
6. Scoring, results and rank.
7. Packages, payments and the free sample.
8. Admin dashboard.
9. Load test and dry run.

## Step 3 — question import (`/admin/pg/mocks/import`, admin only)

```mermaid
flowchart LR
  U[Upload .docx / typed .pdf / .xlsx] --> S[(R2: original file)]
  U --> T[background thread: store.process_batch]
  T --> P[importer.parse_file → layout.parse_stream]
  P --> C[checks.check_batch → flags per question]
  C --> DB[(ex_questions = draft)]
  DB --> R[Review screen: compare with PDF page, fix, crop / upload pictures]
  R -->|no red problems| A[approved]
  R --> X[rejected]
```

**Readers.** Each reader turns its file into one stream of lines and images, which `layout.py` reads.
- `docx_reader.py`:
  - reads paragraphs and table cells in document order;
  - picks up pasted pictures in place;
  - rebuilds Word's automatic numbering, so "A." / "1." labels added by a list are not lost.
- `pdf_reader.py` (pypdfium2, typed PDFs only):
  - reads line text and position;
  - drops running headers and footers (repeated at a page edge on 3+ pages and never mid-page);
  - cuts embedded pictures from the rendered page.
  - Diagrams drawn as lines are not "pictures" inside a PDF; the team crops those on the review screen.
  - A scanned PDF is refused with a plain message.
- `xlsx_reader.py`: one row per question; headers are matched loosely; text only.

**Layout recognised**
- `Q12.` or `Q12  SURGERY / RADIOLOGY` (subject tags) or `12.`
- An optional `IMAGE FINDING` box.
- Options `A.`–`D.`, or `1.`–`4.` (a ✓ / (correct) / leading `*` marks the key).
- `Answer: C`, or `ANSWER` followed by `C. …` on the next line.
- `Explanation:`, or the boxes HOW TO SOLVE / DEEP-DIVE / PATTERN / KEY FACT.
- `Subject:` and `Topic:`.
- A picture before the answer belongs to the question; a picture after it belongs to the explanation.

**Check report** (`importer/checks.py`). Red problems block approval:
- no question text;
- not exactly 4 options, or an empty option;
- no answer;
- the ✓ and the Answer line disagree;
- the question is built on an image but has none;
- subject not recognised;
- repeated in the file, or already in the bank;
- a picture format browsers can't show (EMF/WMF).

Warnings:
- the question mentions an image but has none;
- subject taken from the second tag;
- no explanation;
- doubled words;
- two options with the same text.

File-level notes: missing or repeated question numbers, how the correct answers are spread across A–D, and skipped index entries.

**Subjects.** NEET PG's 19 subjects live in `ex_subjects`. Specialities are mapped to subjects in `ex_subject_aliases` (Cardiology → Medicine, Urology → Surgery, etc.).
- Oncology, Genetics and Hematology are deliberately left for the team to decide.
- A choice made on the review screen is remembered for every later file and applied to the rest of the current file.

**Rules**
- A PDF question needs the "I checked it against the PDF page" tick before it can be approved.
- Word and Excel imports can bulk-approve their questions that have no problems.
- Editing an approved question saves the old version in `ex_question_versions` and sends it back for approval.
- An import can be read again or discarded only while nothing in it is approved or rejected.

**Storage**
- Originals: `exam_engine/t<tenant>/imports/<batch>/…`
- Pictures: `exam_engine/t<tenant>/q/<qid>/<img>.<ext>`
- Page renders: cached under `…/imports/<batch>/pages/<n>.png`

Without R2, the bytes are stored in the row.

**Not done yet:** the AI route for PDFs in other layouts or scanned PDFs (the brief's "AI splits the PDF"). It will be added once a real file needs it. Typed PDFs in a labelled layout don't need AI.

## Step 4 — question bank and papers

**Screens**
- `/admin/pg/mocks/bank`:
  - search and filter: subject, topic, status, used or unused, has a picture;
  - "Type a question" creates a blank draft and opens it in the review screen.
- `/admin/pg/mocks/papers`: create a paper:
  - **Full mock**: the pattern's 5 × 36 questions, 42 minutes per section.
  - **Subject test**: 60 questions, 70 minutes, one subject.
  - **Mini test**: 30 questions, 35 minutes.
  - The subject-test and mini-test sizes are editable defaults.
- `/admin/pg/mocks/papers/<id>` is the builder:
  - Sections with numbered slots; move a question up, down or to another section; remove it.
  - Picker: search approved questions and add the ticked ones to a section.
  - **Auto-fill** follows the subject mix (or the test's own subject). It prefers questions not used in any other paper, can top up from other subjects when one runs short, and spreads subjects round-robin across the sections.
  - The "Ready to lock?" panel shows what blocks locking and what's worth a look. It blocks on:
    - a section not full;
    - a question no longer approved;
    - the same question twice.

    It warns about:
    - a subject mix off by 3 or more;
    - answer-letter skew;
    - questions reused from other locked or published papers.
- `/admin/pg/mocks/papers/<id>/preview`: the whole paper as doctors will see it, with or without answers, printable.
- `/admin/pg/mocks/pattern`: the exam pattern as settings:
  - sections, minutes, marking, options;
  - section rules (no going back, each section runs its full time);
  - subject-test and mini-test sizes;
  - the subject mix for auto-fill.

  Saving creates a new version. Each paper copies the pattern when it is created, so later changes never alter an existing paper.

**Paper lifecycle** (`ex_papers.status`): draft → locked → published → retired.
- **Lock**: every question is frozen into `ex_paper_items.snapshot_json` (text, options, answer, explanation, subject, picture ids, question version). Later bank edits don't change the paper; the builder marks such questions "edited in bank since".
- A picture inside a frozen copy can't be deleted from its question.
- **Unlock**: only while locked, never once published, and never after doctors have attempted it (`attempts_count`, which reads `ex_attempts` once Step 5 adds it).
- Only a draft paper can be deleted.
- Exactly one full mock can be the **free sample** (`is_free_sample`).

**Default subject mix**: `tables.BLUEPRINT_PER_200`, scaled to 180. It is an approximation of recent papers, for the team to adjust on the Pattern page.
