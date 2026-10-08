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
First run per source: notices older than BASELINE_DAYS are recorded as already seen (no draft).
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
BASELINE_DAYS = 7


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
            known = set(_api('GET', '/api/pg/news-inbox/known', params={'source': code}).get('known') or [])
            first_run = not known
            res['found'] = len(items)
            for it in items:
                if it['item_key'] in known:
                    continue
                iid = _id(code, it['item_key'])
                if iid in have:
                    continue
                d = it.get('notice_date')
                if first_run and (not d or d < date.today() - timedelta(days=BASELINE_DAYS)):
                    # baseline: record as already seen — no draft, no PDF
                    _api('POST', '/api/pg/news-inbox/ingest', json={
                        'source_code': code, 'item_key': it['item_key'], 'title': it['title'],
                        'raw_title': it['raw_title'], 'url': it['url'], 'kind': it['kind'],
                        'notice_date': d.isoformat() if d else None, 'status': 'seen'})
                    continue
                pdf_path = ''
                if it['kind'] == 'pdf':
                    data, name = NS.fetch_pdf(it['url'])
                    if data:
                        pdf_path = os.path.join(PDFS, iid + '.pdf')
                        with open(pdf_path, 'wb') as f:
                            f.write(data)
                pending.append({'id': iid, 'source_code': code, 'source_label': src['label'],
                                'item_key': it['item_key'], 'title': it['title'], 'raw_title': it['raw_title'],
                                'url': it['url'], 'kind': it['kind'],
                                'notice_date': d.isoformat() if d else None,
                                'pdf_path': pdf_path, 'draft_path': os.path.join(DRAFTS, iid + '.json')})
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
        print(f"{b['source']}: {'ok' if b['ok'] else 'ERROR ' + b['error']} · {b['found']} on page · {b['new']} new")
    print(f'PENDING {len(pending)}')
    for p in pending:
        print(json.dumps({k: p[k] for k in ('id', 'source_label', 'title', 'kind', 'notice_date',
                                            'url', 'pdf_path', 'draft_path')}))


def push():
    pending = _load_pending()
    left = []
    for p in pending:
        body = {k: p.get(k) for k in ('source_code', 'item_key', 'title', 'raw_title', 'url', 'kind', 'notice_date')}
        if os.path.exists(p['draft_path']):
            try:
                with open(p['draft_path']) as f:
                    body['draft'] = json.load(f)
            except Exception as e:
                print(f"{p['id']}: draft unreadable ({e}) — sending without it")
        if p.get('pdf_path') and os.path.exists(p['pdf_path']):
            with open(p['pdf_path'], 'rb') as f:
                body['pdf_b64'] = base64.b64encode(f.read()).decode()
            body['pdf_name'] = p['url'].split('?')[0].rsplit('/', 1)[-1][:200]
        try:
            r = _api('POST', '/api/pg/news-inbox/ingest', json=body)
            print(f"{p['id']}: {r.get('result')} · {p['title'][:80]}")
        except Exception as e:
            print(f"{p['id']}: FAILED ({e}) — will retry next run")
            left.append(p)
    _save_pending(left)
    print(f'LEFT {len(left)}')


if __name__ == '__main__':
    cmd = (sys.argv[1] if len(sys.argv) > 1 else '').strip()
    if cmd == 'scan':
        scan()
    elif cmd == 'push':
        push()
    else:
        print(__doc__)
