"""Question importer: Word / typed PDF / Excel → question dicts (+ the check report in checks.py)."""


class ImportProblem(Exception):
    """A file we can't read at all — the message is shown to the team as-is."""


SUPPORTED = ('docx', 'pdf', 'xlsx')


def file_kind(filename):
    ext = (filename or '').rsplit('.', 1)[-1].lower() if '.' in (filename or '') else ''
    if ext in ('xlsx', 'xlsm'):
        return 'xlsx'
    return ext


def parse_file(filename, data, n_options=4):
    """→ {'kind', 'questions', 'notes', 'info'}; raises ImportProblem for unreadable files."""
    kind = file_kind(filename)
    if kind == 'doc':
        raise ImportProblem('This is an old Word file (.doc). Open it in Word and "Save As" .docx, then upload again.')
    if kind == 'xls':
        raise ImportProblem('This is an old Excel file (.xls). Open it in Excel and "Save As" .xlsx, then upload again.')
    if kind not in SUPPORTED:
        raise ImportProblem('Please upload a Word (.docx), PDF or Excel (.xlsx) file.')
    if not data:
        raise ImportProblem('The file is empty.')

    from exam_engine.importer.layout import parse_stream
    if kind == 'docx':
        from exam_engine.importer.docx_reader import read_docx
        try:
            items, info = read_docx(data)
        except Exception as e:
            raise ImportProblem(f'Could not open this Word file ({e.__class__.__name__}). Is it a real .docx?')
        questions, notes = parse_stream(items, n_options=n_options, joiner='\n')
    elif kind == 'pdf':
        from exam_engine.importer.pdf_reader import read_pdf
        try:
            items, info = read_pdf(data)
        except Exception as e:
            raise ImportProblem(f'Could not open this PDF ({e.__class__.__name__}). It may be damaged or password-protected.')
        if info.get('scanned'):
            raise ImportProblem('This PDF is scanned pages (pictures of text), so its words can\'t be read directly. '
                                'Please send the Word file, or a typed PDF.')
        questions, notes = parse_stream(items, n_options=n_options, joiner=' ')
    else:
        from exam_engine.importer.xlsx_reader import read_xlsx
        try:
            questions, notes = read_xlsx(data)
        except Exception as e:
            raise ImportProblem(f'Could not open this Excel file ({e.__class__.__name__}).')
        info = {}
    if not questions:
        raise ImportProblem('No questions were found. Each question should start with "Q1." (or "1."), '
                            'followed by options A–D and an "Answer:" line.')
    return {'kind': kind, 'questions': questions, 'notes': notes, 'info': info}
