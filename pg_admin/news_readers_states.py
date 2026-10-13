"""Readers for state counselling-authority sites (batch 3, founder 2026-10-13: "all other states").
Each site lays notices out differently; every reader returns the same item dicts as news_scraper
({item_key, raw_title, title, url, kind, notice_date}). Sources were found and verified on each
authority's OFFICIAL site (see SOURCES notes in news_scraper). Wired in via DISPATCH below.
"""
import re
import logging
import html as _html
from datetime import date, datetime

from pg_admin import news_scraper as NS
from pg_admin.news_scraper import (_session, _text, split_title_date, _kind, _wanted, _URL_DATE_RE,
                                   TIMEOUT, UA, SEASON_FROM, read_pdf_links)

# ===== acpmec =====
def read_pdf_links_url(url, pages=None, url_include=None, include=None, exclude=None):
    """Like read_pdf_links, but (a) also accepts PDF links with a query string ('x.pdf?v=2') and
    (b) can keep only links whose URL matches `url_include` (e.g. r'/PG2026/' — the year folder),
    for pages that mix this year's notices with years of archive links (Gujarat ACPPGMEC)."""
    from urllib.parse import urljoin
    s, items, seen = NS._session(), [], set()
    for pg in (pages or [url]):
        r = s.get(pg, timeout=NS.TIMEOUT)
        r.raise_for_status()
        for href, inner in re.findall(r'<a\b[^>]*href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\'][^>]*>(.*?)</a>',
                                      r.text, re.S | re.I):
            href = urljoin(r.url, _html.unescape(href).strip())
            raw = NS._text(inner)
            if href in seen or not raw or raw.lower() in ('view', 'download', 'click here'):
                continue
            seen.add(href)
            if url_include and not re.search(url_include, href, re.I):
                continue
            if not NS._wanted(raw, include, exclude):
                continue
            title, d = NS.split_title_date(raw)
            if not d:
                m = NS._URL_DATE_RE.search(href.rsplit('/', 1)[-1])
                if m:
                    try: d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    except ValueError: d = None
            items.append({'item_key': href, 'raw_title': raw, 'title': title, 'url': href,
                          'kind': 'pdf', 'notice_date': d})
    if not items:
        raise ValueError('No notices found on the page — the site layout may have changed.')
    return items


# ===== amru_hp =====
def read_amru_hp(url='https://amruhp.ac.in/counselling-notifications/', tab='mdms_neetpg',
                 include=r'MD\s*/\s*MS|MD-MS|\bDNB\b|NEET[\s-]*PG|PG\s+COURSE|POST\s*-?\s*GRADUATE',
                 exclude=r'AYURVED|\bMDS\b|DENTAL|NURSING|BAMS|BHMS'):
    """AMRU Himachal (WordPress): 'Apply for Admission & Various Counselling' page has one
    sub-tab per course — <div id="mdms_neetpg" class="sub-content"> = MD/MS Counselling — each a
    table of rows <td data-order="YYYY-MM-DD hh:mm:ss">year</td><td>TITLE</td><td><a href=…>View</a>.
    The data-order timestamp is the posting date. Also reads the 'prospectus' tab for the
    PG MD/MS/DNB prospectus (filtered by include/exclude)."""
    from urllib.parse import urljoin
    r = _session().get(url, timeout=(10, 60))
    r.raise_for_status()
    t = r.text
    items, seen, found_tab = [], set(), False
    for tid, flt in ((tab, False), ('prospectus', True)):
        m = re.search(rf'<div id="{tid}" class="sub-content[^"]*">(.*?)(?=<div id="[\w-]+" class="sub-content|$)', t, re.S)
        if not m:
            continue
        found_tab = found_tab or tid == tab
        for stamp, inner, href in re.findall(
                r'<td data-order="([\d-]+)[^"]*">.*?</td>\s*<td>(.*?)</td>\s*<td>.*?href="([^"]+)"', m.group(1), re.S):
            raw = _text(inner)
            href = urljoin(r.url, _html.unescape(href).strip())
            if not raw or href in seen or (flt and not _wanted(raw, include, exclude)):
                continue
            seen.add(href)
            title, d = split_title_date(raw)
            try:
                d = d or date(*map(int, stamp.split('-')[:3]))
            except ValueError:
                pass
            items.append({'item_key': href, 'raw_title': raw, 'title': title, 'url': href,
                          'kind': _kind(href), 'notice_date': d})
    if not found_tab:
        raise ValueError('AMRU MD/MS Counselling tab not found — the page layout may have changed.')
    return items


# ===== centac =====
def read_centac_home(url, include=None, exclude=None):
    """Puducherry CENTAC (centacpuducherry.in) home page — every notice is
    <a href='https://drive.google.com/file/d/<ID>/view…'> [dd-mm-yyyy] - TITLE</a>, repeated in the OVERALL tab and the
    course tab (PG-MEDICAL appears once the PG season opens; PG-DENTAL, UG-NEET… meanwhile). Keep titles matching
    include/exclude. Drive files are re-pointed to the direct-download link (uc?export=download) so fetch_pdf gets
    the PDF; CENTAC's own .html/.pdf links are kept as they are."""
    from urllib.parse import urljoin
    r = _session().get(url, timeout=(10, 60))
    r.raise_for_status()
    items, seen, rows = [], set(), 0
    for href, inner in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r.text, re.S | re.I):
        raw = _text(inner)
        m = re.match(r'\[\s*(\d{1,2}-\d{1,2}-20\d{2})\s*\]\s*-\s*(.+)', raw)
        if not m:
            continue
        rows += 1
        href = urljoin(r.url, _html.unescape(href).strip())
        g = re.search(r'drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:[^"\']*&)?id=)([\w-]{20,})', href)
        key = 'gdrive:' + g.group(1) if g else href
        title = m.group(2).strip()
        if key in seen or not _wanted(title, include, exclude):
            continue
        seen.add(key)
        _x, d = split_title_date(m.group(1))
        if g:
            link, kind = f'https://drive.google.com/uc?export=download&id={g.group(1)}', 'pdf'
        else:
            link, kind = href, _kind(href)
        items.append({'item_key': key, 'raw_title': raw, 'title': title, 'url': link, 'kind': kind, 'notice_date': d})
    if not rows:
        raise ValueError('No dated notices found — the site layout may have changed.')
    return items          # empty is fine until the PG-MEDICAL tab opens



# ===== cetcell_mh =====
def _get_text_tls13(url):
    """GET → (status, final_url, text). Maharashtra CET Cell hosts (*.mahacet.org) accept TLS 1.3
    only; the Mac's Python 3.9 (LibreSSL 2.8.3) can't do TLS 1.3, so fall back to the system curl."""
    import subprocess, requests
    try:
        r = NS._session().get(url, timeout=NS.TIMEOUT)
        return r.status_code, r.url, r.text
    except requests.exceptions.SSLError:
        out = subprocess.run(['curl', '-sL', '-A', NS.UA, '-m', '60', '-w', '\n%{http_code} %{url_effective}', url],
                             capture_output=True, timeout=90)
        body, _, tail = out.stdout.decode('utf-8', 'ignore').rpartition('\n')
        code, _, final = tail.partition(' ')
        return int(code or 0), final or url, body

def read_mh_cetcell(pages, include=None, exclude=None):
    """Maharashtra State CET Cell course portal (medical<year>.mahacet.org/<COURSE>/login): the
    'News' + 'Notification' boxes are <a href="…/instructions-downloadFile/<file>.pdf">TITLE</a>
    (some on statecetcell S3). A page that 404s (portal for the year not opened yet) is skipped."""
    from urllib.parse import urljoin
    items, seen, ok = [], set(), False
    for pg in pages:
        code, final, text = _get_text_tls13(pg)
        if code == 404:
            continue
        if code >= 400 or not text:
            raise ValueError(f'HTTP {code} from {pg}')
        ok = True
        for href, inner in re.findall(r'<a\b[^>]*href=["\']([^"\']+\.pdf)["\'][^>]*>(.*?)</a>', text, re.S | re.I):
            href = urljoin(final, _html.unescape(href).strip()).replace(' ', '%20')
            raw = re.sub(r'\s*New\s*$', '', NS._text(inner)).strip()
            if href in seen or not raw or not NS._wanted(raw, include, exclude):
                continue
            seen.add(href)
            title, d = NS.split_title_date(raw)
            items.append({'item_key': href, 'raw_title': raw, 'title': title, 'url': href,
                          'kind': 'pdf', 'notice_date': d})
    if not ok:
        return []        # the year's NEET-PGM portal isn't up yet — nothing to report
    return items


# ===== dmer_hr =====
_HR_INC = r'MD\s*[/.]?\s*MS|POST\s*MBBS|\bDNB\b|PG\s+COURSES?|NEET[\s-]*PG|POST\s*-?\s*GRADUATE|\bPG\b'
_HR_EXC = r'^(?!.*MD\s*[/.]?\s*MS).*\bMDS\b|NURSING|\bANM\b|\bGNM\b|PARAMEDICAL|PHYSIOTHERAP|RECRUIT|ADVERTISEMENT|SENIOR\s+RESIDENT'


def read_dmer_hr(url='https://dmer.haryana.gov.in/', include=_HR_INC, exclude=_HR_EXC):
    """DMER Haryana home page 'Latest News' / 'Notice Board': every notice since 2021 stays on the
    page, mostly WITHOUT a date or session in the title. So: keep the PG-medical PDFs, and for an
    undated title read the PDF's Last-Modified header (1-byte range GET; HEAD answers 404 there)
    as the notice date, so in_season() can drop old years. A link that no longer serves a PDF
    (dead hry.online-counselling.co.in/admissions/resources links fall back to the SPA's HTML) is skipped."""
    from urllib.parse import urljoin
    from email.utils import parsedate_to_datetime
    s = _session()
    r = s.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    items, seen = [], set()
    for href, inner in re.findall(r'<a\b[^>]*href=["\']([^"\']+\.pdf)["\'][^>]*>(.*?)</a>', r.text, re.S | re.I):
        href = urljoin(r.url, _html.unescape(href).strip())
        raw = re.sub(r'\s*Download\s*\([\d.]+\s*[KM]B\)\s*$', '', _text(inner), flags=re.I)
        if href in seen or not raw or not _wanted(raw, include, exclude):
            continue
        seen.add(href)
        title, d = split_title_date(raw)
        yrs = [int(y) for y in re.findall(r'(20\d\d)\s*[-–]\s*\d\d\b', title)]
        if yrs and max(yrs) < SEASON_FROM.year:
            continue                                           # an old session (e.g. 2024-25) named in the title
        if not d:
            try:
                h = s.get(href, headers={'Range': 'bytes=0-0'}, timeout=TIMEOUT, stream=True)
                ctype, lm = h.headers.get('Content-Type', ''), h.headers.get('Last-Modified')
                h.close()
                if h.status_code >= 400 or 'pdf' not in ctype.lower():
                    continue                                   # dead link
                if lm:
                    d = parsedate_to_datetime(lm).date()
            except Exception:
                pass
        items.append({'item_key': href, 'raw_title': raw, 'title': title, 'url': href, 'kind': 'pdf', 'notice_date': d})
    if not re.search(r'Latest News|Notice Board', r.text):
        raise ValueError('DMER Haryana home page layout changed (no Latest News / Notice Board).')
    return items


# ===== dmetup =====
def read_row_table(pages, include=None, exclude=None, strip=None, max_rows=None):
    """Generic notices table: each <tr> has a TITLE cell (date inside it, e.g. '(Uploaded on dated
    dd-mm-yyyy)') and a separate link cell whose anchor text is only 'Download'/'View' — so
    read_pdf_links can't use it. Title = the longest cell text (minus the `strip` regex, e.g. a
    'Size: … Format: PDF' tail); url = the row's first PDF link (else first real link); item_key = url.
    max_rows: read only the first N link-rows of each page (newest-first archives going back years).
    (UP DGME counselling page, 2026-10-13.)"""
    from urllib.parse import urljoin
    s, items, seen, total = NS._session(), [], set(), 0
    for pg in pages:
        r = s.get(pg, timeout=(10, 60))
        r.raise_for_status()
        rows = 0
        for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', r.text, re.S | re.I):
            hrefs = [h for h in re.findall(r'<a\b[^>]*href\s*=\s*["\']([^"\']+)["\']', row, re.I)
                     if not h.lower().startswith(('javascript', '#', 'mailto'))]
            if not hrefs:
                continue
            rows += 1
            total += 1
            if max_rows and rows > max_rows:
                break
            pdfs = [h for h in hrefs if re.search(r'\.pdf($|[?#])', h, re.I)]
            href = urljoin(r.url, _html.unescape((pdfs or hrefs)[0]).strip()).replace(' ', '%20')
            cells = [NS._text(c) for c in re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S | re.I)]
            if strip:
                cells = [re.sub(strip, ' ', c, flags=re.I).strip() for c in cells]
            raw = max(cells, key=len) if cells else ''
            if not raw or href in seen or not NS._wanted(raw, include, exclude):
                continue
            seen.add(href)
            title, d = NS.split_title_date(raw)
            title = re.sub(r'\(\s*uploaded on( dated)?\s*\)?\s*$|\(\s*$', '', title, flags=re.I).strip()
            items.append({'item_key': href, 'raw_title': raw, 'title': title, 'url': href,
                          'kind': NS._kind(href), 'notice_date': d})
    if not total:
        raise ValueError('No notices table found — the site layout may have changed.')
    return items          # empty after filtering is fine (no PG notice yet this season)


# ===== dte_goa =====
def read_drupal_news(url, include=None, exclude=None):
    """Goa DTE (dte.goa.gov.in, Drupal) — the 'Latest Updates' view (view-latest-news) lists each notice as
    <h3><a href="/pg-medical-rules-2026">TITLE</a></h3>; each title is its own node page holding the PDF
    ('…/sites/default/files/2026-10/X.pdf … Click to download') and the posting date ('October 09, 2026').
    Keep titles matching include/exclude, then open each node for its PDF + date (link item if no PDF)."""
    from urllib.parse import urljoin
    s = _session()
    r = s.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    blk = re.search(r'view-latest-news(.*?)(?:<footer|id="block-rvs-footermenu"|$)', r.text, re.S)
    found = re.findall(r'<h3>\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>', blk.group(1) if blk else r.text, re.S | re.I)
    if not found:
        raise ValueError('No Latest Updates list found — the site layout may have changed.')
    items, seen = [], set()
    for href, inner in found:
        raw = _text(inner)
        node = urljoin(r.url, _html.unescape(href).strip())
        if not raw or node in seen or not _wanted(raw, include, exclude):
            continue
        seen.add(node)
        title, d = split_title_date(raw)
        pdfs = []
        try:
            n = s.get(node, timeout=TIMEOUT)
            n.raise_for_status()
            main = re.search(r'<main\b(.*?)</main>', n.text, re.S)
            body = main.group(1) if main else n.text
            for p in re.findall(r'href="([^"]+\.pdf)"', body, re.I):
                p = urljoin(n.url, _html.unescape(p).strip())
                if p not in pdfs:
                    pdfs.append(p)
            m = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)'
                          r'\s+(\d{1,2}),\s*(20\d{2})', _text(body))
            if m:
                d = datetime.strptime(f'{m.group(1)} {m.group(2)} {m.group(3)}', '%B %d %Y').date()
        except Exception as e:
            logging.warning("goa dte node %s: %s", node, e)
        if not pdfs:
            items.append({'item_key': node, 'raw_title': raw, 'title': title, 'url': node,
                          'kind': 'link', 'notice_date': d})
        for i, p in enumerate(pdfs):
            t = title if len(pdfs) == 1 else f'{title} ({i + 1})'
            items.append({'item_key': p, 'raw_title': raw, 'title': t, 'url': p, 'kind': 'pdf', 'notice_date': d})
    return items          # empty is fine: no PG Medical item in Latest Updates right now



# ===== ggsipu =====
def read_pdf_links_soft(url, pages=None, include=None, exclude=None):
    """read_pdf_links, but a page whose course filter matches nothing YET is not an error
    (e.g. GGSIPU before its first PGMC notice of the season). Use reader 'pdf_links_soft'."""
    try:
        return read_pdf_links(url, pages, include, exclude)
    except ValueError as e:
        if 'No notices found' in str(e):
            return []
        raise


# ===== gmch_chd =====
def read_gmch_chd(url='https://gmch.gov.in/admissions', year=None):
    """GMCH-32 Chandigarh: the Admissions page links one page per session, e.g. 'Admission MD/MS-2025'
    (/node/6481 = /admission-mdms-2025). Find this season's 'Admission MD/MS-<year>' link (or the
    /admission-mdms-<year> alias), then read every PDF in that page's body table. Before the
    season's page exists → [] (nothing new yet)."""
    from urllib.parse import urljoin
    year = year or SEASON_FROM.year
    s = _session()
    r = s.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    target = None
    for href, inner in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r.text, re.S | re.I):
        if re.search(rf'MD\s*/?\s*MS\W*{year}\b', _text(inner), re.I):
            target = urljoin(r.url, _html.unescape(href).strip())
            break
    if not target:
        target = f'https://gmch.gov.in/admission-mdms-{year}'
    r2 = s.get(target, timeout=TIMEOUT)
    if r2.status_code == 404:
        return []
    r2.raise_for_status()
    m = re.search(r'<main\b(.*?)</main>', r2.text, re.S | re.I)
    body = m.group(1) if m else r2.text
    items, seen = [{'item_key': 'page|' + r2.url, 'raw_title': f'GMCH Chandigarh — Admission MD/MS-{year} page opened',
                    'title': f'GMCH Chandigarh — Admission MD/MS-{year} page opened', 'url': r2.url,
                    'kind': 'link', 'notice_date': None}], set()
    for href, inner in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', body, re.S | re.I):
        href = urljoin(r2.url, _html.unescape(href).strip())
        raw = _text(inner)
        if href in seen or not raw or _kind(href) != 'pdf':
            continue
        if re.search(r'super\s*speciality|\bDM\b|\bM\.?\s?Ch\b', raw, re.I):
            continue
        seen.add(href)
        title, d = split_title_date(raw)
        if title.lower() in ('notice', '.'):
            title = f'GMCH Chandigarh MD/MS {year} — Notice'
        items.append({'item_key': href, 'raw_title': raw, 'title': title, 'url': href, 'kind': 'pdf', 'notice_date': d})
    return items


# ===== hnbumu =====
def read_hnbumu_pg(url='https://meta-secure.com/HNBUMU_NEETPG'):
    """Uttarakhand HNBUMU state PG counselling portal (vendor meta-secure.com, linked from hnbumu.ac.in).
    The SAME portal runs NEET MDS and NEET PG (MD/MS) in turn, and most link titles are generic
    ('Schedule Round-1', 'State Quota', 'Provisional Merit List'). So: read which counselling the
    portal is in (the label before 'Note:' / the Information Bulletin file name). In MDS mode keep
    only links that name MD/MS / NEET-PG explicitly; in PG mode keep everything not marked MDS
    (title or file name). Undated; the notice date comes from a dd/mm/yyyy in the title if any."""
    from urllib.parse import urljoin
    r = _session().get(url, timeout=TIMEOUT)
    r.raise_for_status()
    t = r.text
    plain = _text(re.sub(r'<script.*?</script>|<style.*?</style>', ' ', t, flags=re.S))
    m = re.search(r'Contact Us\s+(.{0,60}?)\s+Note\s*:', plain)
    label = m.group(1) if m else ''
    bull = re.search(r'href=["\']\s*([^"\']*InformationBulletin[^"\']*)["\']', t, re.I)
    mds_mode = bool(re.search(r'MDS', label + ' ' + (bull.group(1) if bull else ''), re.I))
    pg_word = r'MD\s*/\s*MS|NEET[\s-]*PG(?![\s-]*MDS)|\bDNB\b|PG\s+MEDICAL|POST\s*-?\s*GRADUATE\s+MEDICAL'
    items, seen = [], set()
    for href, inner in re.findall(r'<a\b[^>]*href=["\']\s*([^"\']+\.pdf)\s*["\'][^>]*>(.*?)</a>', t, re.S | re.I):
        href = urljoin(r.url, _html.unescape(href).strip())
        raw = _text(re.sub(r'<span[^>]*>\s*new\s*</span>', ' ', inner, flags=re.I))
        raw = re.sub(r'\s+new$', '', raw, flags=re.I).strip()
        fname = href.rsplit('/', 1)[-1]
        if not raw or href in seen:
            continue
        is_mds = bool(re.search(r'MDS', raw + ' ' + fname, re.I))
        if mds_mode and not re.search(pg_word, raw, re.I):
            continue
        if not mds_mode and is_mds:
            continue
        seen.add(href)
        title, d = split_title_date(raw.replace('/', '-') if re.search(r'\d{2}/\d{2}/20\d{2}', raw) else raw)
        if not re.search(r'NEET|MD\s*/\s*MS|HNBUMU|Uttarakhand', title, re.I):
            title = 'Uttarakhand NEET-PG (MD/MS) counselling — ' + title
        items.append({'item_key': href, 'raw_title': raw, 'title': title, 'url': href, 'kind': 'pdf', 'notice_date': d})
    if 'Applicant Login' not in plain and 'Announcements' not in plain:
        raise ValueError('HNBUMU counselling portal layout changed.')
    return items


# ===== jceceb =====
def read_jceceb_grid(pages, include=None, exclude=None):
    """Jharkhand JCECEB (jceceb.jharkhand.gov.in/Links/*.aspx) — an ASP.NET GridView 'GvImportantnotices',
    newest first: <tr><td>No.</td><td><span id='..._Label1_N'>TITLE (often 'Advt. No. X dated-dd.mm.yyyy …')</span></td>
    <td><a id='..._HyperLink1_N' href='../con_notice/NNN.pdf'>View</a></td></tr>. The link text is always 'View', so
    the title comes from the Label1 cell. An undated row (e.g. 'Provisional Vacant Seat matrix …') takes the date of
    the nearest dated row ABOVE it (rows are newest-first), so an old undated row isn't mistaken for this season."""
    from urllib.parse import urljoin
    s, items, seen, rows = _session(), [], set(), 0
    for pg in pages:
        r = s.get(pg, timeout=(10, 60))
        r.raise_for_status()
        above = None
        for tr in re.split(r'<tr\b', r.text):
            lab = re.search(r'_Label1_\d+"[^>]*>(.*?)</td>', tr, re.S)
            lnk = re.search(r'<a\b[^>]*id="[^"]*HyperLink1_\d+"[^>]*href="([^"]+)"', tr, re.S) or \
                  re.search(r'<a\b[^>]*href="([^"]+)"[^>]*id="[^"]*HyperLink1_\d+"', tr, re.S)
            if not lab or not lnk:
                continue
            rows += 1
            raw = _text(lab.group(1))
            href = urljoin(r.url, _html.unescape(lnk.group(1)).strip())
            title, d = split_title_date(raw)
            title = re.sub(r'\s*\b[Dd]ated?\s*[:\-–]*\s*(?=[\s(){}]|$)', ' ', title)
            title = re.sub(r'\s+', ' ', title).strip(' {}')
            if d:
                above = d
            if href in seen or not raw or not _wanted(raw, include, exclude):
                continue
            seen.add(href)
            items.append({'item_key': href, 'raw_title': raw, 'title': title, 'url': href,
                          'kind': _kind(href), 'notice_date': d or above})
    if not rows:
        raise ValueError('No notices table found — the site layout may have changed.')
    return items          # an empty list is fine before the PG season starts



# ===== jk_bopee =====
def read_jk_bopee(url='https://jkbopee.gov.in/NoticeBoard.aspx',
                  include=r'NEET[\s-]*PG|MD\s*/\s*MS|\bDNB\b|POST\s*MBBS|PG\s*MEDICAL|POST\s*-?\s*GRADUATE\s+MEDICAL',
                  exclude=r'\bMDS\b|DENTAL|REHABILITATION|NURSING|AYUSH|PHARM|PARAMEDICAL|SUPER\s*SPECIAL'):
    """J&K BOPEE Notice Board — one long list (all courses, all years) of
    <li data-date='dd-mm-yyyy'><a class="title" href='Pdf/Downloader.ashx?nid=N&type=n'>TITLE</a></li>.
    The links serve PDFs through Downloader.ashx (no .pdf in the URL) → kind 'pdf'; item_key = nid."""
    from urllib.parse import urljoin
    r = _session().get(url, timeout=(10, 60))
    r.raise_for_status()
    items, seen, rows = [], set(), 0
    for dtxt, href, inner in re.findall(
            r"<li\s+data-date=['\"]([^'\"]*)['\"][^>]*>\s*<a\b[^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", r.text, re.S | re.I):
        rows += 1
        raw = _text(inner)
        href = urljoin(r.url, _html.unescape(href).strip())
        m = re.search(r'nid=(\d+)', href)
        key = 'nid' + m.group(1) if m else href
        if not raw or key in seen or not _wanted(raw, include, exclude):
            continue
        seen.add(key)
        title = re.sub(r'\s*\[[^\]]*\bD(?:t|ated)\.?\s*[\d.\-/]+\s*\]\s*$', '', raw).strip() or raw   # "[NEET-PG-PN-001 Dt. 05-03-2026]"
        _x, d = split_title_date(dtxt)
        if not d:
            _x, d = split_title_date(raw)
        items.append({'item_key': key, 'raw_title': raw, 'title': title, 'url': href,
                      'kind': 'pdf' if 'Downloader.ashx' in href else _kind(href), 'notice_date': d})
    if not rows:
        raise ValueError('No notices found on the J&K BOPEE notice board — the layout may have changed.')
    return items


# ===== ruhs =====
def read_raj_orderportal(dept_codes, include=None, exclude=None, page_size=300):
    """Rajasthan Govt 'Jankalyan' order portal (the JSON API behind medicaleducation.rajasthan.gov.in
    'Government Orders' pages). Lists the newest `page_size` orders/notifications of each department
    (102 = Medical Education Dept, 357 = SMS Medical College Jaipur — the state NEET UG/PG counselling
    boards sit there) and keeps titles matching include/exclude. url = first attached PDF (official
    jankalyanfile.rajasthan.gov.in), else the order's own website link (e.g. the counselling portal)."""
    api = 'https://medicalportal.rajasthan.gov.in/webapi/api/OrderPortal/GetList'
    s, items, seen = NS._session(), [], set()
    for dept in dept_codes:
        body = {"AttachmentList": [], "IsLatest": -1, "DeptSectionCode": "0",
                "IndexModel": {"AdvanceSearchModel": {}, "PageSize": page_size, "IsPostBack": False,
                               "OrderByAsc": 0, "Search": None, "OrderBy": "Date", "Page": 1},
                "Id": 0, "Type": "0", "Title": "", "IndividualBeneficiaryScheme": "", "OrderNo": "", "Date": "",
                "BeneficiaryCategory": 0, "AdmDepartmentCode": 0, "DepartmentCode": int(dept), "OfficeCode": 0,
                "SectorIds": 0, "Search": "", "FromDate": "", "ToDate": "", "SubTypeCode": 0, "EntryFromDate": "",
                "EntryToDate": "", "Status": 1, "IsNotJankalyan": -1, "LookupCode": 0, "SchemeCode": 0,
                "DistrictCode": 0, "DesignationCode": 0, "OfficeCatCode": "0", "IsImagesRequired": False}
        r = s.post(api, json=body, timeout=(10, 60),
                   headers={'Origin': 'https://medicaleducation.rajasthan.gov.in',
                            'Referer': 'https://medicaleducation.rajasthan.gov.in/'})
        r.raise_for_status()
        rows = ((r.json() or {}).get('Data') or {}).get('Data') or []
        if not rows:
            raise ValueError('Rajasthan order portal returned no rows — the API may have changed.')
        for x in rows:
            title = re.sub(r'\s+', ' ', x.get('Title') or '').strip()
            if not title or not NS._wanted(title, include, exclude):
                continue
            atts = [a.get('Path') for a in (x.get('AttachmentList') or []) if a.get('Path')]
            url = atts[0] if atts else (x.get('Url') or
                  f"https://medicaleducation.rajasthan.gov.in/smsjaipur/#/order/detail/{x.get('Id')}")
            key = f"rajorder:{x.get('Id')}"
            if key in seen:
                continue
            seen.add(key)
            d = None
            try:
                d = date.fromisoformat((x.get('Date') or '')[:10])
            except ValueError:
                pass
            if x.get('Url') and atts:
                title = f"{title} (portal: {x['Url']})"
            items.append({'item_key': key, 'raw_title': title, 'title': title, 'url': url,
                          'kind': NS._kind(url), 'notice_date': d})
    return items      # empty is normal until the PG board posts


# ── East & North-East batch ──
# ===== ojee =====
def read_dmet_odisha(pages, include=None, exclude=None):
    """Odisha DMET PG Medical counselling (dmetodisha.in/PGMCC_Static/...) — static HTML tables:
    each row = [date cell 'DD<br>Mon-YYYY'] [title cell] [<a href=PDF>View PDF</a>]. The bulletin page uses
    [course 'PG-Medical'] [title] [View PDF] with no date. Title = the row's text before the link, minus the
    date and the course label. The 'Doc/Council Affidavit Notification OSCOTP.pdf' href is the template's
    placeholder header link — ignored."""
    from urllib.parse import urljoin
    _MON = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}
    s, items, seen = _session(), [], set()
    for pg in pages:
        r = s.get(pg, timeout=TIMEOUT)
        r.raise_for_status()
        body = r.text
        prev = 0
        for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+\.pdf)["\'][^>]*>(.*?)</a>', body, re.S | re.I):
            href_raw, inner = m.group(1), m.group(2)
            chunk = body[prev:m.start()]
            prev = m.end()
            if 'OSCOTP' in href_raw:                     # template placeholder link
                continue
            # the row = from the last '<tr' that opens this row's outer table row
            rows = [x.start() for x in re.finditer(r'<tr\b', chunk, re.I)]
            row = chunk
            for st in reversed(rows):                    # walk back until the row holds some text
                if _text(re.sub(r'<a\b.*?</a>', ' ', chunk[st:], flags=re.S | re.I)):
                    row = chunk[st:]
                    break
            d = None                                     # the row's date cell sits before the title cell
            dms = list(re.finditer(r'class="date">\s*(\d{1,2})\s*(?:<br\s*/?>)?\s*([A-Za-z]{3})[a-z]*\s*[-\s]\s*(20\d{2})', chunk))
            if dms and dms[-1].group(2).lower() in _MON:
                dm = dms[-1]
                try: d = date(int(dm.group(3)), _MON[dm.group(2).lower()], int(dm.group(1)))
                except ValueError: d = None
            raw = _text(row)
            raw = re.sub(r'^(PG[\s-]*Medical)\s+', '', raw, flags=re.I).strip()
            link_txt = _text(inner)
            if not raw:
                raw = link_txt
            href = urljoin(r.url, _html.unescape(href_raw).strip()).replace(' ', '%20')
            if not raw or href in seen or not _wanted(raw, include, exclude):
                continue
            seen.add(href)
            title, d2 = split_title_date(raw)
            items.append({'item_key': href, 'raw_title': raw, 'title': title, 'url': href,
                          'kind': 'pdf', 'notice_date': d or d2})
    if not items:
        raise ValueError('No notices found — the site layout may have changed.')
    return items



# ===== dme_assam =====
def read_pdf_links_lastmod(url, pages=None, include=None, exclude=None, max_head=80):
    """pdf_links for sites whose notice list carries NO dates and mixes every course and several years
    (Assam DME 'Admission Notice-UG/PG/Others(New)', Meghalaya meghealth.gov.in home 'News' box).
    1) read every PDF link on the page(s) unfiltered — raises only if the page has no PDF links at all
       (= layout changed); 2) apply include/exclude on the title — an EMPTY result is fine (no PG notice
       yet this season) instead of an error; 3) for each undated match (up to max_head) a HEAD request
       reads the server's Last-Modified header as the notice date, so in_season() drops the previous
       session's notices (e.g. Assam 'Stray round online PG counselling_2026' = 2025 session, uploaded
       Feb 2026). A failed HEAD leaves the date None (kept as current season)."""
    from email.utils import parsedate_to_datetime
    items = [i for i in read_pdf_links(url, pages) if _wanted(i['raw_title'], include, exclude)]
    s = _session()
    for it in items[:max_head]:
        if it['notice_date']:
            continue
        try:
            h = s.head(it['url'], timeout=TIMEOUT, allow_redirects=True)
            lm = h.headers.get('Last-Modified')
            if h.ok and lm:
                it['notice_date'] = parsedate_to_datetime(lm).date()
        except Exception as e:
            logging.warning("last-modified %s: %s", it['url'], e)
    return items



# ===== dhs_manipur =====
def read_badge_list(url, include=None, exclude=None):
    """Manipur DHS (manipurhealthdirectorate.mn.gov.in/notifications) — one long list, newest first:
    <li class="list-group-item"><a class="text-primary" href="PDF or /news/<id>">TITLE</a>
    <span class="badge">October 9, 2026</span></li>. Mixes every course + HR orders, so filter by title.
    A /news/<id> link is an HTML notice page (kind 'link')."""
    from urllib.parse import urljoin
    r = _session().get(url, timeout=TIMEOUT)
    r.raise_for_status()
    items, seen, rows = [], set(), 0
    for href, inner, dtxt in re.findall(
            r'<a\s+class="text-primary"\s+href="([^"]+)"[^>]*>(.*?)</a>\s*<span class="badge"\s*>(.*?)</span>', r.text, re.S):
        rows += 1
        raw = _text(inner)
        href = urljoin(r.url, _html.unescape(href).strip())
        if not raw or href in seen or not _wanted(raw, include, exclude):
            continue
        seen.add(href)
        try:
            d = datetime.strptime(_text(dtxt), '%B %d, %Y').date()
        except ValueError:
            d = None
        title, d2 = split_title_date(raw)
        items.append({'item_key': href, 'raw_title': raw, 'title': title, 'url': href,
                      'kind': _kind(href), 'notice_date': d or d2})
    if not rows:
        raise ValueError('No notices list found — the site layout may have changed.')
    return items          # empty is fine: no PG notice yet this season



# ===== arunachal =====
def read_wp_feed(feeds, include=None, exclude=None):
    """Any WordPress site's RSS feed (e.g. RIMS Imphal https://rims.edu.in/rimsman/category/admission/feed/,
    page 2 = ?paged=2): <item><title>…</title><link>POST</link><pubDate>RFC-822</pubDate>
    <content:encoded>… <a href="…pdf">…</content:encoded>. Date = pubDate; url = the first PDF linked in
    the post body if any (kind 'pdf'), else the post link. item_key = the post link.
    A feed page past the end (404) is skipped; raises only if no feed answered with items."""
    from email.utils import parsedate_to_datetime
    s, items, seen, ok = _session(), [], set(), False
    for fd in feeds:
        r = s.get(fd, timeout=TIMEOUT)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        for block in re.findall(r'<item>(.*?)</item>', r.text, re.S):
            ok = True
            tm = re.search(r'<title>(.*?)</title>', block, re.S)
            lm = re.search(r'<link>(.*?)</link>', block, re.S)
            if not tm or not lm:
                continue
            raw = _text(re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', tm.group(1), flags=re.S))
            link = _html.unescape(lm.group(1)).strip()
            if not raw or link in seen or not _wanted(raw, include, exclude):
                continue
            seen.add(link)
            d = None
            pm = re.search(r'<pubDate>(.*?)</pubDate>', block)
            if pm:
                try: d = parsedate_to_datetime(pm.group(1).strip()).date()
                except (TypeError, ValueError): d = None
            url, kind = link, 'link'
            cm = re.search(r'<content:encoded>(.*?)</content:encoded>', block, re.S)
            pdf = re.search(r'href=["\']([^"\']+\.pdf)["\']', cm.group(1) if cm else '', re.I)
            if pdf:
                url, kind = _html.unescape(pdf.group(1)).strip(), 'pdf'
            title, _d2 = split_title_date(raw)
            items.append({'item_key': link, 'raw_title': raw, 'title': title, 'url': url,
                          'kind': kind, 'notice_date': d})
    if not ok:
        raise ValueError('Feed empty or missing — the site may have changed.')
    return items          # empty is fine: no PG notice yet this season



# ===== dict_mz =====
def read_mizoram_posts(pages, include=None, exclude=None):
    """Mizoram Higher & Technical Education (dhte.mizoram.gov.in/category/notice-board?page=N) — the State
    Selection Board posts every selection notice (NEET-UG, NEET-PG ZMC&H state quota, BAMS, engineering, HR)
    as a post; the list has titles only:
    <div class="list-single-item"><a href="/post/<slug>" title="TITLE">…</a>.
    For each wanted title the post page is opened: date = 'Post Created On: 10<sup>th</sup> Dec 25',
    url = the first attachment PDF (/uploads/attachments/…pdf) if any, else the post link.
    item_key = the post URL."""
    from urllib.parse import urljoin
    s, items, seen, rows = _session(), [], set(), 0
    for pg in pages:
        r = s.get(pg, timeout=TIMEOUT)
        r.raise_for_status()
        for href, ttl in re.findall(r'list-single-item">\s*<a href="([^"]+)"\s+title="([^"]*)"', r.text):
            rows += 1
            raw = _text(ttl)
            href = urljoin(r.url, _html.unescape(href).strip())
            if not raw or href in seen or not _wanted(raw, include, exclude):
                continue
            seen.add(href)
            url, kind, d = href, 'link', None
            try:
                p = s.get(href, timeout=TIMEOUT)
                if p.ok:
                    m = re.search(r'class="attachment-link"\s+href="([^"]+\.pdf)"', p.text, re.I)
                    if m:
                        url, kind = urljoin(p.url, _html.unescape(m.group(1)).strip()), 'pdf'
                    dm = re.search(r'Post Created On:\s*(\d{1,2})\s*(?:<sup>\w*</sup>)?\s*([A-Za-z]{3})\w*\s+(\d{2,4})', p.text)
                    if dm:
                        yy = int(dm.group(3)); yy = yy + 2000 if yy < 100 else yy
                        try: d = datetime.strptime(f'{dm.group(1)} {dm.group(2)} {yy}', '%d %b %Y').date()
                        except ValueError: d = None
            except Exception as e:
                logging.warning("dhte mizoram post %s: %s", href, e)
            title, d2 = split_title_date(raw)
            items.append({'item_key': href, 'raw_title': raw, 'title': title, 'url': url,
                          'kind': kind, 'notice_date': d or d2})
    if not rows:
        raise ValueError('No notices list found — the site layout may have changed.')
    return items          # empty is fine: no PG notice yet this season


# reader name (SOURCES[...]['reader']) → call with the source config
DISPATCH = {
    'pdf_links_url': lambda s: read_pdf_links_url(s['url'], s.get('pages'), s.get('url_include'), s.get('include'), s.get('exclude')),
    'amru_hp': lambda s: read_amru_hp(s['url']),
    'centac_home': lambda s: read_centac_home(s['url'], s.get('include'), s.get('exclude')),
    'mh_cetcell': lambda s: read_mh_cetcell(s.get('pages') or [s['url']], s.get('include'), s.get('exclude')),
    'dmer_hr': lambda s: read_dmer_hr(s['url']),
    'row_table': lambda s: read_row_table(s.get('pages') or [s['url']], s.get('include'), s.get('exclude'), s.get('strip'), s.get('max_rows')),
    'drupal_news': lambda s: read_drupal_news(s['url'], s.get('include'), s.get('exclude')),
    'pdf_links_soft': lambda s: read_pdf_links_soft(s['url'], s.get('pages'), s.get('include'), s.get('exclude')),
    'gmch_chd': lambda s: read_gmch_chd(s['url']),
    'hnbumu_pg': lambda s: read_hnbumu_pg(s['url']),
    'jceceb_grid': lambda s: read_jceceb_grid(s.get('pages') or [s['url']], s.get('include'), s.get('exclude')),
    'jk_bopee': lambda s: read_jk_bopee(s['url']),
    'raj_orderportal': lambda s: read_raj_orderportal(s['dept_codes'], s.get('include'), s.get('exclude')),
    'dmet_odisha': lambda s: read_dmet_odisha(s.get('pages') or [s['url']], s.get('include'), s.get('exclude')),
    'pdf_links_lastmod': lambda s: read_pdf_links_lastmod(s['url'], s.get('pages'), s.get('include'), s.get('exclude')),
    'badge_list': lambda s: read_badge_list(s['url'], s.get('include'), s.get('exclude')),
    'wp_feed': lambda s: read_wp_feed(s.get('feeds') or [s['url'].rstrip('/') + '/feed/'], s.get('include'), s.get('exclude')),
    'mizoram_posts': lambda s: read_mizoram_posts(s.get('pages') or [s['url']], s.get('include'), s.get('exclude')),
}
