"""The check report: what's wrong with each imported question, in plain words.

Severity:  error → the question can't be approved until fixed
           warn  → worth a look, doesn't block
           info  → something the importer fixed by itself
"""
import collections
import hashlib
import re

from exam_engine.subjects import norm_tag, pretty_tag

FLAG_TEXT = {
    'no_stem':          ('error', 'Question text is missing.'),
    'option_count':     ('error', 'Has {n} options — needs exactly {need}.'),
    'blank_option':     ('error', 'Option {L} is empty.'),
    'no_answer':        ('error', 'No correct answer found.'),
    'answer_mismatch':  ('error', 'The ✓ mark ({tick}) and the Answer line ({ans}) disagree.'),
    'multi_ticks':      ('error', 'More than one option is ticked ({ticks}).'),
    'answer_not_option': ('error', 'The answer ({ans}) is not one of the options.'),
    'image_missing':    ('error', 'The question is built on an image, but no image is attached.'),
    'subject_unmapped': ('error', 'Subject not recognised ({raw}) — choose one of the NEET PG subjects.'),
    'dup_in_file':      ('error', 'Same question as Q{other} in this file.'),
    'dup_in_bank':      ('error', 'Already in the question bank (question #{other}).'),
    'image_maybe':      ('warn', 'The question mentions "{word}" but has no image — check whether one is needed.'),
    'subject_guessed':  ('warn', 'Subject set to {subject} from the tag "{used}" (first tag "{raw}" isn\'t a NEET PG subject).'),
    'dup_option':       ('warn', 'Options {a} and {b} have the same text.'),
    'no_explanation':   ('warn', 'No explanation — doctors will see only the correct answer.'),
    'doubled_words':    ('warn', 'Repeated words: “{text}”.'),
    'answer_text_mismatch': ('warn', 'The Answer line says “{text}”, which differs from option {L}.'),
    'heading_removed':  ('info', 'Stray heading text was removed from the explanation.'),
}

# short titles for the file-level report table
FLAG_TITLE = {
    'no_stem': 'Question text missing', 'option_count': 'Not exactly 4 options', 'blank_option': 'An option is empty',
    'no_answer': 'No correct answer', 'answer_mismatch': '✓ mark and Answer line disagree',
    'multi_ticks': 'More than one option ticked', 'answer_not_option': 'Answer is not one of the options',
    'image_missing': 'Built on an image, but no image attached', 'subject_unmapped': 'Subject not recognised',
    'dup_in_file': 'Repeated in this file', 'dup_in_bank': 'Already in the question bank',
    'image_maybe': 'Mentions an image but has none', 'subject_guessed': 'Subject taken from the second tag',
    'dup_option': 'Two options have the same text', 'no_explanation': 'No explanation',
    'doubled_words': 'Repeated words in the text', 'answer_text_mismatch': 'Answer line text differs from the option',
    'heading_removed': 'Stray heading text removed', 'image_format': 'Picture in a format browsers can\'t show',
}

RE_IMAGE_WORDS = re.compile(
    r'\b(shown|given below|image|photograph|picture|figure|identify the|radiograph|x-ray shown|'
    r'the ecg|this ecg|fundus photograph|smear shown|specimen shown)\b', re.I)
RE_DOUBLED = re.compile(r'\b(\w+(?:\s+\w+){1,3})\s+\1\b', re.I)


def flag(code, **kw):
    sev, text = FLAG_TEXT[code]
    try:
        msg = text.format(**kw)
    except (KeyError, IndexError):
        msg = text
    return {'code': code, 'severity': sev, 'message': msg}


def _norm_text(s):
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', (s or '').lower())).strip()


def fingerprint(stem, options):
    """Same stem + same set of options (any order) = same question."""
    key = _norm_text(stem) + '|' + '|'.join(sorted(_norm_text(t) for t in options))
    return hashlib.sha1(key.encode('utf-8')).hexdigest()


def resolve_subject(q, alias_map, subjects):
    """→ (subject_name | None, topic, raw_lead, flags). alias_map: norm tag → subject name."""
    subj_by_norm = {norm_tag(s): s for s in subjects}
    cands = [c for c in ([q.get('subject_raw')] + list(q.get('tags') or [])) if c and c.strip()]
    if not cands:
        return None, (q.get('topic_raw') or '').strip(), '', [flag('subject_unmapped', raw='none given')]

    def lookup(c):
        n = norm_tag(c)
        return subj_by_norm.get(n) or alias_map.get(n)

    lead = cands[0]
    subject = lookup(lead)
    flags = []
    if not subject:
        for c in cands[1:]:
            s = lookup(c)
            if s:
                subject = s
                flags.append(flag('subject_guessed', subject=s, used=pretty_tag(c), raw=pretty_tag(lead)))
                break
    if not subject:
        flags.append(flag('subject_unmapped', raw='“%s”' % pretty_tag(lead)))
    topic = (q.get('topic_raw') or '').strip()
    if not topic:
        # first tag that isn't itself one of the subjects, e.g. MEDICINE / CARDIOLOGY → Cardiology
        for c in cands:
            if norm_tag(c) not in subj_by_norm:
                topic = pretty_tag(c)
                break
    return subject, topic, pretty_tag(lead), flags


def check_question(q, n_options=4):
    """Flags that depend on the question alone (subject + duplicates are added by check_batch)."""
    out = []
    opts = q.get('options') or []
    letters = [L for L, _ in opts]
    if not (q.get('stem') or '').strip():
        out.append(flag('no_stem'))
    if len(opts) != n_options:
        out.append(flag('option_count', n=len(opts), need=n_options))
    for L, t in opts:
        if not (t or '').strip():
            out.append(flag('blank_option', L=L))
    seen = {}
    for L, t in opts:
        k = _norm_text(t)
        if k and k in seen:
            out.append(flag('dup_option', a=seen[k], b=L))
        seen.setdefault(k, L)
    ticks, ans = q.get('ticks') or [], q.get('answer') or ''
    if len(ticks) > 1:
        out.append(flag('multi_ticks', ticks=', '.join(ticks)))
    if ticks and ans and len(ticks) == 1 and ticks[0] != ans:
        out.append(flag('answer_mismatch', tick=ticks[0], ans=ans))
    if not ans:
        out.append(flag('no_answer'))
    elif letters and ans not in letters:
        out.append(flag('answer_not_option', ans=ans))
    elif q.get('answer_text'):
        opt_text = dict(opts).get(ans, '')
        a, b = _norm_text(q['answer_text']), _norm_text(opt_text)
        if a and b and a != b and not a.startswith(b) and not b.startswith(a):
            out.append(flag('answer_text_mismatch', text=q['answer_text'][:80], L=ans))
    stem_imgs = [i for i in (q.get('images') or []) if i.get('role', 'stem') == 'stem']
    if q.get('image_desc') and not stem_imgs:
        out.append(flag('image_missing'))
    elif not stem_imgs:
        m = RE_IMAGE_WORDS.search(q.get('stem') or '')
        if m:
            out.append(flag('image_maybe', word=m.group(1)))
    if not any((t or '').strip() for _, t in (q.get('sections') or [])):
        out.append(flag('no_explanation'))
    texts = [q.get('stem') or ''] + [t for _, t in (q.get('sections') or [])]
    for t in texts:
        m = RE_DOUBLED.search(t)
        if m and not m.group(1).isdigit():
            out.append(flag('doubled_words', text=m.group(0)[:80]))
            break
    if q.get('cleaned'):
        out.append(flag('heading_removed'))
    return out


def check_batch(questions, alias_map, subjects, bank_fingerprints=None, n_options=4):
    """Adds q['flags'], q['subject'], q['topic'], q['fingerprint'] to every question and returns the
    file-level summary (counts, missing numbers, answer spread, subject spread)."""
    bank_fingerprints = bank_fingerprints or {}
    first_by_fp = {}
    for q in questions:
        flags = check_question(q, n_options)
        subject, topic, lead, sflags = resolve_subject(q, alias_map, subjects)
        q['subject'], q['topic'], q['lead_tag'] = subject, topic, lead
        flags.extend(sflags)
        fp = fingerprint(q.get('stem'), [t for _, t in (q.get('options') or [])])
        q['fingerprint'] = fp
        if (q.get('stem') or '').strip():
            if fp in first_by_fp:
                flags.append(flag('dup_in_file', other=first_by_fp[fp]))
            else:
                first_by_fp[fp] = q.get('no')
            if fp in bank_fingerprints:
                flags.append(flag('dup_in_bank', other=bank_fingerprints[fp]))
        q['flags'] = flags

    nos = [q['no'] for q in questions if q.get('no') is not None]
    counts = collections.Counter(nos)
    missing = []
    if nos:
        lo, hi = min(nos), max(nos)
        if hi - lo < 5000:
            missing = [n for n in range(lo, hi + 1) if n not in counts]
    answers = collections.Counter(q.get('answer') or '?' for q in questions)
    flag_counts = collections.Counter(f['code'] for q in questions for f in q['flags'])
    n_err = sum(1 for q in questions if any(f['severity'] == 'error' for f in q['flags']))
    summary = {
        'total': len(questions),
        'with_errors': n_err,
        'ready': len(questions) - n_err,
        'missing_numbers': missing[:200],
        'repeated_numbers': sorted(n for n, c in counts.items() if c > 1),
        'answers': dict(sorted(answers.items())),
        'subjects': dict(collections.Counter(q.get('subject') or 'Not set' for q in questions).most_common()),
        'flag_counts': {k: flag_counts[k] for k in FLAG_TEXT if flag_counts.get(k)},
        'with_images': sum(1 for q in questions if q.get('images')),
    }
    total_ans = sum(v for k, v in answers.items() if k != '?')
    if total_ans >= 20:
        top, n = max(((k, v) for k, v in answers.items() if k != '?'), key=lambda kv: kv[1])
        if n / total_ans > 0.45:
            summary['answer_skew'] = (f'The answer is “{top}” in {round(100 * n / total_ans)}% of questions. '
                                      'If options are shuffled for doctors this won\'t show in the exam, '
                                      'but it can mean the answer key needs a second look.')
    return summary
