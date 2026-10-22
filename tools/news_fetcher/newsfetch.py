#!/usr/bin/env python3
"""GooCampus counselling-notice fetcher — runs on the founder's Mac (Indian IP; the govt
sites block our Render server). Driven by a Claude Code scheduled task (founder 2026-10-08):

  1. python newsfetch.py scan   → reads every source, asks the portal which notices it already
                                   has, downloads new PDFs, writes work/pending.json. Prints
                                   "PENDING <n>"; 0 = nothing to do (the task stops there).
  2. (the Claude session reads each pending PDF and writes work/drafts/<id>.json)
  3. python newsfetch.py push   → sends each pending notice (+ draft + PDF) to the portal inbox.

No AI here and no secrets in the repo: portal URL + key live in ~/.goocampus/news_ingest.json
  {"portal": "https://goocampus.org", "key": "<same value as Render env NEWS_INGEST_KEY>"}
Notices from the PREVIOUS NEET-PG season are recorded as already seen (no draft); every notice of the
current season (news_scraper.SEASON_FROM) is drafted, however old.
"""
import os
import sys
import json
import base64
import hashlib
from datetime import date, timedelta

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, REPO)
from pg_admin import news_scraper as NS          # noqa: E402  (readers + SOURCES)

WORK = os.path.expanduser('~/goocampus-news')
CONF = os.path.expanduser('~/.goocampus/news_ingest.json')
PENDING = os.path.join(WORK, 'pending.json')
DRAFTS = os.path.join(WORK, 'drafts')
PDFS = os.path.join(WORK, 'pdf')
SNAPS = os.path.join(WORK, 'snap')
SNAP_FAILS = os.path.join(WORK, 'snap_failed.json')
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
SNAP_MAX = 25                      # older web pages snapshotted per source per run (catch-up)


def _conf():
    with open(CONF) as f:
        c = json.load(f)
    return c['portal'].rstrip('/'), c['key']


def _api(method, path, **kw):
    import requests
    portal, key = _conf()
    r = requests.request(method, portal + path, headers={'X-News-Key': key}, timeout=60, **kw)
    r.raise_for_status()
    return r.json()


INLINE_MAX = 20 * 1024 * 1024       # bigger PDFs go straight to R2 storage (founder 2026-10-17)


def _pdf_fields(code, item_key, data, name):
    """The ingest-body fields that carry a PDF: inline (base64) when small, else upload it to R2
    via a signed link and send only the key. Every authority PDF is archived, whatever its size."""
    import requests
    name = (name or 'notice.pdf')[:200]
    if len(data) <= INLINE_MAX:
        return {'pdf_b64': base64.b64encode(data).decode(), 'pdf_name': name}
    sha = hashlib.sha256(data).hexdigest()
    u = _api('POST', '/api/pg/news-inbox/upload-url',
             json={'source_code': code, 'item_key': item_key, 'sha256': sha, 'name': name, 'size': len(data)})
    if not u.get('already'):
        r = requests.put(u['put_url'], data=data, headers={'Content-Type': 'application/pdf'}, timeout=900)
        r.raise_for_status()
    print(f"  big PDF ({len(data) // (1024 * 1024)} MB) archived in storage: {u['key']}")
    return {'pdf_r2_key': u['key'], 'pdf_sha256': sha, 'pdf_size': len(data), 'pdf_name': name}


def _fetch_missing_pdfs(code, need):
    """PDF notices the portal still has no copy of (not online yet / failed before) — try again;
    when the file is there now, send it (it is attached to the inbox notice, any posted news and the
    authority's Documents). Returns how many arrived."""
    got = 0
    for n in need or []:
        data, name = NS.fetch_pdf(n['url'])
        if not data:
            continue
        try:
            body = {'source_code': code, 'item_key': n['item_key']}
            body.update(_pdf_fields(code, n['item_key'], data, name))
            _api('POST', '/api/pg/news-inbox/ingest', json=body)
            got += 1
            print(f"  PDF now online and archived: {n['title'][:80]}")
        except Exception as e:
            print(f"  PDF for {n['title'][:60]} could not be sent ({e}) — will retry next run")
    return got


def _snapshot(url):
    """Print a web-page notice to PDF with headless Chrome (its own throwaway profile — never the
    founder's browser). Returns the PDF bytes, or None (not a web page / timed out / no Chrome).
    Every notice must stay in our control after the authority edits or removes the page (2026-10-22)."""
    import subprocess
    import tempfile
    path = url.split('?')[0].lower()
    if not url.startswith('http') or path.endswith(('.xls', '.xlsx', '.doc', '.docx', '.zip', '.rar', '.csv',
                                                     '.ppt', '.pptx', '.pdf')):
        return None
    if not os.path.exists(CHROME):
        return None
    fd, out = tempfile.mkstemp(suffix='.pdf'); os.close(fd)
    try:
        subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--no-first-run', '--no-pdf-header-footer',
                        '--user-data-dir=' + os.path.join(WORK, 'chrome-snap'), '--timeout=45000',
                        '--user-agent=' + NS.UA, '--print-to-pdf=' + out, url],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
        with open(out, 'rb') as f:
            data = f.read()
        if not data.startswith(b'%PDF') or len(data) < 1500 or len(data) > INLINE_MAX:
            return None                                  # blank page (site down / load timed out)
        try:                                             # never keep a block / error page
            import io
            from pypdf import PdfReader
            txt = ' '.join((pg.extract_text() or '') for pg in PdfReader(io.BytesIO(data)).pages[:2]).lower()
            if len(txt) < 1500 and any(w in txt for w in ('access denied', "don't have permission", '403 forbidden',
                                                           '404 not found', 'page not found', 'bad gateway',
                                                           'service unavailable', 'request rejected')):
                return None
        except Exception:
            pass
        return data
    except Exception:
        return None
    finally:
        try: os.remove(out)
        except OSError: pass


def _send_snapshot(code, item_key, data, title):
    name = (''.join(c for c in (title or 'web-page') if c.isalnum() or c in ' -_')[:80].strip() or 'web-page') + '.pdf'
    r = _api('POST', '/api/pg/news-inbox/snapshot',
             json={'source_code': code, 'item_key': item_key, 'name': name,
                   'pdf_b64': base64.b64encode(data).decode()})
    return r.get('result')


def _snap_fails():
    try:
        with open(SNAP_FAILS) as f:
            return json.load(f)
    except Exception:
        return {}


def _catch_up_snapshots(code, need):
    """Web-page notices the portal holds no snapshot of yet → print + send (a few per run; a page that
    fails 3 times is skipped so a broken link never slows every run)."""
    fails = _snap_fails()
    got = 0
    for n in (need or [])[:SNAP_MAX]:
        k = f"{code}|{n['item_key']}"
        if fails.get(k, 0) >= 3:
            continue
        data = _snapshot(n['url'])
        if not data:
            fails[k] = fails.get(k, 0) + 1
            continue
        try:
            if _send_snapshot(code, n['item_key'], data, n.get('title')) in ('archived', 'duplicate', 'already'):
                got += 1
        except Exception as e:
            print(f"  snapshot of {n['title'][:60]} could not be sent ({e}) — will retry next run")
    os.makedirs(WORK, exist_ok=True)
    with open(SNAP_FAILS, 'w') as f:
        json.dump(fails, f)
    return got


def _load_pending():
    try:
        with open(PENDING) as f:
            return json.load(f)
    except Exception:
        return []


def _save_pending(items):
    os.makedirs(WORK, exist_ok=True)
    with open(PENDING, 'w') as f:
        json.dump(items, f, indent=1, default=str)


def _id(code, key):
    return hashlib.sha1(f'{code}|{key}'.encode()).hexdigest()[:12]


def scan():
    os.makedirs(PDFS, exist_ok=True)
    os.makedirs(DRAFTS, exist_ok=True)
    pending = _load_pending()
    have = {p['id'] for p in pending}
    beat = []
    for code, src in NS.SOURCES.items():
        if not src.get('enabled'):
            continue
        res = {'source': code, 'ok': False, 'found': 0, 'new': 0, 'error': ''}
        try:
            items = NS.read_source(code)
            kinfo = _api('GET', '/api/pg/news-inbox/known', params={'source': code})
            known = set(kinfo.get('known') or [])
            first_run = not known
            res['found'] = len(items)
            res['pdfs_late'] = _fetch_missing_pdfs(code, kinfo.get('need_pdf'))
            res['snapshots'] = _catch_up_snapshots(code, kinfo.get('need_snapshot'))
            # Notices the founder asked to re-draft ("↻ Re-draft with AI" in the News Inbox)
            for rd in (kinfo.get('redraft') or []):
                iid = _id(code, rd['item_key'])
                if iid in have:
                    continue
                pdf_path = ''
                if rd.get('kind') == 'pdf' and rd.get('url'):
                    data, _n = NS.fetch_pdf(rd['url'])
                    if data:
                        pdf_path = os.path.join(PDFS, iid + '.pdf')
                        with open(pdf_path, 'wb') as f:
                            f.write(data)
                dp = os.path.join(DRAFTS, iid + '.json')
                if os.path.exists(dp):
                    os.remove(dp)                       # force a fresh draft
                pending.append({'id': iid, 'source_code': code, 'source_label': src['label'],
                                'item_key': rd['item_key'], 'title': rd.get('title') or '',
                                'raw_title': rd.get('title') or '', 'url': rd.get('url') or '',
                                'kind': rd.get('kind') or 'link', 'notice_date': rd.get('notice_date'),
                                'pdf_path': pdf_path, 'draft_path': dp, 'redraft': True})
                have.add(iid)
                res['new'] += 1
            for it in items:
                if it['item_key'] in known:
                    continue
                iid = _id(code, it['item_key'])
                if iid in have:
                    continue
                d = it.get('notice_date')
                # Only last season's notices are set aside (recorded as seen, never drafted). Every
                # notice of the current NEET-PG season is drafted, however old — also on a new
                # source's first run (founder 2026-10-13).
                if not NS.in_season(it):
                    # baseline: record as already seen — no draft, no PDF
                    _api('POST', '/api/pg/news-inbox/ingest', json={
                        'source_code': code, 'item_key': it['item_key'], 'title': it['title'],
                        'raw_title': it['raw_title'], 'url': it['url'], 'kind': it['kind'],
                        'notice_date': d.isoformat() if d else None, 'status': 'seen'})
                    continue
                pdf_path = snap_path = ''
                if it['kind'] == 'pdf':
                    data, name = NS.fetch_pdf(it['url'])
                    if data:
                        pdf_path = os.path.join(PDFS, iid + '.pdf')
                        with open(pdf_path, 'wb') as f:
                            f.write(data)
                elif it.get('url'):
                    snap = _snapshot(it['url'])         # web-page notice → PDF snapshot, sent at push
                    if snap:
                        os.makedirs(SNAPS, exist_ok=True)
                        snap_path = os.path.join(SNAPS, iid + '.pdf')
                        with open(snap_path, 'wb') as f:
                            f.write(snap)
                pending.append({'id': iid, 'source_code': code, 'source_label': src['label'],
                                'item_key': it['item_key'], 'title': it['title'], 'raw_title': it['raw_title'],
                                'url': it['url'], 'kind': it['kind'],
                                'notice_date': d.isoformat() if d else None,
                                'pdf_path': pdf_path, 'snapshot_path': snap_path,
                                'draft_path': os.path.join(DRAFTS, iid + '.json')})
                have.add(iid)
                res['new'] += 1
            res['ok'] = True
        except Exception as e:
            res['error'] = str(e)[:300]
        beat.append(res)
    _save_pending(pending)
    try:
        _api('POST', '/api/pg/news-inbox/heartbeat', json={'sources': beat})
    except Exception as e:
        print('heartbeat failed:', e)
    for b in beat:
        print(f"{b['source']}: {'ok' if b['ok'] else 'ERROR ' + b['error']} · {b['found']} on page · {b['new']} new"
              + (f" · {b['pdfs_late']} missing PDF(s) now archived" if b.get('pdfs_late') else '')
              + (f" · {b['snapshots']} web page(s) saved as PDF" if b.get('snapshots') else ''))
    print(f'PENDING {len(pending)}')
    for p in pending:
        print(json.dumps({k: p[k] for k in ('id', 'source_label', 'title', 'kind', 'notice_date',
                                            'url', 'pdf_path', 'draft_path')}))


def push():
    pending = _load_pending()
    left = []
    for p in pending:
        body = {k: p.get(k) for k in ('source_code', 'item_key', 'title', 'raw_title', 'url', 'kind', 'notice_date')}
        if p.get('revive'):
            body['revive'] = True            # a current-season notice that was set aside earlier
        if os.path.exists(p['draft_path']):
            try:
                with open(p['draft_path']) as f:
                    body['draft'] = json.load(f)
            except Exception as e:
                print(f"{p['id']}: draft unreadable ({e}) — sending without it")
        try:
            if p.get('pdf_path') and os.path.exists(p['pdf_path']):
                with open(p['pdf_path'], 'rb') as f:
                    body.update(_pdf_fields(p['source_code'], p['item_key'], f.read(),
                                            p['url'].split('?')[0].rsplit('/', 1)[-1][:200]))
            r = _api('POST', '/api/pg/news-inbox/ingest', json=body)
            print(f"{p['id']}: {r.get('result')} · {p['title'][:80]}")
            sp = p.get('snapshot_path')
            if sp and os.path.exists(sp):
                try:                                     # the page's PDF snapshot → archive (not fatal)
                    with open(sp, 'rb') as f:
                        _send_snapshot(p['source_code'], p['item_key'], f.read(), p.get('title'))
                    os.remove(sp)
                except Exception as e:
                    print(f"{p['id']}: snapshot not sent ({e}) — the next run retries it")
        except Exception as e:
            print(f"{p['id']}: FAILED ({e}) — will retry next run")
            left.append(p)
    _save_pending(left)
    print(f'LEFT {len(left)}')


def text(iid, first=None, last=None):
    """Print a pending PDF's text page by page (for long PDFs — Claude reads this instead of
    the whole file). `text <id> [first] [last]` (1-based pages)."""
    from pypdf import PdfReader
    p = next((x for x in _load_pending() if x['id'] == iid), None)
    path = p['pdf_path'] if p else os.path.join(PDFS, iid + '.pdf')
    r = PdfReader(path)
    n = len(r.pages)
    a = max(1, int(first or 1)); b = min(n, int(last or n))
    print(f'[{n} pages — showing {a}-{b}]')
    empty = []
    for i in range(a - 1, b):
        t = (r.pages[i].extract_text() or '').strip()
        print(f'\n--- page {i + 1} ---')
        print(t)
        if len(t) < 40:
            empty.append(i)
    if empty:
        # a SCANNED notice (image only, no text) — save the page images so they can be READ
        # (founder 2026-10-18: never draft a notice from its title when the PDF is there)
        out = os.path.join(WORK, 'img')
        os.makedirs(out, exist_ok=True)
        saved = []
        for i in empty:
            try:
                for j, im in enumerate(r.pages[i].images):
                    ext = os.path.splitext(im.name)[1] or '.png'
                    fp = os.path.join(out, f'{iid}_p{i + 1}_{j}{ext}')
                    with open(fp, 'wb') as f:
                        f.write(im.data)
                    saved.append(fp)
            except Exception as e:
                print(f'(could not extract images from page {i + 1}: {e})')
        if saved:
            print('\nSCANNED PAGES (no text layer) — READ these images with the Read tool before drafting:')
            for fp in saved:
                print('  ' + fp)


if __name__ == '__main__':
    cmd = (sys.argv[1] if len(sys.argv) > 1 else '').strip()
    if cmd == 'scan':
        scan()
    elif cmd == 'push':
        push()
    elif cmd == 'text' and len(sys.argv) > 2:
        text(sys.argv[2], *(sys.argv[3:5]))
    else:
        print(__doc__)
