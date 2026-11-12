"""Typed (text) PDF → the line/image stream layout.py reads.  Uses pypdfium2 only (Chrome's PDF engine).

- Text: pdfium's reading-order text, line by line, with each line's height on the page.
- Pictures are cut out of the rendered page at their position, so every image encoding works.
  Tiny pictures and ones repeated on many pages (logos, watermarks) are skipped.
- Running headers/footers (a line repeated at the top/bottom of 3+ pages) are dropped.
- Diagrams drawn as vector lines are not "pictures" in a PDF; the team crops those from the
  page on the review screen (crop_region below).
A scanned PDF has no text layer → info['scanned'] is True and the upload is refused with a plain
message (the AI route handles those).
"""
import io
import re
import collections

RENDER_SCALE = 2.0          # 144 dpi crops — sharp enough for ECGs / X-rays on screen
MIN_IMG_PT = 40             # ignore pictures smaller than this (points) on either side
EDGE_FRAC = 0.16            # top/bottom 16% of a page = header/footer zone


def _structural(text):
    """Lines that carry question structure are never headers, even when they sit at a page top."""
    from exam_engine.importer import layout as L
    t = text.strip()
    return bool(L.RE_Q_HEAD.match(t) and (L.RE_Q_HEAD.match(t).group(1) or L.RE_Q_HEAD.match(t).group(2).strip())
                or L.RE_OPT.match(t) or L.RE_ANSWER.match(t) or L.RE_EXPL.match(t) or L.RE_IMG_BOX.match(t)
                or L.EXPL_BOXES.get(t.lower().rstrip(':').strip()) or L.RE_SUBJECT.match(t) or L.RE_TOPIC.match(t))


def _norm_header(text):
    t = text.lower()
    t = re.sub(r'\d+', '#', t)
    t = re.sub(r'\b[a-z]\b', '@', t)          # "Section A" ≈ "Section B"
    return re.sub(r'\s+', ' ', t).strip()


def _page_lines(page, tp, height):
    """[(top_from_page_top, text)] in reading order."""
    text = tp.get_text_bounded() or ''
    out, pos = [], 0
    n_chars = tp.count_chars()
    for ln in re.split(r'\r\n|\n|\r', text):
        idx = text.find(ln, pos) if ln else -1
        if idx >= 0:
            pos = idx + len(ln)
        if not ln.strip():
            continue
        top = None
        try:
            if 0 <= idx < n_chars:
                box = tp.get_charbox(idx)          # (left, bottom, right, top), origin bottom-left
                top = height - float(box[3])
        except Exception:
            top = None
        out.append((top, ln))
    # lines without a position keep their order between neighbours
    last = 0.0
    fixed = []
    for top, ln in out:
        if top is None:
            top = last
        last = top
        fixed.append((top, ln))
    return fixed


def _page_images(page, width, height):
    import pypdfium2.raw as pdfium_c
    boxes = []
    try:
        for obj in page.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_IMAGE,), max_depth=4):
            left, bottom, right, top = obj.get_pos()
            x0, x1 = max(0.0, left), min(width, right)
            y0, y1 = max(0.0, height - top), min(height, height - bottom)
            if (x1 - x0) >= MIN_IMG_PT and (y1 - y0) >= MIN_IMG_PT:
                boxes.append((x0, y0, x1, y1))
    except Exception:
        pass
    return boxes


def read_pdf(data):
    """bytes → (items, info). items: ('line', text, page) / ('image', {data, ext, bbox, …}, page)."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(data)
    try:
        per_page = []           # [(page_no, width, height, [(top, text)], [img boxes])]
        for i in range(len(doc)):
            page = doc[i]
            w, h = float(page.get_width()), float(page.get_height())
            tp = page.get_textpage()
            per_page.append((i + 1, w, h, _page_lines(page, tp, h), _page_images(page, w, h)))

        n_pages = len(per_page)
        chars = sum(len(t) for _, _, _, ls, _ in per_page for _, t in ls)
        info = {'pages': n_pages, 'text_chars': chars, 'scanned': n_pages > 0 and chars < 40 * n_pages,
                'headers_removed': 0, 'images_found': 0, 'images_skipped': 0}

        # running headers / footers: the same text (digits & single letters ignored) at the top/bottom of 3+
        # pages and NEVER in the middle of a page — boilerplate sentences that repeat inside explanations
        # also land at page tops sometimes, but they show up mid-page too, so they're kept
        edge_counts, mid_counts = collections.Counter(), collections.Counter()
        for _, w, h, ls, _ in per_page:
            seen = set()
            for top, t in ls:
                k = _norm_header(t)
                if not k:
                    continue
                if top < h * EDGE_FRAC or top > h * (1 - EDGE_FRAC):
                    if len(k) >= 10 and k not in seen and not _structural(t):
                        seen.add(k)
                        edge_counts[k] += 1
                else:
                    mid_counts[k] += 1
        header_keys = {k for k, c in edge_counts.items() if c >= 3 and not mid_counts.get(k)}
        page_no_re = re.compile(r'^(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?$', re.I)

        # logos / watermarks: a picture of the same size at the same place on 3+ pages
        img_keys = collections.Counter()
        for _, _, _, _, imgs in per_page:
            for b in set((round(b[0]), round(b[1]), round(b[2] - b[0]), round(b[3] - b[1])) for b in imgs):
                img_keys[b] += 1
        repeated_imgs = {k for k, c in img_keys.items() if c >= 3}

        items = []
        for pno, w, h, ls, imgs in per_page:
            entries = []
            for top, t in ls:
                if page_no_re.match(t.strip()):
                    continue
                if ((top < h * EDGE_FRAC or top > h * (1 - EDGE_FRAC)) and _norm_header(t) in header_keys
                        and not _structural(t)):
                    info['headers_removed'] += 1
                    continue
                entries.append((top, 0, ('line', t, pno)))
            keep = [b for b in imgs
                    if (round(b[0]), round(b[1]), round(b[2] - b[0]), round(b[3] - b[1])) not in repeated_imgs]
            info['images_skipped'] += len(imgs) - len(keep)
            if keep:
                pil = doc[pno - 1].render(scale=RENDER_SCALE).to_pil()
                for (x0, y0, x1, y1) in keep:
                    crop = pil.crop((int(x0 * RENDER_SCALE), int(y0 * RENDER_SCALE),
                                     int(x1 * RENDER_SCALE), int(y1 * RENDER_SCALE)))
                    buf = io.BytesIO()
                    crop.convert('RGB').save(buf, 'PNG', optimize=True)
                    entries.append((y0, 1, ('image', {'data': buf.getvalue(), 'ext': 'png',
                                                      'content_type': 'image/png',
                                                      'bbox': [x0 / w, y0 / h, x1 / w, y1 / h],
                                                      'source': 'pdf_image'}, pno)))
                    info['images_found'] += 1
            entries.sort(key=lambda e: (e[0], e[1]))
            items.extend(e[2] for e in entries)
        return items, info
    finally:
        doc.close()


def render_page_png(data, page_no, scale=1.6):
    """One page as PNG bytes (the review screen shows it next to the question)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(data)
    try:
        if page_no < 1 or page_no > len(doc):
            return None
        pil = doc[page_no - 1].render(scale=scale).to_pil()
        buf = io.BytesIO()
        pil.convert('RGB').save(buf, 'PNG', optimize=True)
        return buf.getvalue()
    finally:
        doc.close()


def crop_region(data, page_no, frac_box, scale=RENDER_SCALE):
    """Cut a picture/diagram out of a page. frac_box = [x0, y0, x1, y1] as 0–1 fractions of the page."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(data)
    try:
        if page_no < 1 or page_no > len(doc):
            return None
        pil = doc[page_no - 1].render(scale=scale).to_pil()
        W, H = pil.size
        x0, y0, x1, y1 = [min(1.0, max(0.0, float(v))) for v in frac_box]
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if (x1 - x0) * W < 20 or (y1 - y0) * H < 20:
            return None
        crop = pil.crop((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)))
        buf = io.BytesIO()
        crop.convert('RGB').save(buf, 'PNG', optimize=True)
        return buf.getvalue()
    finally:
        doc.close()
