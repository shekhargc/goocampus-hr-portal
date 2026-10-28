"""Operations › Receipts — payment receipts for internal clients (all pathways).

The team records a payment a client made (amount, date, what for, mode + reference),
the portal gives it a permanent receipt number (GC/RCPT/<FY>/NNNN), and the receipt can
be downloaded as a GooCampus-branded PDF or emailed to the client (+ extra addresses).
A receipt, not an invoice: INR only, no GST, no GSTIN, no signature ("GooCampus Team").
Edits never change the receipt number; every create/edit/send/cancel is logged.
Records live only here — they do not feed the payments ledger. (founder 2026-10-28)
"""
import logging
import os
from datetime import datetime, timedelta

from fpdf import FPDF

_LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'logo-full.png')
_LOGO_WHITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'logo-white.png')
_NAVY = (15, 27, 51)
_ORANGE = (234, 108, 30)
_GRAY = (100, 110, 125)

DESC_MAX = 400   # with SERVICE_MAX, keeps every receipt on one page
SERVICE_MAX = 150
PAYMENT_MODES = ['Bank transfer (NEFT/RTGS/IMPS)', 'UPI', 'Debit / Credit card', 'Cheque', 'Cash', 'Other']


def ensure(conn):
    """Tables are created at request time too (Render cold-start can skip boot DDL)."""
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS ops_receipts (
            id SERIAL PRIMARY KEY,
            receipt_no TEXT UNIQUE NOT NULL,
            fy TEXT,
            seq INTEGER,
            client_id INTEGER,
            registration_number TEXT,
            pathway TEXT,
            client_name TEXT,
            client_email TEXT,
            amount NUMERIC(12,2) NOT NULL,
            paid_on DATE,
            service TEXT,
            description TEXT,
            payment_mode TEXT,
            payment_ref TEXT,
            status TEXT DEFAULT 'active',
            cancel_reason TEXT,
            created_by INTEGER,
            created_by_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by_name TEXT,
            updated_at TIMESTAMP,
            last_sent_at TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS ops_receipt_log (
            id SERIAL PRIMARY KEY,
            receipt_id INTEGER NOT NULL,
            action TEXT,
            detail TEXT,
            by_name TEXT,
            at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ops_receipts_reg ON ops_receipts (registration_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ops_receipt_log_rid ON ops_receipt_log (receipt_id)")
        conn.commit()
    except Exception as e:
        logging.warning("ops_receipts ensure: %s", e)
        try: conn.rollback()
        except Exception: pass


def ist_now():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def fy_label(d):
    """Indian financial year (April–March) → '2026-27'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def next_number(conn):
    """Next receipt number for the current FY. Serialised with a transaction-level
    advisory lock so two people saving at once never get the same number."""
    fy = fy_label(ist_now().date())
    conn.execute("SELECT pg_advisory_xact_lock(732118)")
    seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM ops_receipts WHERE fy = ?", (fy,)).fetchone()['n']
    return f"GC/RCPT/{fy}/{seq:04d}", fy, seq


def log(conn, receipt_id, action, detail, by_name):
    conn.execute("INSERT INTO ops_receipt_log (receipt_id, action, detail, by_name) VALUES (?, ?, ?, ?)",
                 (receipt_id, action, detail or '', by_name or ''))


def inr(v):
    """12345678.5 → '1,23,45,678.50' (Indian grouping)."""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    neg = v < 0
    whole, frac = f"{abs(v):.2f}".split('.')
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ','.join(parts) + ',' + tail
    return ('-' if neg else '') + whole + '.' + frac


_ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve',
         'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
_TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']


def _below_100(n):
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (' ' + _ONES[n % 10] if n % 10 else ''))


def _below_1000(n):
    h, r = divmod(n, 100)
    return ((_ONES[h] + ' Hundred' + (' ' if r else '')) if h else '') + (_below_100(r) if r else '')


def words(amount):
    """50000 → 'Rupees Fifty Thousand Only'; 1250.5 → '... and Fifty Paise Only' (lakh/crore system)."""
    try:
        amount = round(float(amount or 0), 2)
    except (TypeError, ValueError):
        amount = 0.0
    rupees, paise = int(amount), int(round((amount - int(amount)) * 100))
    if rupees == 0 and paise == 0:
        return 'Rupees Zero Only'
    out, n = [], rupees
    for div, name in ((10 ** 7, 'Crore'), (10 ** 5, 'Lakh'), (1000, 'Thousand')):
        q, n = divmod(n, div)
        if q:
            out.append((words(q).replace('Rupees ', '').replace(' Only', '') if q >= 1000 else _below_1000(q))
                       + ' ' + name)
    if n:
        out.append(_below_1000(n))
    s = 'Rupees ' + ' '.join(out) if out else 'Rupees Zero'
    if paise:
        s += ' and ' + _below_100(paise) + ' Paise'
    return s + ' Only'


def _latin(s):
    """Helvetica is Latin-1 only — swap common Unicode punctuation, drop the rest."""
    s = str(s or '')
    for a, b in (('–', '-'), ('—', '-'), ('‘', "'"), ('’', "'"), ('“', '"'),
                 ('”', '"'), ('•', '-'), ('₹', 'Rs. '), (' ', ' '), ('…', '...')):
        s = s.replace(a, b)
    return s.encode('latin-1', 'replace').decode('latin-1')


def _date(d):
    if not d:
        return '-'
    if isinstance(d, str):
        try:
            d = datetime.strptime(d[:10], '%Y-%m-%d')
        except ValueError:
            return d
    return d.strftime('%d %b %Y')


def build_pdf(r, pathway_label='', _compact=False):
    """r: an ops_receipts row (dict). Returns the PDF as bytes. One full A4 page:
    navy header band, from/payment boxes, service table, amount banner (words in bold),
    sign-off placed low on the page so the receipt fills it. (founder 2026-10-29)
    A very long service/description retries in a tighter layout so it stays one page."""
    g = 0.55 if _compact else 1.0   # vertical gap scale
    from core.helpers import format_dr_name
    pdf = FPDF(format='A4')
    pdf.set_auto_page_break(True, margin=27)
    hb = 40 if _compact else 48       # header band height
    pdf.set_margins(16, 14, 16)
    pdf.add_page()
    W, L = pdf.w - 32, 16
    cancelled = (r.get('status') or 'active') == 'cancelled'

    # Header band
    pdf.set_fill_color(*_NAVY); pdf.rect(0, 0, pdf.w, hb, 'F')
    pdf.set_fill_color(*_ORANGE); pdf.rect(0, hb, pdf.w, 2.2, 'F')
    try:
        pdf.image(_LOGO_WHITE, x=L, y=8, h=hb - 18)
    except Exception as e:
        logging.warning("receipt logo: %s", e)
    issued = r.get('created_at')
    issued = (issued + timedelta(hours=5, minutes=30)) if isinstance(issued, datetime) else issued
    pdf.set_xy(L, 8 if _compact else 11)
    pdf.set_font('Helvetica', 'B', 24); pdf.set_text_color(255, 255, 255)
    pdf.cell(W, 11, 'PAYMENT RECEIPT', align='R', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(2)
    pdf.set_font('Helvetica', '', 11); pdf.set_text_color(214, 222, 235)
    pdf.cell(W, 6.5, _latin(f"Receipt No:  {r['receipt_no']}"), align='R', new_x='LMARGIN', new_y='NEXT')
    pdf.cell(W, 6.5, _latin(f"Date issued:  {_date(issued)}"), align='R', new_x='LMARGIN', new_y='NEXT')
    y = hb + (8 if _compact else 12)

    if cancelled:
        pdf.set_fill_color(254, 226, 226); pdf.set_draw_color(252, 165, 165)
        pdf.rect(L, y, W, 11, 'DF')
        pdf.set_xy(L, y); pdf.set_font('Helvetica', 'B', 11.5); pdf.set_text_color(185, 28, 28)
        pdf.cell(W, 11, 'CANCELLED - this receipt is no longer valid', align='C')
        y += 11 + 6 * g

    # Two boxes: Received from | Payment details
    bw, gap, bh = (W - 8) / 2, 8, (42 if _compact else 50)
    pdf.set_draw_color(220, 224, 232); pdf.set_line_width(0.35); pdf.set_fill_color(248, 250, 252)
    pdf.rect(L, y, bw, bh, 'DF'); pdf.rect(L + bw + gap, y, bw, bh, 'DF')
    pdf.set_fill_color(*_ORANGE)
    pdf.rect(L, y, bw, 1.4, 'F'); pdf.rect(L + bw + gap, y, bw, 1.4, 'F')

    pdf.set_xy(L + 6, y + 6)
    pdf.set_font('Helvetica', 'B', 9); pdf.set_text_color(*_GRAY)
    pdf.cell(bw - 12, 5, 'RECEIVED FROM', new_x='LEFT', new_y='NEXT')
    pdf.set_xy(L + 6, pdf.get_y() + 1.5)
    pdf.set_font('Helvetica', 'B', 15); pdf.set_text_color(*_NAVY)
    pdf.multi_cell(bw - 12, 7.5, _latin(format_dr_name(r.get('client_name') or '')), align='L', new_x='LEFT', new_y='NEXT')
    pdf.set_xy(L + 6, pdf.get_y() + 1)
    pdf.set_font('Helvetica', '', 10.5); pdf.set_text_color(60, 60, 60)
    for line in (r.get('registration_number') and f"Reg. No: {r['registration_number']}", pathway_label,
                 r.get('client_email')):
        if line:
            pdf.multi_cell(bw - 12, 6, _latin(line), align='L', new_x='LEFT', new_y='NEXT')

    x2 = L + bw + gap + 6
    pdf.set_xy(x2, y + 6)
    pdf.set_font('Helvetica', 'B', 9); pdf.set_text_color(*_GRAY)
    pdf.cell(bw - 12, 5, 'PAYMENT DETAILS', new_x='LEFT', new_y='NEXT')
    pdf.set_y(pdf.get_y() + 2.5)
    for k, v in (('Date paid', _date(r.get('paid_on'))), ('Payment mode', r.get('payment_mode') or '-'),
                 ('Reference', r.get('payment_ref') or '-')):
        pdf.set_x(x2)
        pdf.set_font('Helvetica', '', 10.5); pdf.set_text_color(90, 90, 90)
        pdf.cell(28, 7, _latin(k))
        pdf.set_font('Helvetica', 'B', 10.5); pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(bw - 40, 7, _latin(v), align='L', new_x='LMARGIN', new_y='NEXT')
    y += bh + 12 * g

    # Service table
    c1, c2 = W - 52, 52
    pdf.set_xy(L, y)
    pdf.set_fill_color(*_NAVY); pdf.set_text_color(255, 255, 255); pdf.set_font('Helvetica', 'B', 11)
    pdf.cell(c1, 11, '   Description', fill=True)
    pdf.cell(c2, 11, 'Amount (Rs.)   ', fill=True, align='R', new_x='LMARGIN', new_y='NEXT')
    y0 = pdf.get_y()
    pdf.set_xy(L + 4, y0 + 5); pdf.set_font('Helvetica', 'B', 12.5); pdf.set_text_color(30, 30, 30)
    pdf.multi_cell(c1 - 8, 7, _latin((r.get('service') or 'Payment received')[:SERVICE_MAX]), align='L', new_x='LMARGIN', new_y='NEXT')
    if (r.get('description') or '').strip():
        pdf.set_xy(L + 4, pdf.get_y() + 1); pdf.set_font('Helvetica', '', 10.5); pdf.set_text_color(80, 80, 80)
        pdf.multi_cell(c1 - 8, 6, _latin(r['description'].strip()[:DESC_MAX]), align='L', new_x='LMARGIN', new_y='NEXT')
    y1 = max(pdf.get_y() + 5, y0 + (16 if _compact else 30))
    pdf.set_xy(L + c1, y0 + 5); pdf.set_font('Helvetica', 'B', 12.5); pdf.set_text_color(30, 30, 30)
    pdf.cell(c2, 7, inr(r.get('amount')) + '   ', align='R')
    pdf.set_draw_color(220, 224, 232); pdf.set_line_width(0.35)
    pdf.rect(L, y0, W, y1 - y0)
    pdf.line(L + c1, y0, L + c1, y1)
    y = y1 + 10 * g

    # Amount banner (words in bold)
    pdf.set_fill_color(253, 240, 230); pdf.set_draw_color(*_ORANGE); pdf.set_line_width(0.5)
    pdf.set_font('Helvetica', 'B', 11.5)
    wlines = pdf.multi_cell(W - 16, 6.5, align='L', text=_latin('Amount in words: ' + words(r.get('amount'))), dry_run=True, output='LINES')
    bh2 = 26 + 6.5 * len(wlines)
    if y + bh2 > pdf.h - 30:          # never split the amount box across pages
        pdf.add_page(); y = 20
    pdf.rect(L, y, W, bh2, 'DF')
    pdf.set_xy(L + 8, y + 7)
    pdf.set_font('Helvetica', 'B', 13); pdf.set_text_color(*_NAVY)
    pdf.cell(W / 2, 10, 'Total amount received')
    pdf.set_font('Helvetica', 'B', 22); pdf.set_text_color(*_ORANGE)
    pdf.cell(W / 2 - 16, 10, 'Rs. ' + inr(r.get('amount')), align='R', new_x='LMARGIN', new_y='NEXT')
    pdf.set_draw_color(240, 200, 170); pdf.set_line_width(0.3)
    pdf.line(L + 8, y + 21, L + W - 8, y + 21)
    pdf.set_xy(L + 8, y + 23)
    pdf.set_font('Helvetica', 'B', 11.5); pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(W - 16, 6.5, _latin('Amount in words: ' + words(r.get('amount'))), align='L', new_x='LMARGIN', new_y='NEXT')
    y += bh2 + 12 * g

    # Thank-you note, then the sign-off sitting low on the page
    pdf.set_xy(L, y)
    pdf.set_font('Helvetica', '', 11); pdf.set_text_color(50, 50, 50)
    if _compact:
        if y + 26 < pdf.h - 27:       # room for the one-line thanks + sign-off
            pdf.cell(W, 6.5, 'Thank you for your payment.', new_x='LMARGIN', new_y='NEXT')
            pdf.set_y(pdf.get_y() + 3)
    else:
        pdf.multi_cell(W, 6.5, align='L', text='Thank you for your payment. Please keep this receipt for your records. '
                               'For any questions about this payment, write to us at info@goocampus.in.',
                       new_x='LMARGIN', new_y='NEXT')
        pdf.set_y(max(pdf.get_y() + 12, 238))
    pdf.set_font('Helvetica', '', 11); pdf.set_text_color(50, 50, 50)
    pdf.cell(W, 6.5, 'Warm regards,', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(1)
    pdf.set_font('Helvetica', 'B', 14); pdf.set_text_color(*_NAVY)
    pdf.cell(W, 8, 'GooCampus Team', new_x='LMARGIN', new_y='NEXT')
    pdf.set_draw_color(*_ORANGE); pdf.set_line_width(0.8)
    pdf.line(L, pdf.get_y() + 1, L + 42, pdf.get_y() + 1)

    # Footer (page-break off so the last line can sit inside the bottom margin)
    pdf.set_auto_page_break(False)
    pdf.set_y(-24)
    pdf.set_draw_color(*_ORANGE); pdf.set_line_width(0.4)
    pdf.line(L, pdf.get_y(), L + W, pdf.get_y())
    pdf.ln(3)
    pdf.set_font('Helvetica', 'I', 9); pdf.set_text_color(*_GRAY)
    pdf.cell(W, 5, 'This is a computer-generated receipt and does not require a signature.', align='C',
             new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Helvetica', '', 9)
    pdf.cell(W, 5, 'GooCampus Edu Solutions Pvt Ltd  |  www.goocampus.in  |  info@goocampus.in', align='C')
    if pdf.page > 1 and not _compact:
        return build_pdf(r, pathway_label, _compact=True)
    return bytes(pdf.output())


def pdf_filename(receipt_no):
    return 'GooCampus-Receipt-' + receipt_no.replace('/', '-') + '.pdf'
