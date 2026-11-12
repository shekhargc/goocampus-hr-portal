"""Turns a stream of lines + images (from Word or a typed PDF) into questions.

Both readers feed the same stream, so one set of rules covers every format:
    ('line', text, page)            one line / paragraph of text
    ('image', image_dict, page)     a picture, in reading order (image_dict: data, ext, bbox?)

Recognised layout (labels are case-insensitive; the founder's Word template and the sample PDF):
    Q12. <stem…>            or  Q12   SURGERY / RADIOLOGY   (subject tags)   or  12. <stem>
    IMAGE FINDING …         optional box describing an image (kept for the team only)
    A. <option>  ✓          options A–D; a ✓ / ✔ / (correct) / leading * marks the key
    Answer: C               or  ANSWER  ⏎  C. <option text>
    Explanation: …          or boxes HOW TO SOLVE / DEEP-DIVE / PATTERN / KEY FACT …
    Subject: …   Topic: …   optional, anywhere after the question header
    <picture>               before the answer → question image; after → explanation image
"""
import re

OPT_LETTERS = 'ABCDEFGH'
TICK_CHARS = '✓✔☑✅'

RE_Q_HEAD = re.compile(r'^Q(?:uestion)?\s*(?:no\.?\s*)?(\d{1,4})?\s*([.):\-–]|\s|$)\s*(.*)$', re.I)
RE_NUM_HEAD = re.compile(r'^(\d{1,4})\s*[.)]\s+(.+)$')
RE_OPT = re.compile(r'^\(?\s*\*?\s*([A-Ha-h])\s*[.):]\s*(.*)$')
RE_ANSWER = re.compile(r'^(?:answer\s+key|answer|ans|correct\s+(?:answer|option)|key)\b\s*\.?\s*[:\-–]?\s*(.*)$', re.I)
RE_LETTER = re.compile(r'^\(?\s*(?:option\s+)?([A-Ha-h1-8])\s*(?:[.):\-–]|\s|$)', re.I)
RE_NUM_OPT = re.compile(r'^\(?\s*\*?\s*([1-8])\s*[.)]\s*(.+)$')
RE_EXPL = re.compile(r'^(explanation|solution|rationale|exp)\b\s*\.?\s*[:\-–]?\s*(.*)$', re.I)
RE_SUBJECT = re.compile(r'^subject\s*[:\-–]\s*(.+)$', re.I)
RE_TOPIC = re.compile(r'^(?:topic|sub-?topic|chapter)\s*[:\-–]\s*(.+)$', re.I)
RE_IMG_BOX = re.compile(r'^(?:image|video|picture|diagram|photo|clinical image)\s+(?:finding|description)\b.*$', re.I)
RE_SECTION_LINE = re.compile(r'^section\s+[A-E]\b(?!\w)', re.I)
# heading text a PDF sometimes drops into the middle of a paragraph ("SECTION B Clinical … Questions 37–72.")
RE_HEADING_LEAK = re.compile(r'\s*SECTION [A-E]\b[^.]{0,80}?Questions \d+\s*[–-]\s*\d+\.?\s*')
RE_TAGS = re.compile(r"^[A-Z][A-Z0-9 &/,()'\-]{1,80}$")
# a stem usually opens like this — used to split an image-description box from the stem that follows it
RE_STEM_START = re.compile(
    r'^(?:A|An)\s+(?:\d+|new|newborn|neonate|pregnant|primi|multi|patient|man|woman|male|female|boy|girl|child|'
    r'infant|toddler|teen|elderly|young|middle|old|healthy|known|chronic)\b|'
    r'^(?:Which|What|Identify|Name|Most|All|In a|During|While|Regarding|True|False|Choose)\b', re.I)

EXPL_BOXES = {  # label (normalised) → shown heading
    'how to solve': 'How to solve', 'deep-dive': 'Deep-dive', 'deep dive': 'Deep-dive',
    'pattern': 'Pattern', 'key fact': 'Key fact', 'key point': 'Key point', 'key points': 'Key points',
    'high yield': 'High yield', 'high-yield': 'High yield', 'reference': 'Reference', 'references': 'Reference',
    'explanation': 'Explanation', 'solution': 'Explanation', 'rationale': 'Explanation',
}


def _clean(s):
    return re.sub(r'[ \t ]+', ' ', (s or '')).strip()


def _strip_tick(text):
    """'Vagal maneuvers   ✓' → ('Vagal maneuvers', True); '* Adenosine' handled by RE_OPT."""
    t = text.rstrip()
    tick = False
    for marker in list(TICK_CHARS) + ['(correct)', '[correct]', '(Correct)', '[Correct]']:
        if t.endswith(marker):
            t, tick = t[:-len(marker)].rstrip(), True
    if t.startswith('*'):
        t, tick = t[1:].lstrip(), True
    return t, tick


def _ans_letter(v, letters):
    v = v.upper()
    if v.isdigit():
        i = int(v) - 1
        return letters[i] if 0 <= i < len(letters) else ''
    return v


def _new_q(no, page):
    return {'no': no, 'tags': [], 'subject_raw': '', 'topic_raw': '', 'stem': [], 'image_desc': [],
            'options': {}, 'ticks': [], 'answer': '', 'answer_text': '', 'sections': [],
            'images': [], 'pages': [page, page], 'cleaned': [], 'numeric_opts': False}


def parse_stream(items, n_options=4, joiner=' '):
    """items → list of question dicts (see _new_q) + list of file-level notes.

    joiner: how consecutive text items of one field are glued — ' ' for wrapped PDF lines,
    '\n' for Word paragraphs.
    """
    letters = OPT_LETTERS[:max(2, n_options)]
    qs, notes = [], []
    cur, field, last_opt, want_answer_line = None, None, None, False
    expected_next = 1
    orphan_images = 0

    def start(no, page):
        nonlocal cur, field, last_opt, want_answer_line, expected_next
        cur = _new_q(no if no is not None else expected_next, page)
        qs.append(cur)
        field, last_opt, want_answer_line = 'stem', None, False
        expected_next = cur['no'] + 1

    def add_text(text):
        if field == 'stem':
            cur['stem'].append(text)
        elif field == 'image_desc':
            # the description box ends where the stem starts
            if cur['image_desc'] and RE_STEM_START.match(text) and cur['image_desc'][-1].rstrip().endswith(('.', ')')):
                cur['stem'].append(text)
                return 'stem'
            cur['image_desc'].append(text)
        elif field == 'option' and last_opt:
            t, tick = _strip_tick(text)
            cur['options'][last_opt].append(t)
            if tick and last_opt not in cur['ticks']:
                cur['ticks'].append(last_opt)
        elif field == 'answer':
            cur['answer_text'] = _clean(cur['answer_text'] + ' ' + text)
        elif field and field.startswith('sec:'):
            cur['sections'][-1][1].append(text)
        return field

    for kind, payload, page in items:
        if kind == 'image':
            if cur is None:
                orphan_images += 1
                continue
            role = 'explanation' if field in ('answer',) or (field or '').startswith('sec:') else 'stem'
            img = dict(payload)
            img['role'] = role
            img['page'] = page
            cur['images'].append(img)
            cur['pages'][1] = max(cur['pages'][1], page)
            continue

        raw = payload
        text = _clean(raw)
        if not text:
            continue
        if RE_HEADING_LEAK.search(text):
            text2 = _clean(RE_HEADING_LEAK.sub(' ', text))
            if cur is not None:
                cur['cleaned'].append('heading text removed')
            text = text2
            if not text:
                continue
        if RE_SECTION_LINE.match(text) and (cur is None or field in ('stem',) and not cur['stem']):
            continue

        # ── a new question? ──
        m = RE_Q_HEAD.match(text)
        is_head = False
        if m and (m.group(1) or m.group(2).strip()):
            no = int(m.group(1)) if m.group(1) else None
            rest = m.group(3).strip()
            is_head = True          # an explicit "Q12" / "Q:" / "Question 12" always opens a question
        if not is_head and cur is not None and field not in ('stem', 'image_desc', 'option'):
            m2 = RE_NUM_HEAD.match(text)
            if m2 and int(m2.group(1)) == expected_next:
                m, no, rest, is_head = m2, int(m2.group(1)), m2.group(2).strip(), True
        if not is_head and cur is None:
            m2 = RE_NUM_HEAD.match(text)
            if m2:
                m, no, rest, is_head = m2, int(m2.group(1)), m2.group(2).strip(), True
        if is_head:
            start(no, page)
            if rest:
                if RE_TAGS.match(rest) and not RE_STEM_START.match(rest) and any(c.isalpha() for c in rest):
                    cur['tags'] = [t.strip() for t in re.split(r'\s*[/,|]\s*', rest) if t.strip()]
                else:
                    cur['stem'].append(rest)
            continue
        if cur is None:
            continue
        cur['pages'][1] = max(cur['pages'][1], page)

        # ── labelled lines ──
        ms = RE_SUBJECT.match(text)
        if ms:
            cur['subject_raw'] = ms.group(1).strip()
            continue
        mt = RE_TOPIC.match(text)
        if mt:
            cur['topic_raw'] = mt.group(1).strip()
            continue
        if RE_IMG_BOX.match(text) and field in ('stem', 'image_desc') and not cur['options']:
            field = 'image_desc'
            continue
        box = EXPL_BOXES.get(text.lower().rstrip(':').strip())
        if box and field not in ('stem', 'image_desc'):
            cur['sections'].append([box, []])
            field = 'sec:' + box
            want_answer_line = False
            continue
        me = RE_EXPL.match(text)
        if me and field not in ('stem', 'image_desc') and (me.group(2) or text.rstrip().endswith(':') or
                                                            text.lower().strip() in ('explanation', 'solution')):
            cur['sections'].append(['Explanation', [me.group(2)] if me.group(2) else []])
            field = 'sec:Explanation'
            want_answer_line = False
            continue
        ma = RE_ANSWER.match(text)
        if ma and field in ('option', 'answer') or (ma and field == 'stem' and len(cur['options']) >= 2):
            rest = ma.group(1).strip()
            ml = RE_LETTER.match(rest) if rest else None
            if ml:
                cur['answer'] = _ans_letter(ml.group(1), letters)
                cur['answer_text'] = _clean(rest[ml.end():])
                want_answer_line = False
            elif rest:
                cur['answer_text'] = rest          # "Answer: Vagal maneuvers" — matched to an option below
                want_answer_line = False
            else:
                want_answer_line = True
            field = 'answer'
            continue
        if want_answer_line:
            ml = RE_LETTER.match(text)
            if ml:
                cur['answer'] = _ans_letter(ml.group(1), letters)
                cur['answer_text'] = _clean(text[ml.end():])
            else:
                cur['answer_text'] = text
            want_answer_line = False
            continue

        # ── options ──
        mn = RE_NUM_OPT.match(text) if field in ('stem', 'image_desc', 'option') else None
        if mn and (cur['numeric_opts'] or not cur['options']) and int(mn.group(1)) == len(cur['options']) + 1 \
                and int(mn.group(1)) <= len(letters) and (cur['stem'] or cur['image_desc']):
            L = letters[int(mn.group(1)) - 1]
            body, tick = _strip_tick(mn.group(2))
            if text.lstrip('( ').startswith('*'):
                tick = True
            cur['options'][L] = [body]
            cur['numeric_opts'] = True
            if tick and L not in cur['ticks']:
                cur['ticks'].append(L)
            field, last_opt = 'option', L
            continue
        mo = RE_OPT.match(text)
        if mo and field in ('stem', 'image_desc', 'option') and cur['numeric_opts'] and mo.group(1).upper() == 'A':
            # "1. … 2. … 3. …" were statements of the stem (assertion-type question), not options
            for i, (L0, body) in enumerate(cur['options'].items(), 1):
                cur['stem'].append('%d. %s' % (i, joiner.join(body)))
            cur['options'], cur['ticks'], cur['numeric_opts'] = {}, [], False
        if mo and field in ('stem', 'image_desc', 'option'):
            L = mo.group(1).upper()
            expected = letters[len(cur['options'])] if len(cur['options']) < len(letters) else None
            if L == expected or (L in letters and L not in cur['options'] and cur['options']):
                body, tick = _strip_tick(mo.group(2))
                if text.lstrip('( ').startswith('*'):
                    tick = True
                cur['options'][L] = [body]
                if tick and L not in cur['ticks']:
                    cur['ticks'].append(L)
                field, last_opt = 'option', L
                continue

        field = add_text(text) or field

    # ── finish each question ──
    for q in qs:
        q['stem'] = joiner.join(q['stem']).strip()
        q['image_desc'] = joiner.join(q['image_desc']).strip()
        if q['image_desc'] and not q['stem']:
            # a PDF can wrap description + stem into one run of lines: split at the first stem-like sentence
            mm = re.search(r'(?<=[.)])\s+(?=(?:A|An)\s+\d+[- ](?:year|month|day|week)|Which\b|What\b)', q['image_desc'])
            if mm:
                q['stem'] = q['image_desc'][mm.end():].strip()
                q['image_desc'] = q['image_desc'][:mm.start()].strip()
        q['options'] = [(L, joiner.join(v).strip()) for L, v in q['options'].items()]
        q['sections'] = [(label, joiner.join(t).strip()) for label, t in q['sections'] if joiner.join(t).strip()]
        if not q['answer'] and q['answer_text']:
            key = re.sub(r'[^a-z0-9]+', ' ', q['answer_text'].lower()).strip()
            hits = [L for L, t in q['options'] if re.sub(r'[^a-z0-9]+', ' ', t.lower()).strip() == key]
            if len(hits) == 1:
                q['answer'] = hits[0]
        if not q['answer'] and len(q['ticks']) == 1:
            q['answer'] = q['ticks'][0]
    # an index / contents page ("Q61" on its own line) opens "questions" with no options, answer or
    # explanation — those aren't questions; skip them but say so in the report
    skipped = [q for q in qs if not (q['options'] or q['answer'] or q['sections'])]
    if skipped:
        qs = [q for q in qs if q not in skipped]
        where = ', '.join(f"Q{q['no']} (page {q['pages'][0]})" if q['pages'][0] else f"Q{q['no']}" for q in skipped[:8])
        notes.append(f"Skipped {len(skipped)} item(s) that looked like a question number but had no options, "
                     f"answer or explanation — usually an index page: {where}{' …' if len(skipped) > 8 else ''}.")
    if orphan_images:
        notes.append(f'{orphan_images} picture(s) appear before the first question and were ignored.')
    return qs, notes
