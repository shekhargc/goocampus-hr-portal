"""GooCampus-branded PDF of one NEET-PG choice list (one counselling body, rounds 1-3).

Used by the Counselling Desk on goocampus.in (team builds a list for an internal /
paid doctor -> Download PDF / Email PDF) and by the doctor's own Download PDF.
Pure-Python (fpdf2) so it renders on Render with no system libraries. (founder 2026-10-15)
"""
import os
import json
import logging
from datetime import datetime, timedelta

from fpdf import FPDF

from pg_admin.routes.api_choice import live_fees

_LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'logo-full.png')
_NAVY = (15, 27, 51)
_ORANGE = (234, 108, 30)
_GREY = (107, 114, 128)
_CHANCE = {'strong': 'Strong', 'high': 'High', 'good': 'Good',
           'borderline': 'Borderline', 'verylow': 'Very low', 'unknown': '-'}
_CHANCE_RGB = {'strong': (22, 101, 52), 'high': (21, 128, 61), 'good': (37, 99, 235),
               'borderline': (180, 83, 9), 'verylow': (185, 28, 28)}

_SUBS = {'–': '-', '—': '-', '‘': "'", '’': "'", '“': '"',
         '”': '"', '…': '...', '₹': 'Rs.', ' ': ' ', '•': '-'}


def _t(v):
    """fpdf core fonts are latin-1 only - swap common typographic chars, drop the rest."""
    s = '' if v is None else str(v)
    for a, b in _SUBS.items():
        s = s.replace(a, b)
    return s.encode('latin-1', 'replace').decode('latin-1')


def _ist_now():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def _money(v):
    """Rs. with Indian digit grouping (12,34,567); '-' when unknown."""
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return '-'
    if n <= 0:
        return '-'
    digits = str(n)
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return 'Rs. ' + ','.join(groups + [tail])


def _dr(name):
    n = (name or '').strip()
    if not n:
        return 'Doctor'
    return n if n.lower().startswith('dr') else 'Dr. ' + n


class _PDF(FPDF):
    footer_note = ''

    def footer(self):
        self.set_y(-12)
        self.set_font('Helvetica', '', 7.5)
        self.set_text_color(*_GREY)
        self.cell(0, 5, _t(self.footer_note), align='L')
        self.cell(0, 5, f'Page {self.page_no()}/{{nb}}', align='R')


def load_set(conn, set_id):
    """(set dict, doctor dict, {1:[items],2:[...],3:[...]}) or (None, None, None)."""
    s = conn.execute("SELECT * FROM pg_choice_sets WHERE id = ?", [set_id]).fetchone()
    if not s:
        return None, None, None
    s = dict(s)
    for k in ('specialties', 'quota_categories'):
        try:
            s[k] = json.loads(s.get(k) or '[]')
        except Exception:
            s[k] = []
    d = conn.execute("SELECT id, name, mobile, email, state, neet_pg_rank, neet_pg_score, "
                     "target_speciality FROM pg_users WHERE id = ?", [s['user_id']]).fetchone()
    items = [dict(r) for r in conn.execute(
        "SELECT * FROM pg_choice_items WHERE set_id = ? ORDER BY round, position, id",
        [set_id]).fetchall()]
    live_fees(conn, items)
    rounds = {1: [], 2: [], 3: []}
    for it in items:
        rounds.setdefault(it['round'], []).append(it)
    return s, (dict(d) if d else {}), rounds


def set_title(s):
    if (s.get('scope') or '') == 'mcc':
        return 'MCC - All India Quota'
    return (s.get('label') or s.get('state') or s.get('authority') or 'State counselling').strip()


def pdf_filename(s, d):
    nm = ''.join(ch if ch.isalnum() else '_' for ch in (d.get('name') or 'doctor')).strip('_')[:40]
    body = ''.join(ch if ch.isalnum() else '_' for ch in set_title(s)).strip('_')[:40]
    return f"GooCampus_Choice_List_{nm}_{body}.pdf"


def build_pdf(conn, set_id, prepared_by=''):
    """Return (pdf_bytes, filename) or (None, None) if the set doesn't exist."""
    s, d, rounds = load_set(conn, set_id)
    if not s:
        return None, None
    pdf = _PDF(orientation='L', unit='mm', format='A4')
    pdf.set_margins(10, 10, 10)
    pdf.set_auto_page_break(True, margin=16)
    pdf.alias_nb_pages()
    pdf.footer_note = ('Prepared by GooCampus from the previous year\'s NEET-PG closing ranks. '
                       'Cut-offs change every year - check the official seat matrix before locking your choices.')
    pdf.add_page()

    # ── Header ──
    try:
        if os.path.exists(_LOGO):
            pdf.image(_LOGO, x=10, y=8, h=13)
    except Exception as e:
        logging.warning("choice_pdf logo: %s", e)
    pdf.set_xy(80, 9)
    pdf.set_font('Helvetica', 'B', 15)
    pdf.set_text_color(*_NAVY)
    pdf.cell(0, 7, 'NEET-PG Choice List', align='R', new_x='LMARGIN', new_y='NEXT')
    pdf.set_x(80)
    pdf.set_font('Helvetica', 'B', 11)
    pdf.set_text_color(*_ORANGE)
    pdf.cell(0, 6, _t(set_title(s)), align='R', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(4)
    pdf.set_draw_color(*_ORANGE)
    pdf.set_line_width(0.6)
    pdf.line(10, pdf.get_y(), 287, pdf.get_y())
    pdf.ln(3)

    # ── Doctor box ──
    rank = s.get('rank') or d.get('neet_pg_rank')
    qc = s.get('quota_categories') or []
    if qc:
        qtxt = '; '.join(
            f"{x.get('quota') or ''}{(' (' + ', '.join(x.get('categories') or []) + ')') if x.get('categories') else ''}"
            for x in qc if isinstance(x, dict))
    else:
        qtxt = ' / '.join(v for v in (s.get('quota'), s.get('category')) if v)
    specs = ', '.join(s.get('specialties') or []) or (d.get('target_speciality') or '')
    rows = [
        ('Doctor', _dr(d.get('name'))),
        ('NEET-PG rank', f"{rank:,}" if isinstance(rank, int) else (str(rank) if rank else '-')),
        ('NEET-PG score', str(d.get('neet_pg_score')) if d.get('neet_pg_score') else '-'),
        ('Quota / category', qtxt or '-'),
        ('Specialities', specs or '-'),
        ('Prepared', f"{_ist_now().strftime('%d %b %Y, %I:%M %p')} IST"
                     + (f" by {prepared_by} (GooCampus)" if prepared_by else '')),
    ]
    pdf.set_font('Helvetica', '', 9.5)
    for lbl, val in rows:
        pdf.set_text_color(*_GREY)
        pdf.set_font('Helvetica', '', 9)
        pdf.cell(32, 5.6, _t(lbl))
        pdf.set_text_color(*_NAVY)
        pdf.set_font('Helvetica', 'B', 9.5)
        pdf.multi_cell(0, 5.6, _t(val), new_x='LMARGIN', new_y='NEXT')
    pdf.ln(2)
    if (s.get('owner') or 'client') == 'team':
        from pg_admin.data.choice_log import DISCLAIMER
        pdf.set_fill_color(255, 247, 237)
        pdf.set_draw_color(253, 186, 116)
        pdf.set_text_color(124, 45, 18)
        pdf.set_font('Helvetica', '', 8.6)
        pdf.multi_cell(0, 4.6, _t('Please note: ' + DISCLAIMER), border='L', fill=True,
                       new_x='LMARGIN', new_y='NEXT')
        pdf.set_fill_color(255, 255, 255)
        pdf.ln(1)

    # ── Rounds ──
    widths = (10, 88, 62, 30, 24, 22, 22, 19)
    heads = ('#', 'College', 'Course', 'Quota', 'Category', 'Closing rank', 'Fee / year', 'Chance')
    any_rows = False
    for rnd in (1, 2, 3):
        items = rounds.get(rnd) or []
        if not items:
            continue
        any_rows = True
        if pdf.get_y() > 170:
            pdf.add_page()
        pdf.ln(2)
        pdf.set_font('Helvetica', 'B', 11.5)
        pdf.set_text_color(*_NAVY)
        pdf.cell(0, 7, f'Round {rnd}  ({len(items)} choice{"s" if len(items) != 1 else ""})',
                 new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('Helvetica', '', 8.3)
        pdf.set_draw_color(220, 224, 230)
        pdf.set_line_width(0.2)
        with pdf.table(col_widths=widths, text_align=('CENTER', 'LEFT', 'LEFT', 'LEFT', 'LEFT', 'RIGHT', 'RIGHT', 'CENTER'),
                       line_height=4.6, headings_style=_head_style(), first_row_as_headings=True,
                       repeat_headings=1) as table:
            hr = table.row()
            for h in heads:
                hr.cell(h)
            for i, it in enumerate(items, start=1):
                r = table.row()
                ch = (it.get('chance') or 'unknown').lower()
                cr = it.get('closing_rank')
                vals = (str(i), _t(it.get('institute')), _t(it.get('course')), _t(it.get('quota')),
                        _t(it.get('category')), f"{cr:,}" if isinstance(cr, int) else (str(cr) if cr else '-'),
                        _money(it.get('fee')), _CHANCE.get(ch, ch.title()))
                for j, v in enumerate(vals):
                    if j == 7 and ch in _CHANCE_RGB:
                        r.cell(v, style=_chance_style(_CHANCE_RGB[ch]))
                    else:
                        r.cell(v)
    if not any_rows:
        pdf.set_font('Helvetica', 'I', 10)
        pdf.set_text_color(*_GREY)
        pdf.cell(0, 8, 'No colleges have been added to this choice list yet.', new_x='LMARGIN', new_y='NEXT')

    pdf.ln(4)
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(*_GREY)
    pdf.multi_cell(0, 4.2, _t(
        'Chance compares your rank with last year\'s closing rank for that seat in that round: '
        'Strong / High / Good = within last year\'s closing rank, Borderline = slightly beyond it, '
        'Very low = well beyond it. Fees are annual tuition as last published and may change. '
        'Questions? Write to info@goocampus.in or call your GooCampus counsellor.'))
    out = pdf.output()
    return bytes(out), pdf_filename(s, d)


def _head_style():
    from fpdf.fonts import FontFace
    return FontFace(emphasis='BOLD', color=(255, 255, 255), fill_color=_NAVY)


def _chance_style(rgb):
    from fpdf.fonts import FontFace
    return FontFace(emphasis='BOLD', color=rgb)
