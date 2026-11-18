"""Prepare one country e-book for the goocampus.in dashboard reader (Mac-side; founder 2026-11-18).

    /usr/bin/python3 tools/ebooks/prepare.py <code> <folder with Chapter-N.pdf> [--dry]

For every Chapter-N.pdf: the original PDF is backed up to R2 (ebooks/<code>/src/), each page is rendered to a
1400-px-wide WebP (ebooks/<code>/c<NN>/p<NNN>.webp) and the chapter is registered with the portal
(/api/pg/ebooks/register). The portal never serves the PDF — only these page images, watermarked per doctor.
Re-running is safe: files already in R2 (same key) are not uploaded again; the chapter's page list is replaced,
its summary / step tag are kept. Uses ~/.goocampus/news_ingest.json (portal + X-News-Key).
"""
import glob
import io
import json
import os
import re
import sys
import urllib.request

import fitz  # PyMuPDF (system /usr/bin/python3)

WIDTH = 1400


def _cfg():
    c = json.load(open(os.path.expanduser('~/.goocampus/news_ingest.json')))
    if '--portal' in sys.argv:                       # e.g. the staging service before the feature is live
        c['portal'] = sys.argv[sys.argv.index('--portal') + 1]
    return c


def _post(cfg, path, body):
    r = urllib.request.Request(cfg['portal'].rstrip('/') + path, data=json.dumps(body).encode(),
                               headers={'X-News-Key': cfg['key'], 'Content-Type': 'application/json'}, method='POST')
    return json.load(urllib.request.urlopen(r, timeout=120))


def _put(cfg, key, data, ctype):
    u = _post(cfg, '/api/pg/ebooks/upload-url', {'key': key, 'content_type': ctype})
    if not u.get('ok'):
        raise SystemExit(f"upload-url failed for {key}: {u}")
    if u.get('already'):
        return 'kept'
    req = urllib.request.Request(u['put_url'], data=data, headers={'Content-Type': ctype}, method='PUT')
    urllib.request.urlopen(req, timeout=300)
    return 'uploaded'


def _title(doc):
    """'01 C H A P T E R 3 FIND THE REGULATOR … UAE · IMG GUIDE 13' / '… I N T H I S C H A P T E R …' → title."""
    t = ' '.join(doc[0].get_text().split())
    m = re.search(r'C\s*H\s*A\s*P\s*T\s*E\s*R\s*((?:\d\s*){1,2})(.*)', t)
    rest = m.group(2) if m else t
    rest = re.split(r'I N T H I S C H A P T E R|·\s*IMG GUIDE', rest)[0]
    rest = re.sub(r'^\s*\d{1,2}\s+', '', rest).strip()
    rest = re.sub(r'\s+(UAE|SAUDI ARABIA|AUSTRALIA)\s*$', '', rest).strip(' ·')
    title = rest[:120]
    if title.isupper():
        title = title[:1].upper() + title[1:].lower()
        for w in ('UAE', 'AMC', 'AHPRA', 'CPD', 'DHA', 'DOH', 'MOHAP', 'EHS', 'SMLE', 'WBA', 'IMG', 'PG', 'GP', 'PR',
                  'Saudi Arabia', 'Australian', 'Australia', 'Saudi', 'Arabia', 'Dubai', 'Abu Dhabi', 'India', 'Indian'):
            title = re.sub(r'\b' + re.escape(w.lower()) + r'\b', w, title, flags=re.I)
    return title


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    code, folder, dry = sys.argv[1], sys.argv[2], '--dry' in sys.argv
    # optional summaries file: --summaries <json {"1": {"summary": "...", "service_tag": "..."}, ...}>
    extra = {}
    if '--summaries' in sys.argv:
        extra = json.load(open(sys.argv[sys.argv.index('--summaries') + 1]))
    files = sorted(glob.glob(os.path.join(folder, 'Chapter-*.pdf')), key=lambda p: int(re.findall(r'(\d+)\.pdf$', p)[0]))
    if not files:
        raise SystemExit('no Chapter-N.pdf files in ' + folder)
    cfg = None if dry else _cfg()
    total = 0
    for f in files:
        n = int(re.findall(r'(\d+)\.pdf$', f)[0])
        doc = fitz.open(f)
        title = _title(doc)
        src_key = f"ebooks/{code}/src/Chapter-{n:02d}.pdf"
        pages = []
        for i, page in enumerate(doc, start=1):
            z = WIDTH / page.rect.width
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z))
            png = pix.tobytes('png')
            try:
                from PIL import Image
                im = Image.open(io.BytesIO(png)).convert('RGB')
                buf = io.BytesIO(); im.save(buf, 'WEBP', quality=85); data, ctype, ext = buf.getvalue(), 'image/webp', 'webp'
            except Exception:
                data, ctype, ext = png, 'image/png', 'png'
            key = f"ebooks/{code}/c{n:02d}/p{i:03d}.{ext}"
            if not dry:
                _put(cfg, key, data, ctype)
            pages.append({'page_no': i, 'key': key, 'width': pix.width, 'height': pix.height})
        total += len(pages)
        if dry:
            print(f"chapter {n:2d}: {len(pages):2d} pages · {title}")
            continue
        _put(cfg, src_key, open(f, 'rb').read(), 'application/pdf')
        x = extra.get(str(n)) or {}
        r = _post(cfg, '/api/pg/ebooks/register', {'code': code, 'chapter_no': n, 'title': title, 'pdf_key': src_key,
                                                   'pages': pages, 'summary': x.get('summary', ''),
                                                   'service_tag': x.get('service_tag', '')})
        print(f"chapter {n:2d}: {len(pages):2d} pages · {title} → {r}")
    print(f"{code}: {len(files)} chapters, {total} pages{' (dry run)' if dry else ''}")


if __name__ == '__main__':
    main()
