"""Word (.docx) → the line/image stream layout.py reads.

Walks the document body in order (paragraphs and table cells), emitting each paragraph's text and
every picture pasted in it, in the order they appear. Word's automatic numbering ("1." / "A." added
by a numbered list, not typed) is not part of the paragraph text, so it is rebuilt here from the
document's numbering definitions — otherwise list-numbered options would lose their letters.
"""
import io
import re

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
V = 'urn:schemas-microsoft-com:vml'
WP = 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'


def _q(ns, tag):
    return '{%s}%s' % (ns, tag)


EXT_BY_TYPE = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/gif': 'gif',
               'image/bmp': 'bmp', 'image/tiff': 'tif', 'image/x-emf': 'emf', 'image/x-wmf': 'wmf',
               'image/webp': 'webp', 'image/svg+xml': 'svg'}


def _to_letters(n, upper=True):
    s = ''
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s if upper else s.lower()


def _to_roman(n, upper=True):
    vals = [(1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'), (100, 'C'), (90, 'XC'), (50, 'L'),
            (40, 'XL'), (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]
    out = ''
    for v, sym in vals:
        while n >= v:
            out += sym
            n -= v
    return out if upper else out.lower()


class _Numbering:
    """Rebuilds the visible label ("12.", "A)") of auto-numbered paragraphs."""

    def __init__(self, doc):
        self.levels = {}       # (numId, ilvl) → (fmt, lvlText, start)
        self.counters = {}     # numId → [count per level]
        self.style_num = {}    # styleId → (numId, ilvl) — numbering that comes from a paragraph style
        try:
            for st in doc.styles.element.findall(_q(W, 'style')):
                ppr = st.find(_q(W, 'pPr'))
                numpr = ppr.find(_q(W, 'numPr')) if ppr is not None else None
                if numpr is not None and numpr.find(_q(W, 'numId')) is not None:
                    il = numpr.find(_q(W, 'ilvl'))
                    self.style_num[st.get(_q(W, 'styleId'))] = (
                        numpr.find(_q(W, 'numId')).get(_q(W, 'val')), int(il.get(_q(W, 'val'))) if il is not None else 0)
        except Exception:
            pass
        try:
            part = doc.part.numbering_part
            root = part.element
        except Exception:
            return
        abstract = {}
        for an in root.findall(_q(W, 'abstractNum')):
            aid = an.get(_q(W, 'abstractNumId'))
            lv = {}
            for l in an.findall(_q(W, 'lvl')):
                ilvl = int(l.get(_q(W, 'ilvl'), '0'))
                fmt = l.find(_q(W, 'numFmt'))
                txt = l.find(_q(W, 'lvlText'))
                st = l.find(_q(W, 'start'))
                lv[ilvl] = (fmt.get(_q(W, 'val')) if fmt is not None else 'decimal',
                            txt.get(_q(W, 'val')) if txt is not None else '%1.',
                            int(st.get(_q(W, 'val'))) if st is not None else 1)
            abstract[aid] = lv
        for num in root.findall(_q(W, 'num')):
            nid = num.get(_q(W, 'numId'))
            an = num.find(_q(W, 'abstractNumId'))
            if an is None:
                continue
            for ilvl, spec in abstract.get(an.get(_q(W, 'val')), {}).items():
                self.levels[(nid, ilvl)] = spec

    def label(self, p_el):
        ppr = p_el.find(_q(W, 'pPr'))
        if ppr is None:
            return ''
        numpr = ppr.find(_q(W, 'numPr'))
        nid_el = numpr.find(_q(W, 'numId')) if numpr is not None else None
        if nid_el is not None:
            ilvl_el = numpr.find(_q(W, 'ilvl'))
            nid = nid_el.get(_q(W, 'val'))
            ilvl = int(ilvl_el.get(_q(W, 'val'))) if ilvl_el is not None else 0
        else:
            ps = ppr.find(_q(W, 'pStyle'))
            sn = self.style_num.get(ps.get(_q(W, 'val'))) if ps is not None else None
            if not sn:
                return ''
            nid, ilvl = sn
        spec = self.levels.get((nid, ilvl))
        if not spec or nid == '0':
            return ''
        cnt = self.counters.setdefault(nid, [0] * 9)
        if cnt[ilvl] == 0:
            cnt[ilvl] = spec[2]
        else:
            cnt[ilvl] += 1
        for deeper in range(ilvl + 1, 9):
            cnt[deeper] = 0
        out = spec[1]
        for lvl in range(ilvl + 1):
            s = self.levels.get((nid, lvl))
            if not s:
                continue
            n = cnt[lvl] or s[2]
            fmt = s[0]
            if fmt == 'bullet':
                return ''
            if fmt == 'upperLetter':
                v = _to_letters(n, True)
            elif fmt == 'lowerLetter':
                v = _to_letters(n, False)
            elif fmt == 'upperRoman':
                v = _to_roman(n, True)
            elif fmt == 'lowerRoman':
                v = _to_roman(n, False)
            else:
                v = str(n)
            out = out.replace('%%%d' % (lvl + 1), v)
        return out.strip()


def _iter_block_paragraphs(body):
    """Paragraph elements in document order, descending into tables."""
    for child in body.iterchildren():
        if child.tag == _q(W, 'p'):
            yield child
        elif child.tag == _q(W, 'tbl'):
            for tc in child.iter(_q(W, 'tc')):
                for p in tc.iterchildren(_q(W, 'p')):
                    yield p
        elif child.tag == _q(W, 'sdt'):
            content = child.find(_q(W, 'sdtContent'))
            if content is not None:
                yield from _iter_block_paragraphs(content)


def read_docx(data):
    """bytes → (items, info)."""
    import docx  # python-docx
    doc = docx.Document(io.BytesIO(data))
    numbering = _Numbering(doc)
    rels = doc.part.related_parts
    items = []
    info = {'paragraphs': 0, 'images_found': 0, 'images_unreadable': 0, 'auto_numbered': 0}

    def image_item(rid):
        part = rels.get(rid)
        if part is None:
            info['images_unreadable'] += 1
            return None
        ctype = getattr(part, 'content_type', '') or ''
        ext = EXT_BY_TYPE.get(ctype, (part.partname.split('.')[-1] if '.' in str(part.partname) else 'bin'))
        info['images_found'] += 1
        return ('image', {'data': part.blob, 'ext': ext, 'content_type': ctype or 'application/octet-stream',
                          'source': 'docx'}, 0)

    for p in _iter_block_paragraphs(doc.element.body):
        info['paragraphs'] += 1
        label = numbering.label(p)
        if label:
            info['auto_numbered'] += 1
        buf = [label + ' '] if label else []
        pending_images = []
        for el in p.iter():
            tag = el.tag
            if tag == _q(W, 't'):
                buf.append(el.text or '')
            elif tag == _q(W, 'tab'):
                buf.append(' ')
            elif tag in (_q(W, 'br'), _q(W, 'cr')):
                buf.append('\n')
            elif tag == _q(A, 'blip'):
                rid = el.get(_q(R, 'embed')) or el.get(_q(R, 'link'))
                it = image_item(rid) if rid else None
                if it:
                    pending_images.append((len(''.join(buf)), it))
            elif tag == _q(V, 'imagedata'):
                rid = el.get(_q(R, 'id'))
                it = image_item(rid) if rid else None
                if it:
                    pending_images.append((len(''.join(buf)), it))
        text = ''.join(buf)
        # text before a picture comes first, then the picture, then text after it
        cut = 0
        for pos, it in pending_images:
            for ln in re.split(r'\n', text[cut:pos]):
                if ln.strip():
                    items.append(('line', ln, 0))
            items.append(it)
            cut = pos
        for ln in re.split(r'\n', text[cut:]):
            if ln.strip():
                items.append(('line', ln, 0))
    return items, info
