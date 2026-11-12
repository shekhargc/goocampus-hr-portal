"""Excel (.xlsx) → question dicts, for text-only questions.

One row per question. Headers are matched loosely (first 10 rows searched), e.g.
    Q No | Question | A | B | C | D | Answer | Explanation | Subject | Topic
"Option A" / "Opt 1" / "Correct Answer" / "Solution" etc. also work. Pictures in Excel are not
read (the report says so) — image questions go in the Word template.
"""
import io
import re

HEADER_ALIASES = {
    'no': ('q no', 'qno', 'q', 'no', 'sl no', 's no', 'sno', 'question no', 'question number', 'q number', '#'),
    'stem': ('question', 'questions', 'stem', 'question text', 'question stem'),
    'A': ('a', 'option a', 'opt a', 'option 1', 'opt 1', '1'),
    'B': ('b', 'option b', 'opt b', 'option 2', 'opt 2', '2'),
    'C': ('c', 'option c', 'opt c', 'option 3', 'opt 3', '3'),
    'D': ('d', 'option d', 'opt d', 'option 4', 'opt 4', '4'),
    'answer': ('answer', 'ans', 'correct answer', 'correct option', 'key', 'answer key', 'correct'),
    'explanation': ('explanation', 'solution', 'rationale', 'explanations'),
    'subject': ('subject',),
    'topic': ('topic', 'sub topic', 'subtopic', 'chapter'),
}


def _norm(s):
    return re.sub(r'[^a-z0-9#]+', ' ', str(s or '').lower()).strip()


def read_xlsx(data):
    """bytes → (questions, notes) — the same question dict shape layout.parse_stream returns."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    questions, notes = [], []
    pictures = 0
    for ws in wb.worksheets:
        pictures += len(getattr(ws, '_images', []) or [])
        rows = list(ws.iter_rows(values_only=True))
        hdr_idx, cols = None, {}
        for i, row in enumerate(rows[:10]):
            found = {}
            for j, cell in enumerate(row or ()):
                key = _norm(cell)
                for field, names in HEADER_ALIASES.items():
                    if key in names and field not in found:
                        found[field] = j
            if 'stem' in found and 'A' in found and 'B' in found:
                hdr_idx, cols = i, found
                break
        if hdr_idx is None:
            if any(any(c not in (None, '') for c in (r or ())) for r in rows):
                notes.append(f'Sheet "{ws.title}": no header row with Question / A / B columns — skipped.')
            continue
        for r_i, row in enumerate(rows[hdr_idx + 1:], start=hdr_idx + 2):
            def cell(field):
                j = cols.get(field)
                if j is None or j >= len(row):
                    return ''
                v = row[j]
                if v is None:
                    return ''
                if isinstance(v, float) and v.is_integer():
                    v = int(v)
                return str(v).strip()
            stem = cell('stem')
            opts = [(L, cell(L)) for L in 'ABCD' if L in cols]
            if not stem and not any(t for _, t in opts):
                continue
            no_raw = cell('no')
            try:
                no = int(float(no_raw)) if no_raw else None
            except ValueError:
                no = None
            ans_raw = cell('answer')
            m = re.match(r'^\(?\s*(?:option\s+)?([A-Da-d1-4])\s*\)?\.?\s*$', ans_raw) or \
                re.match(r'^\(?\s*([A-Da-d])\s*[.):\-–]', ans_raw)
            answer = ''
            if m:
                v = m.group(1).upper()
                answer = 'ABCD'[int(v) - 1] if v.isdigit() else v
            elif ans_raw:
                key = _norm(ans_raw)
                hits = [L for L, t in opts if _norm(t) == key]
                answer = hits[0] if len(hits) == 1 else ''
            expl = cell('explanation')
            questions.append({
                'no': no if no is not None else len(questions) + 1,
                'tags': [], 'subject_raw': cell('subject'), 'topic_raw': cell('topic'),
                'stem': stem, 'image_desc': '', 'options': opts, 'ticks': [], 'answer': answer,
                'answer_text': ans_raw if not answer else '',
                'sections': [('Explanation', expl)] if expl else [],
                'images': [], 'pages': [0, 0], 'cleaned': [],
                'source_ref': f'{ws.title} row {r_i}',
            })
    if pictures:
        notes.append(f'{pictures} picture(s) in the workbook were not read — put image questions in the Word template.')
    return questions, notes
