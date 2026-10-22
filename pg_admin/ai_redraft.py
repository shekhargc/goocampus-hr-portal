"""Instant AI re-draft of a News Inbox notice (founder 2026-10-22: "if I feel something is off I can
press Re-draft and the AI reads the PDF and finds the missed date or redoes the news" — without
waiting for the Mac's next 3-hourly run).

The portal already stores every notice's PDF (inbox copy, the Documents file it points to, or R2),
so the re-draft runs here: the PDF goes to Claude with the same drafting rules the Mac run follows
(tools/news_fetcher/DRAFTING.md), the authority's current schedule (so an extension updates the
existing step instead of adding a second one) and the team's optional "what looks off" note. The
result goes through the same cleaning, calendar merge and Documents filing as a Mac draft.

Needs env ANTHROPIC_API_KEY on Render; without it the button falls back to "re-draft at the next
Mac run". Runs in a background thread (a long PDF can take a minute or two); the Inbox shows
redraft_status = running / done / failed.
"""
import base64
import io
import json
import logging
import os
import re
import threading
from pathlib import Path

MODEL = 'claude-opus-5-5'
MAX_PDF_BYTES = 30 * 1024 * 1024          # API request limit is 32 MB including the prompt
_RULES = Path(__file__).resolve().parents[1] / 'tools' / 'news_fetcher' / 'DRAFTING.md'
_running = set()
_lock = threading.Lock()


def available():
    return bool((os.environ.get('ANTHROPIC_API_KEY') or '').strip())


def ensure_cols(conn):
    for c, t in (('redraft_status', "TEXT DEFAULT ''"), ('redraft_error', "TEXT DEFAULT ''"),
                 ('redraft_note', "TEXT DEFAULT ''"), ('redraft_at', 'TIMESTAMP')):
        conn.execute(f"ALTER TABLE pg_news_inbox ADD COLUMN IF NOT EXISTS {c} {t}")
    conn.commit()


def _pdf_bytes(conn, row):
    """The notice's stored PDF: inbox copy → its Documents file → R2. For a web-page notice, the
    saved page snapshot. None when there is no file."""
    from core import storage
    if row.get('pdf_data'):
        return bytes(row['pdf_data'])
    if row.get('pdf_r2_key'):
        return storage.download_bytes(row['pdf_r2_key'])
    from pg_admin.data.auto_docs import doc_for_inbox
    did = doc_for_inbox(conn, row['id'])
    if not did:
        snap = conn.execute("SELECT id FROM pg_authority_docs WHERE auto_inbox_id = ? AND auto_kind = 'snapshot' "
                            "ORDER BY id DESC LIMIT 1", (row['id'],)).fetchone()
        did = snap['id'] if snap else None
    if not did:
        return None
    d = conn.execute("SELECT file_data, to_jsonb(pg_authority_docs)->>'file_r2_key' AS k FROM pg_authority_docs "
                     "WHERE id = ?", (did,)).fetchone()
    if d and d['file_data']:
        return bytes(d['file_data'])
    if d and d['k']:
        return storage.download_bytes(d['k'])
    return None


def _fit(data):
    """Keep a PDF under the request size limit: drop trailing pages of a huge prospectus (the
    schedule and dates are near the front). Returns (bytes, note)."""
    if len(data) <= MAX_PDF_BYTES:
        return data, ''
    from pypdf import PdfReader, PdfWriter
    r = PdfReader(io.BytesIO(data))
    n = len(r.pages)
    keep = n
    while keep > 1:
        keep = max(1, keep * 2 // 3)
        w = PdfWriter()
        for i in range(keep):
            w.add_page(r.pages[i])
        buf = io.BytesIO()
        w.write(buf)
        if buf.tell() <= MAX_PDF_BYTES:
            return buf.getvalue(), f'Only the first {keep} of {n} pages were sent (file too large).'
    return None, 'The PDF is too large to send.'


def _schedule(conn, code):
    rows = conn.execute("SELECT round, event, label, start_date, end_date, time_text FROM pg_counselling_events "
                        "WHERE authority_code = ? AND COALESCE(is_active, TRUE) ORDER BY start_date",
                        (code,)).fetchall()
    out = []
    for r in rows:
        rnd = r['round'] or '""'
        end = (' → ' + str(r['end_date'])) if r['end_date'] else ''
        tm = (' | ' + r['time_text']) if r['time_text'] else ''
        out.append(f"- round={rnd} | event={r['event']} | label={r['label']} | {r['start_date']}{end}{tm}")
    return '\n'.join(out) or '(none yet)'


def _parse(text):
    m = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.S)
    raw = m.group(1) if m else text[text.find('{'):text.rfind('}') + 1]
    return json.loads(raw)


def start(inbox_id, note, who):
    """Kick off a background re-draft. Returns '' or a reason it did not start."""
    with _lock:
        if inbox_id in _running:
            return 'A re-draft of this notice is already running.'
        _running.add(inbox_id)
    from db import get_db
    conn = get_db()
    try:
        ensure_cols(conn)
        conn.execute("UPDATE pg_news_inbox SET redraft_status = 'running', redraft_error = '', redraft_note = ?, "
                     "redraft_at = CURRENT_TIMESTAMP WHERE id = ?", ((note or '')[:500], inbox_id))
        conn.commit()
    finally:
        conn.close()
    threading.Thread(target=_run, args=(inbox_id, note or '', who), daemon=True).start()
    return ''


def _fail(conn, inbox_id, msg):
    logging.warning("ai redraft %s: %s", inbox_id, msg)
    try:
        conn.rollback()
    except Exception:
        pass
    conn.execute("UPDATE pg_news_inbox SET redraft_status = 'failed', redraft_error = ? WHERE id = ?",
                 (str(msg)[:400], inbox_id))
    conn.commit()


def _run(inbox_id, note, who):
    import anthropic
    from db import get_db
    from pg_admin import news_scraper as NS
    from pg_admin.routes.api_news_ingest import _clean_draft, _auto_calendar, _issued
    conn = get_db()
    try:
        from pg_admin.data.big_files import ensure_cols as _bf_cols
        _bf_cols(conn)
        row = conn.execute("SELECT * FROM pg_news_inbox WHERE id = ?", (inbox_id,)).fetchone()
        if not row:
            return _fail(conn, inbox_id, 'Notice not found.')
        row = dict(row)
        src = NS.SOURCES.get(row['source_code']) or {}
        code = src.get('authority_code') or row.get('authority_code') or ''
        pdf, trim_note = None, ''
        raw = _pdf_bytes(conn, row)
        if raw:
            pdf, trim_note = _fit(raw)
        try:
            old = json.loads(row.get('draft_json') or '{}') or {}
        except Exception:
            old = {}
        context = (
            f"Authority / source: {src.get('label') or row['source_code']}\n"
            f"Official title on the website: {row.get('title') or ''}\n"
            f"Official link: {row.get('url') or ''}\n"
            f"Date the website lists: {row.get('notice_date') or 'not given'}\n"
            f"Kind: {row.get('kind')}{' — no PDF; draft from the title only, as the rules say' if not pdf else ''}\n"
            + (f"Note: {trim_note}\n" if trim_note else '')
            + f"\nThis authority's schedule entries already in the GooCampus calendar (reuse the SAME round/event/"
              f"label for a step that this notice changes or repeats):\n{_schedule(conn, code)}\n"
            + f"\nThe current draft (it may be wrong or incomplete — re-read the PDF and write a fresh draft):\n"
              f"{json.dumps(old, ensure_ascii=False)[:12000]}\n"
            + (f"\nThe GooCampus team says something looks off: \"{note}\". Check this carefully against the PDF.\n"
               if note else '')
            + "\nReturn ONLY the new draft as one JSON object in a ```json code block.")
        content = []
        if pdf:
            content.append({'type': 'document', 'source': {'type': 'base64', 'media_type': 'application/pdf',
                                                           'data': base64.standard_b64encode(pdf).decode()}})
        content.append({'type': 'text', 'text': context})
        system = [{'type': 'text', 'cache_control': {'type': 'ephemeral'}, 'text': (
            "You re-draft ONE official NEET-PG counselling notice for GooCampus (goocampus.in), read by doctors who "
            "must not miss a deadline. The notice (PDF, or its title for a web-page notice) and its context are in "
            "the user message. Follow the drafting rules below exactly — the draft JSON schema, date rules, calendar "
            "`events` merge rules, `document` classification, text = fields, reviewer notes in `review_note`. Ignore "
            "the rules' 'Steps' section about running commands: you are given the notice directly and you return "
            "the JSON instead of writing a file.\n\n" + _RULES.read_text(encoding='utf-8'))}]
        client = anthropic.Anthropic()
        with client.beta.messages.stream(
                model=MODEL, max_tokens=32000, system=system,
                messages=[{'role': 'user', 'content': content}],
                thinking={'type': 'adaptive'}, output_config={'effort': 'high'},
                betas=['server-side-fallback-2026-07-01'], fallbacks='default') as stream:
            msg = stream.get_final_message()
        if msg.stop_reason == 'refusal':
            return _fail(conn, inbox_id, 'The AI declined to draft this notice — use ↻ Re-draft at the next run or edit by hand.')
        if msg.stop_reason == 'max_tokens':
            return _fail(conn, inbox_id, 'The AI ran out of room before finishing — try again.')
        text = ''.join(b.text for b in msg.content if b.type == 'text')
        try:
            draft = _clean_draft(_parse(text))
        except Exception as e:
            return _fail(conn, inbox_id, f'Could not read the AI reply as a draft ({e}).')
        if not draft:
            return _fail(conn, inbox_id, 'The AI returned an empty draft.')
        sets, vals = ["draft_json = ?", "drafted_at = CURRENT_TIMESTAMP", "redraft_requested = FALSE",
                      "redraft_status = 'done'", "redraft_error = ''"], [json.dumps(draft)]
        if not row.get('notice_date') and row.get('status') != 'posted' and _issued(draft):
            sets += ["notice_date = ?", "notice_date_source = 'notice'"]
            vals.append(_issued(draft))
        conn.execute(f"UPDATE pg_news_inbox SET {', '.join(sets)} WHERE id = ?", vals + [inbox_id])
        conn.commit()
        logging.info("ai redraft %s by %s: %s (in %s / out %s tokens)", inbox_id, who, draft.get('headline'),
                     msg.usage.input_tokens, msg.usage.output_tokens)
        if draft.get('events'):
            _auto_calendar(conn, inbox_id)
        if row.get('status') != 'seen':
            from pg_admin.data.auto_docs import file_safely
            file_safely(conn, inbox_id)
    except anthropic.AuthenticationError:
        _fail(conn, inbox_id, 'The Claude API key on the server is not valid.')
    except anthropic.RateLimitError:
        _fail(conn, inbox_id, 'The AI is busy (rate limit) — try again in a minute.')
    except anthropic.APIStatusError as e:
        _fail(conn, inbox_id, f'AI service error {e.status_code}: {getattr(e, "message", e)}')
    except anthropic.APIConnectionError:
        _fail(conn, inbox_id, 'Could not reach the AI service — try again.')
    except Exception as e:
        _fail(conn, inbox_id, f'Re-draft failed: {e}')
    finally:
        conn.close()
        with _lock:
            _running.discard(inbox_id)
