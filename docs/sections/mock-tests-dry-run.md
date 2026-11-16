# Mock Tests — team dry run on staging (before launch)

**Goal:** 5–10 team members take the free mock exactly like real doctors, on staging, to catch problems before doctors do. It takes about 30 minutes of preparation, then everyone's mock time.

## Before the dry run

| # | Who | What |
|---|---|---|
| 1 | Founder | Approve the website branch `mock-tests` going to **goocampus.in staging**, in the website session. Approve `server-health` too. |
| 2 | Content team | On the staging portal → Mock Tests → **Import**: upload a real Word paper (at least 180 questions, with images), or use the sample PDF. Fix anything red and approve. |
| 3 | Content team | Mock Tests → **Papers** → create "Dry Run GT" (full mock) → **Auto-fill** → check "Ready to lock?" → **Preview** → **Lock** → **Publish** → tick **free sample**. |
| 4 | Founder / admin | Pick the testers. **Use normal accounts, not team accounts**, so ranks and the free-sample rules behave as they will for doctors. Team accounts are never ranked. |
| 5 | Admin | Optional: on Packages, give one tester **Standard** to test a paid mock. To test real payment, use Razorpay **test** keys on staging only. |

## During the dry run — each tester

1. Log in on goocampus.in staging → **My Mocks** → **Start** the free sample. Read the instructions → full screen → begin.
2. Answer normally. Use **Mark for Review**, **Clear Response**, and the palette.
3. **Break things on purpose** (one each, spread across testers):
   - switch tabs / leave full screen;
   - turn Wi-Fi off for a minute while answering, then back on;
   - close the browser mid-section, reopen on **another device** (phone) and continue;
   - leave a section idle until its timer ends;
   - one tester simply walks away and never submits. The mock must submit itself when time ends.
4. Finish or submit → check the **result page**: score, rank, predicted NEET rank → **See colleges** → **Solutions**.
5. Note anything confusing or wrong: a screenshot plus one line.

## After — the admin checks the staging portal

- **Mock Tests → Dashboard:** testers counted, nobody stuck "in progress" after the end time.
- **Attempts →** each tester: flags match what they did (tab switch, offline); the walk-away tester shows "Time up".
- **Analytics →** score spread; **Questions to check**, which needs 10+ testers to be meaningful.
- Any answer a tester says "disappeared": open their attempt and check the answers table.

## Go / no-go before launch

- No lost answers, no tester stuck, auto-submit worked, results correct.
- Content: enough approved questions for the launch packages (Starter needs 5 full mocks = 900 questions).
- Founder decisions settled:
  - package end date (now 30 Sep 2027);
  - threads on the portal (see the load test);
  - website server size;
  - the launch date.
- Live push: the main **GooCampus Portal Dashboard** session promotes the portal; the website session promotes goocampus.in.
- Before launch: discard the sample/test imports and retire the dry-run mock, so test data never reaches doctors.
