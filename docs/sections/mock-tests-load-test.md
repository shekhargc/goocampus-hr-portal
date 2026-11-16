# Mock Tests — load test (Step 9, 16 Nov 2026)

## How it was run

- **Not on staging.** Staging shares the live database, so a load test there would slow the live portal. Staging also needs the goocampus.in key, which only the founder holds.
- **Instead, on the Mac:**
  - the real exam engine;
  - the portal's own `/api/pg` speed layer (gzip);
  - the same server setup as Render: gunicorn, 2 workers, timeout 300;
  - a throwaway PostgreSQL 16;
  - 1,500 test doctors;
  - one published 180-question mock.
- **Each simulated doctor:**
  - presses **Start**, and all doctors start in the same second (the worst case);
  - autosaves an answer every 2–3 s (about 10× faster than a real doctor, who saves roughly every 20–30 s);
  - sends a heartbeat now and then, and reloads the section occasionally.

## Results

| Run | Saves / second | Typical save | 95% under | 99% under | Errors | All doctors pressing Start at once |
|---|---|---|---|---|---|---|
| 50 doctors | 22 | 10 ms | 15 ms | 27 ms | 0 | 95% under 0.16 s |
| 300 doctors | 90 | 9 ms | 18 ms | 46 ms | 0 | 95% under 0.72 s |
| 600 doctors | 178 | 6 ms | 14 ms | 159 ms | 0 | 95% under 2.4 s |
| 300 doctors + **2 slow reports**, current setup | 29 | **2,756 ms** | **4,988 ms** | 6,077 ms | 0 (80 starts still waiting at the end) | 95% under 6.8 s |
| 300 doctors + 2 slow reports, **2 workers × 8 threads** | 59 | 10 ms | 14 ms | 18 ms | 0 | 95% under 0.32 s |

**Per autosave:**
- about 5 small database queries plus one new database connection;
- an empty heartbeat is the same minus the answer update;
- a section load is about 28 KB, gzipped on the way out.

## What it means

1. **The exam engine is not the bottleneck.**
   - A real doctor saves about 3 times a minute (0.05 / s).
   - 600 simulated doctors saving every 3 s is the load of roughly **3,500 doctors in a mock at the same moment**.
   - Practice mocks spread across the day, so real peaks will be far lower.
   - Render's machine is slower than this Mac, and each database query crosses a network there, so expect each save to take **2–4× longer on Render**. That is still fine.
2. **The real risk is the shared server.**
   - The portal runs **2 workers that each handle one request at a time**, and the whole team's portal shares them.
   - When 2 slow pages (a big report or an Excel export) run together, every doctor's autosave waits behind them: **3–6 seconds**.
   - The exam keeps working (answers are kept on the device and re-sent), but the screen shows "saving…" and the timer re-syncs late.
   - With **threads** (`--threads 8`), the same test stays at 10–18 ms.
3. **A deploy no longer pauses exams.**
   - Found in this test: both workers set up the exam tables at the same moment, and the database reported a **deadlock**. The table setup also took a lock that pauses autosaves.
   - Fixed: a version marker (`ex_meta.schema_version`). A normal restart now does 2 tiny reads and no table changes. An upgrade runs in one process only, with a 5-second lock limit.

## Recommendations (founder decides)

1. **Switch the portal to threads.** Change the Procfile to `gunicorn app:app --workers 2 --threads 8 --timeout 300`.
   - It is one line, but it changes how the **whole portal** runs.
   - So: staging first, then a day of normal team use, then live, through the main "GooCampus Portal Dashboard" session.
   - Cost: none.
   - Why it is likely safe: each request opens its own database connection (`get_db()`), and the background jobs already run in threads.
   - What to watch on staging: any page that keeps per-request data in module-level variables.
2. **goocampus.in website server** (512 MB, restarted twice in Nov): it relays every exam call.
   - Approve its `server-health` fix now.
   - Consider the 2 GB plan before any big promotion or a fixed-date all-India mock. That's the founder's call.
3. **Later, only if mocks get very busy:** a connection pool, instead of a new database connection per request.

## Not covered by this test

- The goocampus.in relay. The website session can test its own server the same way.
- Render's real network latency.
- Thousands of doctors pressing Start in the same second, which happens only with fixed-date all-India mocks. Revisit before the first one.
