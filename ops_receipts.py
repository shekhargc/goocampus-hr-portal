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
_NAVY = (15, 27, 51)
_ORANGE = (234, 108, 30)
_GRAY = (100, 110, 125)

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


def build_pdf(r, pathway_label=''):
    """r: an ops_receipts row (dict). Returns the PDF as bytes."""
    from core.helpers import format_dr_name
    pdf = FPDF(format='A4')
    pdf.set_auto_page_break(True, margin=18)
    pdf.set_margins(16, 14, 16)
    pdf.add_page()
    W = pdf.w - 32

    # Header: logo left, title + number right
    try:
        pdf.image(_LOGO, x=16, y=12, h=20)
    except Exception as e:
        logging.warning("receipt logo: %s", e)
    pdf.set_xy(16, 13)
    pdf.set_font('Helvetica', 'B', 18); pdf.set_text_color(*_NAVY)
    pdf.cell(W, 9, 'PAYMENT RECEIPT', align='R', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Helvetica', '', 9.5); pdf.set_text_color(*_GRAY)
    pdf.cell(W, 5.5, _latin(f"Receipt No: {r['receipt_no']}"), align='R', new_x='LMARGIN', new_y='NEXT')
    issued = r.get('created_at')
    issued = (issued + timedelta(hours=5, minutes=30)) if isinstance(issued, datetime) else issued
    pdf.cell(W, 5.5, _latin(f"Date issued: {_date(issued)}"), align='R', new_x='LMARGIN', new_y='NEXT')
    pdf.set_y(38)
    pdf.set_draw_color(*_ORANGE); pdf.set_line_width(0.8)
    pdf.line(16, pdf.get_y(), 16 + W, pdf.get_y())
    pdf.ln(7)

    if (r.get('status') or 'active') == 'cancelled':
        pdf.set_font('Helvetica', 'B', 11); pdf.set_text_color(185, 28, 28)
        pdf.cell(W, 7, 'CANCELLED - this receipt is no longer valid', align='C', new_x='LMARGIN', new_y='NEXT')
        pdf.ln(2)

    # Received from
    pdf.set_font('Helvetica', 'B', 8.5); pdf.set_text_color(*_GRAY)
    pdf.cell(W, 5, 'RECEIVED FROM', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Helvetica', 'B', 13); pdf.set_text_color(*_NAVY)
    pdf.cell(W, 7, _latin(format_dr_name(r.get('client_name') or '')), new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Helvetica', '', 9.5); pdf.set_text_color(60, 60, 60)
    bits = [x for x in (r.get('registration_number') and f"Reg. No: {r['registration_number']}",
                        pathway_label, r.get('client_email')) if x]
    if bits:
        pdf.cell(W, 5.5, _latin('   |   '.join(bits)), new_x='LMARGIN', new_y='NEXT')
    pdf.ln(6)

    # Service / amount table
    c1, c2 = W - 48, 48
    pdf.set_fill_color(*_NAVY); pdf.set_text_color(255, 255, 255); pdf.set_font('Helvetica', 'B', 9.5)
    pdf.cell(c1, 8, '  Description', fill=True)
    pdf.cell(c2, 8, 'Amount (Rs.)  ', fill=True, align='R', new_x='LMARGIN', new_y='NEXT')
    pdf.set_text_color(30, 30, 30)
    y0 = pdf.get_y()
    pdf.set_x(16); pdf.set_font('Helvetica', 'B', 10.5)
    pdf.multi_cell(c1, 6, _latin('  ' + (r.get('service') or 'Payment received')), new_x='LMARGIN', new_y='NEXT')
    if (r.get('description') or '').strip():
        pdf.set_font('Helvetica', '', 9.5); pdf.set_text_color(70, 70, 70)
        pdf.set_x(18)
        pdf.multi_cell(c1 - 4, 5.2, _latin(r['description'].strip()), new_x='LMARGIN', new_y='NEXT')
    y1 = max(pdf.get_y() + 2, y0 + 10)
    pdf.set_xy(16 + c1, y0 + 0.5); pdf.set_font('Helvetica', 'B', 10.5); pdf.set_text_color(30, 30, 30)
    pdf.cell(c2, 6, inr(r.get('amount')) + '  ', align='R')
    pdf.set_draw_color(220, 224, 230); pdf.set_line_width(0.3)
    pdf.line(16, y1, 16 + W, y1)
    pdf.set_y(y1 + 1)
    pdf.set_fill_color(253, 240, 230); pdf.set_font('Helvetica', 'B', 11); pdf.set_text_color(*_NAVY)
    pdf.cell(c1, 9, '  Total amount received', fill=True)
    pdf.cell(c2, 9, 'Rs. ' + inr(r.get('amount')) + '  ', fill=True, align='R', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(2)
    pdf.set_font('Helvetica', 'I', 9.5); pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(W, 5.5, _latin('Amount in words: ' + words(r.get('amount'))), new_x='LMARGIN', new_y='NEXT')
    pdf.ln(5)

    # Payment details
    pdf.set_font('Helvetica', 'B', 8.5); pdf.set_text_color(*_GRAY)
    pdf.cell(W, 5, 'PAYMENT DETAILS', new_x='LMARGIN', new_y='NEXT')
    for k, v in (('Date paid', _date(r.get('paid_on'))), ('Payment mode', r.get('payment_mode') or '-'),
                 ('Transaction reference', r.get('payment_ref') or '-')):
        pdf.set_font('Helvetica', '', 9.5); pdf.set_text_color(90, 90, 90)
        pdf.cell(48, 6.5, _latin(k))
        pdf.set_font('Helvetica', 'B', 9.5); pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(W - 48, 6.5, _latin(v), new_x='LMARGIN', new_y='NEXT')
    pdf.ln(8)

    # Sign-off
    pdf.set_font('Helvetica', '', 10); pdf.set_text_color(40, 40, 40)
    pdf.cell(W, 6, 'Thank you for your payment.', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(4)
    pdf.cell(W, 5.5, 'Warm regards,', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Helvetica', 'B', 11); pdf.set_text_color(*_NAVY)
    pdf.cell(W, 6.5, 'GooCampus Team', new_x='LMARGIN', new_y='NEXT')

    # Footer (page-break off so the last line can sit inside the bottom margin)
    pdf.set_auto_page_break(False)
    pdf.set_y(-30)
    pdf.set_draw_color(*_ORANGE); pdf.set_line_width(0.4)
    pdf.line(16, pdf.get_y(), 16 + W, pdf.get_y())
    pdf.ln(3)
    pdf.set_font('Helvetica', 'I', 8.5); pdf.set_text_color(*_GRAY)
    pdf.cell(W, 5, 'This is a computer-generated receipt and does not require a signature.', align='C',
             new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Helvetica', '', 8.5)
    pdf.cell(W, 5, 'GooCampus Edu Solutions Pvt Ltd  |  www.goocampus.in  |  info@goocampus.in', align='C')
    return bytes(pdf.output())


def pdf_filename(receipt_no):
    return 'GooCampus-Receipt-' + receipt_no.replace('/', '-') + '.pdf'
