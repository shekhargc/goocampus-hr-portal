"""Counselling-notice scraper → News Inbox (founder 2026-10-08).

Watches each counselling authority's notices page and drops every NEW notice into
`pg_news_inbox` for the team to review. Nothing is published automatically: from the
inbox the team clicks "Add to News", which pre-fills the newsroom form (heading,
authority, date, official link) and, for a PDF notice, attaches the PDF on save.

Runs 4x a day on the server — 10:00 AM, 1:00 PM, 6:30 PM and 11:00 PM IST — plus a "Check now"
button. Several processes may start the schedule (2 gunicorn workers x live + staging,
one shared DB), so each run takes a Postgres advisory lock and skips a source that was
checked in the last 20 minutes; inbox rows are unique per (source, item) anyway.

Sources are site-specific (each govt site lays notices out differently), so each
source names a reader. Start: All-India MCC (PG) + Karnataka KEA — PG Medical/DNB 2026.

FETCHING NOW RUNS ON THE FOUNDER'S MAC (2026-10-08): KEA + MCC refuse connections from
foreign data-centre IPs (Render), so tools/news_fetcher/newsfetch.py runs on the Mac (Indian
IP) from a Claude Code scheduled task, which also reads each new PDF and writes an AI draft
(headline / summary / 150-250 word article / category / key dates with source quotes), then
POSTs it to /api/pg/news-inbox/ingest. The server-side schedule only runs if env
NEWS_SERVER_FETCH=1 (e.g. once an India proxy/server exists).
"""
import os
import re
import html as _html
import logging
from datetime import datetime, date
from db import get_db

# A normal browser UA — MCC answers 403 to bot-style user agents.
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/124.0 Safari/537.36')
TIMEOUT = (10, 30)          # (connect, read) seconds — a blocked site fails fast
RECENT_SKIP_MINUTES = 20


def _proxies():
    """Indian govt sites (KEA, MCC) refuse connections from foreign data-centre IPs, and the
    portal runs on Render outside India. Set env PG_INDIA_PROXY (e.g. http://user:pass@<india-ip>:3128)
    to fetch through a server in India. Unset → direct (works only from Indian IPs)."""
    p = (os.environ.get('PG_INDIA_PROXY') or '').strip()
    return {'http': p, 'https': p} if p else None

# code → config. authority_code matches pg_admin/authorities.py; news_authority is the
# value the newsroom form's "Counselling Authority" dropdown expects.
SOURCES = {
    'mcc_pg': {
        'short': 'All India MCC',            # News Inbox tab name
        'label': 'All-India MCC — PG Medical Counselling',
        'authority_code': 'mcc',
        'news_authority': '__all__',
        'url': 'https://mcc.nic.in/pg-medical-counselling/',
        'pages': ['https://mcc.nic.in/pg-medical-counselling/', 'https://mcc.nic.in/news-events-pg/',
                  'https://mcc.nic.in/current-events-pg/', 'https://mcc.nic.in/eservices-schedule-pg/'],
        'reader': 'pdf_links',
        'enabled': True,
    },
    'kea_pgmed_2026': {
        'short': 'Karnataka',            # News Inbox tab name
        'label': 'Karnataka KEA — PG Medical / DNB 2026',
        'authority_code': 'kea',
        'news_authority': 'state:Karnataka',
        'url': 'https://cetonline.karnataka.gov.in/kea/pgetmed2026',
        'reader': 'kea_aspnet',
        # bulletins that live somewhere else than the notices page (founder 2026-10-13): KEA's
        # PGET 2026 brochure sits behind "Download Brochure" on the application login page.
        'fixed_docs': [{'url': 'https://cetonline.karnataka.gov.in/pgneet2026/docs/CET2026_Brochure.pdf',
                        'title': 'Karnataka PGET 2026 (PG Medical) Information Brochure'}],
        'enabled': True,
    },
    # ── batch 2 (founder 2026-10-13): Kerala, Tamil Nadu, Andhra Pradesh, Telangana ──
    'cee_kerala_pgm': {
        'short': 'Kerala',            # News Inbox tab name
        'label': 'Kerala CEE — PG Medical 2026',
        'authority_code': 'cee_kerala',
        'news_authority': 'state:Kerala',
        # application-phase page now; the candidate portal (pgm2026) opens later — both read, a
        # missing page is skipped. Next year: bump the year here.
        'url': 'https://cee.kerala.gov.in/pgmonline2026/notification',
        'pages': ['https://cee.kerala.gov.in/pgmonline2026/notification',
                  'https://cee.kerala.gov.in/pgm2026/notification'],
        # course home pages: prospectus + menu PDFs + the "Important Dates" box (founder 2026-10-13)
        'home': ['https://cee.kerala.gov.in/pgmonline2026/', 'https://cee.kerala.gov.in/pgm2026/'],
        'reader': 'cee_kerala',
        'enabled': True,
    },
    'tn_pg_medical': {
        'short': 'Tamil Nadu',            # News Inbox tab name
        'label': 'Tamil Nadu DME Selection Committee — PG Medical (MD/MS/Diploma)',
        'authority_code': 'dmer_tn',
        'news_authority': 'state:Tamil Nadu',
        'url': 'https://tnmedicalselection.net/',
        'tag': 'cssPG002',                      # the site tags each news line by course; PG002 = PG Medical
        'reader': 'tn_tagged',
        'enabled': True,
    },
    'ap_pg_medical': {
        'short': 'Andhra Pradesh',            # News Inbox tab name
        'label': 'Andhra Pradesh Dr NTR UHS — PG Medical (CQ + MQ)',
        'authority_code': 'ntruhs',
        'news_authority': 'state:Andhra Pradesh',
        'url': 'https://drntr.uhsap.in/index/notification_admission',
        'reader': 'aspnet_filter',
        # the page lists ALL admissions; use the site's own "Degree" filter = Medical PG Diploma/Degree
        # (founder 2026-10-13: titles like "PG Degree-Diploma …" / DNB were missed by a keyword filter)
        'form': {'ctl00$ContentPlaceHolder1$DropDownList1': '3', 'ctl00$ContentPlaceHolder1$Button1': 'Submit'},
        'exclude': r'\bMDS\b|dental|homoeo|ayurved|ayush|nursing',
        'enabled': True,
    },
    'tg_pg_medical': {
        'short': 'Telangana',            # News Inbox tab name
        'label': 'Telangana KNRUHS — PG Medical',
        'authority_code': 'knruhs',
        'news_authority': 'state:Telangana',
        'url': 'https://www.knruhs.telangana.gov.in/admission-notification/',
        'pages': ['https://www.knruhs.telangana.gov.in/admission-notification/?results_page=1',
                  'https://www.knruhs.telangana.gov.in/admission-notification/?results_page=2'],
        'reader': 'date_table',
        'include': r'MEDICAL\s+PG|PG\s+MEDICAL|P\.\s*G\.?\s+MEDICAL|POST\s*GRADUATE\s+MEDICAL|NEET[\s-]*PG|MD\s*/\s*MS',
        'exclude': r'\bMDS\b|DENTAL|AYUSH|NURSING|HOMOEO|AYURVED',
        'enabled': True,
    },
    # ── batch 3 (founder 2026-10-13: all other states) — found + verified on each authority's
    #    OFFICIAL site (survey notes: scratchpad states/<code>.json); readers in news_readers_states ──
    # Gujarat: ready — medadmgujarat.org is the Admission Committee for Professional Post Graduate Medical Courses (ACPPGMEC), constituted under the Gujarat Professional Medical Educational Colleges or I
    'acpmec_pg': {
        'label': 'Gujarat ACPPGMEC — PG Medical (MD/MS/Diploma) Admission 2026',
        'short': 'Gujarat',
        'authority_code': 'acpmec',
        'news_authority': 'state:Gujarat',
        'url': 'https://medadmgujarat.org/pg/home.aspx',
        'reader': 'pdf_links_url',
        'url_include': '/PG2026/MDMS/',
        'enabled': True,
    },
    # Himachal Pradesh: ready — Official: amruhp.ac.in menu Admissions > "Apply for Admission & Various Counselling" -> /counselling-notifications/. The page has one sub-tab per course; <div id="mdms_neetpg"> = "
    'amru_hp_pg': {
        'label': 'Himachal Pradesh AMRU — PG Medical (MD/MS/DNB) 2026',
        'short': 'Himachal Pradesh',
        'authority_code': 'amru_hp',
        'news_authority': 'state:Himachal Pradesh',
        'url': 'https://amruhp.ac.in/counselling-notifications/',
        'reader': 'amru_hp',
        'enabled': True,
    },
    # Andaman & Nicobar: no_pg_2026_yet — andssw1.and.nic.in/aniims (homepage in authorities.py): HTTPS connection reset, HTTP 403/404 from this Mac — unusable. ANIIMS announcements are instead published on the A&N Adminis
    'aniims_pg': {
        'label': 'Andaman & Nicobar — ANIIMS (via UT college-admission portal)',
        'short': 'Andaman & Nicobar',
        'authority_code': 'aniims',
        'news_authority': 'state:Andaman & Nicobar',
        'url': 'https://collegeadmission.andamannicobar.gov.in/',
        'reader': 'pdf_links_soft',
        'include': '(?=.*ANIIMS|.*Andaman\\s*&?\\s*Nicobar\\s*Islands\\s*Institute)(?=.*(P\\.?\\s*G\\.?\\s*Medical|Post[\\s-]*Graduate|NEET[\\s-]*PG|\\bM\\.?\\s*D\\.?\\s*/\\s*M\\.?\\s*S\\b|\\bMD\\b|\\bMS\\b))',
        'enabled': False,
    },
    # Bihar: no_pg_2026_yet — Official: bceceboard.bihar.gov.in is the BCECE Board (Govt of Bihar); PGMACIndex.php is the "PGMAC" entry of its Examinations menu, page heading "NOTICE BOARD of PGMAC - 2026" (Pos
    'bceceb_pg': {
        'label': 'Bihar BCECEB — PGMAC (PG Medical MD/MS/PGD/DNB) 2026',
        'short': 'Bihar',
        'authority_code': 'bceceb',
        'news_authority': 'state:Bihar',
        'url': 'https://bceceboard.bihar.gov.in/PGMACIndex.php',
        'pages': ['https://bceceboard.bihar.gov.in/PGMACIndex.php', 'https://bceceboard.bihar.gov.in/NoticeBoard.php'],
        'reader': 'pdf_links_soft',
        'include': 'P(?:GM|MG)AC(?!\\s*[\\[(]?\\s*AYUSH)|Post\\s*Graduate\\s*Medical|PG\\s*Medical|NEET\\s*\\(?\\s*PG',
        'exclude': '^(?!.*PGMAC\\s*/).*(AYUSH|UNANI|HOMOEO|AYURVED|DENTAL|PGDAC)|P(?:GM|MG)AC\\s*-?\\s*20(?:1\\d|2[0-4])\\b',
        'enabled': True,
    },
    # Punjab: ready — Official: bfuhs.ac.in > Admissions (index1.aspx) > "NEET PG 2026" -> https://admission.bfuhsonline.ac.in/mdms/mdms.asp (BFUHS admissions subdomain, bfuhsonline.ac.in). The one page
    'bfuhs_pg': {
        'label': 'Punjab BFUHS — PG Medical (MD/MS) NEET-PG 2026',
        'short': 'Punjab',
        'authority_code': 'bfuhs',
        'news_authority': 'state:Punjab',
        'url': 'https://admission.bfuhsonline.ac.in/mdms/mdms.asp',
        'reader': 'pdf_links_soft',
        'include': 'MD\\s*[/-]?\\s*MS\\b|\\bMD\\b|PG\\s*MEDICAL|MEDICAL\\s*PG|POST\\s*-?\\s*GRADUATE\\s+MEDICAL|PCMS|IN[\\s-]*SERVICE|NEET[\\s-]*PG(?![\\s-]*MDS)|DNB|DIPLOMA',
        'exclude': '\\bMDS\\b|DENTAL|\\bBDS\\b|NURSING|AYUR|HOMOEO',
        'enabled': True,
    },
    # Puducherry: no_pg_2026_yet — Official: centacpuducherry.in is linked from the Govt of Puducherry Directorate of Higher & Technical Education site (dhte.py.gov.in → https://www.centacpuducherry.in/); header "GO
    'centac_pg': {
        'label': 'Puducherry CENTAC — PG Medical (MD/MS) 2026-27',
        'short': 'Puducherry',
        'authority_code': 'centac',
        'news_authority': 'state:Puducherry',
        'url': 'https://centacpuducherry.in/',
        'reader': 'centac_home',
        'include': 'P\\.?\\s*G\\.?\\s*MEDICAL|M\\.\\s*D\\.?\\s*/\\s*M\\.\\s*S|\\bMD\\s*/\\s*MS\\b|NEET[\\s-]*PG|POST[\\s-]*GRADUATE\\s+MEDICAL|\\bDNB\\b|NON[\\s-]*CLINICAL\\s+P\\.?\\s*G|\\bP\\.?\\s*G\\.?\\s+COURSES',
        'exclude': '^(?!.*(P\\.?\\s*G\\.?\\s*MEDICAL|M\\.\\s*D\\.?\\s*/\\s*M\\.\\s*S|\\bMD\\s*/\\s*MS\\b)).*(DENTAL|M\\.\\s*D\\.\\s*S|\\bMDS\\b|AYUSH|NURSING)',
        'enabled': True,
    },
    # Maharashtra: no_pg_2026_yet — Official: cetcell.mahacet.org = State Common Entrance Test Cell, Maharashtra (statutory body under the 2015 Act; listed as such in the Govt eGovernance URL directory dhepune.gov.in
    'cetcell_mh_pg': {
        'label': 'Maharashtra State CET Cell — NEET-PG (MD/MS) CAP 2026',
        'short': 'Maharashtra',
        'authority_code': 'cetcell_mh',
        'news_authority': 'state:Maharashtra',
        'url': 'https://medical2026.mahacet.org/NEET-PGM-2026/login',
        'pages': ['https://medical2026.mahacet.org/NEET-PGM-2026/login'],
        'reader': 'mh_cetcell',
        'enabled': True,
    },
    # Chhattisgarh: no_pg_2026_yet — Official: cgdme.admissions.nic.in is the NIC (S3WaaS, .nic.in) eCounselling site 'Content Owned and Managed by Chhattisgarh Directorate of Medical Education'; linked from cgdme.co.
    'dme_cg_pg': {
        'label': 'Chhattisgarh DME — CG State NEET PG (MD/MS) Counselling (NIC eCounselling portal)',
        'short': 'Chhattisgarh',
        'authority_code': 'dme_cg',
        'news_authority': 'state:Chhattisgarh',
        'url': 'https://cgdme.admissions.nic.in/',
        'pages': ['https://cgdme.admissions.nic.in/', 'https://cgdme.admissions.nic.in/notices/', 'https://cgdme.admissions.nic.in/information-bulletin/', 'https://cgdme.admissions.nic.in/schedule/', 'https://cgdme.admissions.nic.in/seat-matrix/', 'https://cgdme.admissions.nic.in/merit-list/', 'https://cgdme.admissions.nic.in/allotment-result/', 'https://cgdme.admissions.nic.in/or-cr/', 'https://cgdme.admissions.nic.in/procedures/'],
        'reader': 'pdf_links_soft',
        'include': 'NEET[\\s-]*PG|MD\\s*/\\s*MS|PG\\s*\\(\\s*MD|PG\\s*Medical|\\bPG\\b|Post\\s*Graduate',
        'exclude': '\\bMDS\\b|^\\s*PG\\s+DENTAL|\\bUG\\b|MBBS|\\bBDS\\b|BPT|nursing',
        'enabled': True,
    },
    # Madhya Pradesh: ready — Official: medicaleducation.mp.gov.in (Dept of Medical Education, MP) links to dme.mponline.gov.in (MPOnline is the GoMP portal, .gov.in). From DMEhome.aspx: 'DME Post Graduate Coun
    'dme_mp_pg': {
        'label': 'Madhya Pradesh DME — State NEET PG Counselling (MD/MS) 2026-27',
        'short': 'Madhya Pradesh',
        'authority_code': 'dme_mp',
        'news_authority': 'state:Madhya Pradesh',
        'url': 'https://dme.mponline.gov.in/portal/services/dmemp/DMEPG/Profile/ProfileLoginHome.aspx?Counstype=rfZR9zLVYzySY17sU9L9gA%3d%3d',
        'reader': 'pdf_links',
        'enabled': True,
    },
    # Haryana: no_pg_2026_yet — Official: dmer.haryana.gov.in (reachable from the Mac today, 2026-10-13). DMER Haryana itself runs MD/MS/DNB/Diploma state counselling (not UHSR): the counselling portal hry.online
    'dmer_hr_pg': {
        'label': 'Haryana DMER — PG Medical (MD/MS/Post-MBBS DNB & Diploma) 2026',
        'short': 'Haryana',
        'authority_code': 'dmer_hr',
        'news_authority': 'state:Haryana',
        'url': 'https://dmer.haryana.gov.in/',
        'reader': 'dmer_hr',
        'enabled': True,
    },
    # Uttar Pradesh: ready — Official: dgme.up.gov.in is the Directorate General of Medical Education & Training, UP (.gov.in); its home menu 'COUNSELLING & ALLOTMENT' -> /Welcome/counselling. The counselling 
    'dmetup_pg': {
        'label': 'Uttar Pradesh DGME — UP NEET PG (MD/MS/Diploma/DNB) Counselling',
        'short': 'Uttar Pradesh',
        'authority_code': 'dmetup',
        'news_authority': 'state:Uttar Pradesh',
        'url': 'https://dgme.up.gov.in/Welcome/counselling',
        'pages': ['https://dgme.up.gov.in/Welcome/counselling'],
        'reader': 'row_table',
        'include': 'NEET[\\s-]*PG|\\bPG\\b|M\\.?D\\.?\\s*/\\s*M\\.?S\\.?|\\bMD\\b|D\\.?N\\.?B\\.?|post[\\s-]*graduate',
        'exclude': '\\bMDS\\b|DENTAL|\\bUG\\b|MBBS|\\bBDS\\b|bond|deploy|senior resident|junior resident|\\bDM\\s*/\\s*M\\.?CH|NEET[\\s-]*SS|PNDT',
        'strip': 'Size\\s*:.*$',
        'max_rows': 150,
        'enabled': True,
    },
    # Dadra & Nagar Haveli: unreachable — vbch.dnh.nic.in (Shri Vinoba Bhave Civil Hospital / NAMO MERI site, the homepage listed in authorities.py) does not resolve at all — NXDOMAIN on this Mac and via 8.8.8.8; namomeri.
    'dmhs_dnh_pg': {
        'label': 'DNH & DD — NAMO MERI Silvassa PG (MD/MS)',
        'short': 'Dadra & Nagar Haveli',
        'authority_code': 'dmhs_dnh',
        'news_authority': 'state:Dadra & Nagar Haveli',
        'url': 'http://vbch.dnh.nic.in/content/latest-announcement',
        'reader': 'pdf_links_soft',
        'include': 'P\\.?\\s*G\\.?\\s*Medical|Post[\\s-]*Graduate\\s*(Medical|Degree)|NEET[\\s-]*PG|\\bM\\.?D\\.?\\s*/\\s*M\\.?S\\b',
        'enabled': False,
    },
    # Goa: needs_reader — Official + confirmed by the PDF itself: PG-Medical-Advt.pdf (DTE/CAD/PG-MED/2026, dated 09/10/2026) says "As designated State Counselling Authority for conducting admissions to Pos
    'dte_goa_pg': {
        'label': 'Goa DTE — PG Medical (Goa Medical College) 2026',
        'short': 'Goa',
        'authority_code': 'dte_goa',
        'news_authority': 'state:Goa',
        'url': 'https://dte.goa.gov.in/news',
        'reader': 'drupal_news',
        'include': 'PG\\s*Medical|Post[\\s-]*Graduate\\s*Medical|NEET[\\s-]*PG|\\bMD\\s*/\\s*MS\\b|\\bDNB\\b|Goa\\s*Medical\\s*College',
        'exclude': 'Ayurved|AYUSH|Homo?eo|Dental|\\bMDS\\b|Nursing',
        'fixed_docs': [{'url': 'https://dte.goa.gov.in/sites/default/files/2026-10/PG-MEDICAL-Rules-2026.pdf', 'title': 'Goa PG Medical Admission Rules 2026 (Goa Medical College)'}],
        'enabled': True,
    },
    # Delhi: no_pg_2026_yet — Official: ipu.ac.in home page menu "Admission 2026-27 > Notices - Admission" -> /adm2026/adm2026notices.php; PDFs are ipu.ac.in/Pubinfo2026/*.pdf. The page lists ALL GGSIPU courses
    'ggsipu_pg': {
        'label': 'Delhi GGSIPU — PG Medical (PGMC, MD/MS/Diploma) — GGSIP University quota',
        'short': 'Delhi',
        'authority_code': 'ggsipu',
        'news_authority': 'state:Delhi',
        'url': 'https://ipu.ac.in/adm2026/adm2026notices.php',
        'pages': ['https://ipu.ac.in/adm2026/adm2026notices.php', 'https://ipu.ac.in/adm2026/adm2026notices.php?page=2&limit=25', 'https://ipu.ac.in/adm2026/adm2026notices.php?page=3&limit=25'],
        'reader': 'pdf_links_soft',
        'include': 'PGMC|POST\\s*-?\\s*GRADUATE\\s+MEDICAL|NEET[\\s-]*PG|PG\\s+MEDICAL|\\bMD\\b|MD\\s*/\\s*MS|\\bDNB\\b|CODE\\s*[-:]?\\s*102\\b',
        'exclude': 'AYURVED|HOMOEO|HOMEO|NURSING|\\bMDS\\b|DENTAL|PGAC|\\bBAMS\\b|\\bBHMS\\b|PACKAGING|CUET',
        'fixed_docs': [{'url': 'https://ipu.ac.in/adm2026/adm2026br/br280126pgprg/ch09.pdf', 'title': 'GGSIPU Admission Brochure 2026-27 — Chapter 9: PGMC (MD/MS/PG Diploma) admission information'}],
        'enabled': True,
    },
    # Chandigarh: no_pg_2026_yet — Official: gmch.gov.in > Admissions (/admissions) lists one page per session: "Admission MD/MS-2025" (/node/6481 = /admission-mdms-2025, 37 PDFs: prospectus, eligibility lists, seat
    'gmch_chd_pg': {
        'label': 'Chandigarh GMCH-32 — MD/MS (UT state quota) 2026',
        'short': 'Chandigarh',
        'authority_code': 'gmch_chd',
        'news_authority': 'state:Chandigarh',
        'url': 'https://gmch.gov.in/admissions',
        'reader': 'gmch_chd',
        'enabled': True,
    },
    # Uttarakhand: no_pg_2026_yet — Official link chain: hnbumu.ac.in home page (HNB Uttarakhand Medical Education University) links "NEET MDS 2026 Uttarakhand State Centralized Counselling" -> https://meta-secure.co
    'hnbumu_pg': {
        'label': 'Uttarakhand HNBUMU — PG Medical (MD/MS) state counselling 2026',
        'short': 'Uttarakhand',
        'authority_code': 'hnbumu',
        'news_authority': 'state:Uttarakhand',
        'url': 'https://meta-secure.com/HNBUMU_NEETPG',
        'reader': 'hnbumu_pg',
        'enabled': True,
    },
    # Jharkhand: needs_reader — Official: jceceb.jharkhand.gov.in = Jharkhand Combined Entrance Competitive Examination Board; home page menu Notices » "Counselling Notices" (Links/counselling.aspx) and "Download
    'jceceb_pg': {
        'label': 'Jharkhand JCECEB — PG Medical (MD/MS/Diploma & DNB) State Quota 2026',
        'short': 'Jharkhand',
        'authority_code': 'jceceb',
        'news_authority': 'state:Jharkhand',
        'url': 'https://jceceb.jharkhand.gov.in/Links/counselling.aspx',
        'pages': ['https://jceceb.jharkhand.gov.in/Links/counselling.aspx', 'https://jceceb.jharkhand.gov.in/Links/download.aspx'],
        'reader': 'jceceb_grid',
        'include': 'NEET\\s*[\\(\\-]?\\s*PG|Post[\\s-]*Graduate\\s*(Medical|Courses\\s*\\(MD)|\\bPG\\s*Medical|Medical\\s*PG|MD\\s*/\\s*MS|\\bDNB\\b',
        'exclude': 'Homo?eopath|AIAPGET|AYUSH|Ayurved|Unani|^(?!.*NEET\\s*[\\(\\-]?\\s*PG)(?=.*(\\bMDS\\b|Dental))',
        'enabled': True,
    },
    # Jammu & Kashmir: no_pg_2026_yet — Official: jkbopee.gov.in/NoticeBoard.aspx (BOPEE's own Notice Board; 1,368 notices of all courses and years in one list). Rows are <li data-date="dd-mm-yyyy"><a href="Pdf/Downloade
    'jk_bopee_pg': {
        'label': 'J&K BOPEE — NEET-PG (MD/MS/PG Diploma) + Post-MBBS DNB 2026',
        'short': 'Jammu & Kashmir',
        'authority_code': 'jk_bopee',
        'news_authority': 'state:Jammu & Kashmir',
        'url': 'https://jkbopee.gov.in/NoticeBoard.aspx',
        'reader': 'jk_bopee',
        'enabled': True,
    },
    # Rajasthan: no_pg_2026_yet — RUHS (ruhsraj.org, admissions.ruhsraj.org 2026-27) does NOT run NEET-PG MD/MS state counselling — its admissions portal lists only CUET/PGET (nursing/pharmacy/MSc), PhD etc.; no MD
    'ruhs_pg': {
        'label': 'Rajasthan NEET PG Counselling Board (SMS Medical College) — via Medical Education Dept order portal',
        'short': 'Rajasthan',
        'authority_code': 'ruhs',
        'news_authority': 'state:Rajasthan',
        'url': 'https://medicaleducation.rajasthan.gov.in/smsjaipur/#/department-order/102',
        'reader': 'raj_orderportal',
        'include': 'NEET[\\s-]*PG|PG\\s*Medical|Medical\\s*PG|M\\.?D\\.?\\s*/\\s*M\\.?S|post[\\s-]*graduate|स्नातकोत्तर|DNB',
        'exclude': '\\bMDS\\b|dental|nursing|pharm|ayush|ayurved|homoeo|bond|सेवा बन्ध|super\\s*speciality|सुपर',
        'dept_codes': [102, 357],
        'enabled': True,
    },
    # ── East & North-East (found + verified on official sites; survey notes in states/<code>.json) ──
    # West Bengal: ready — wbmcc.nic.in is WBMCC's NIC/S3WaaS site; it links to Govt of West Bengal (wb.gov.in) and the WB Health dept (wbhealth.gov.in) in its header. Menu 'PG Medical' (
    'wbmcc_pg': {
        'label': 'West Bengal WBMCC — PG Medical (MD/MS/Diploma/DNB) 2026',
        'short': 'West Bengal',
        'authority_code': 'wbmcc',
        'news_authority': 'state:West Bengal',
        'url': 'https://wbmcc.nic.in/pg-medical-notice-events/',
        'pages': ['https://wbmcc.nic.in/pg-medical-notice-events/', 'https://wbmcc.nic.in/pg-medical-counselling/', 'https://wbmcc.nic.in/pg-medical-eservices-schedule/'],
        'reader': 'pdf_links',
        'enabled': True,
    },
    # Odisha: needs_reader — Odisha PG Medical counselling is run by DMET Odisha, not OJEE; OJEE (ojee.nic.in) only lists MBBS/BDS/BAMS/BHMS/pharmacy. How it was confirmed: the official DME
    'ojee_pg': {
        'label': 'Odisha DMET — PG Medical Counselling (State Quota) 2026-27',
        'short': 'Odisha',
        'authority_code': 'ojee',
        'news_authority': 'state:Odisha',
        'url': 'https://dmetodisha.in/PGMCC_Static/MEDICAL%20COUNSELLING%201/Notifications.html',
        'pages': ['https://dmetodisha.in/PGMCC_Static/MEDICAL%20COUNSELLING%201/Notifications.html', 'https://dmetodisha.in/PGMCC_Static/MEDICAL%20COUNSELLING%201/Information%20Bulletin.html', 'https://dmetodisha.in/PGMCC_Static/MEDICAL%20COUNSELLING%201/Counselling%20Schedule.html'],
        'reader': 'dmet_odisha',
        'enabled': True,
    },
    # Assam: needs_reader — dme.assam.gov.in is the official Assam DME site. Its home page has a link 'Admission Notice-UG/PG/Others(New)' → /node/95928, which 301-redirects to /latest/adm
    'dme_assam_pg': {
        'label': 'Assam DME — PG Medical (NEET-PG State Quota)',
        'short': 'Assam',
        'authority_code': 'dme_assam',
        'news_authority': 'state:Assam',
        'url': 'https://dme.assam.gov.in/latest/admission-notice-ugpgothersnew',
        'reader': 'pdf_links_lastmod',
        'include': 'NEET[\\s_-]*PG|\\bPG\\b|P\\.G\\.|post[\\s-]*graduate|\\bMD\\b|\\bMS\\b|\\bDNB\\b|prospectus|bulletin',
        'exclude': '\\bMDS\\b|dental|nursing|M\\.?\\s*Sc|pharm|ayush|homoeo|ayurved|post[\\s_-]*PG|\\bSR\\b|engagement',
        'enabled': True,
    },
    # Tripura: ready — Official link: the DME Tripura home page (dme.tripura.gov.in) has a menu link 'NEET Counselling' → https://trmcc.admissions.nic.in/ (Tripura Medical Counselling
    'dme_tripura_pg': {
        'label': 'Tripura TRMCC (DME) — PG Medical Counselling 2026',
        'short': 'Tripura',
        'authority_code': 'dme_tripura',
        'news_authority': 'state:Tripura',
        'url': 'https://trmcc.admissions.nic.in/pg-counselling/',
        'reader': 'pdf_links',
        'enabled': True,
    },
    # Manipur: needs_reader — manipurhealthdirectorate.mn.gov.in is the official Directorate of Health Services, Govt of Manipur (mn.gov.in). Its /notifications ('News & Notifications') page
    'dhs_manipur_pg': {
        'label': 'Manipur DHS — State Level PG (MD/MS) Counselling notices',
        'short': 'Manipur',
        'authority_code': 'dhs_manipur',
        'news_authority': 'state:Manipur',
        'url': 'https://manipurhealthdirectorate.mn.gov.in/notifications',
        'reader': 'badge_list',
        'include': 'NEET[\\s_-]*PG|\\bP\\.?\\s*G\\.?\\b|post[\\s-]*graduate|\\bMD\\b|\\bM\\.?S\\.?\\b(?!c)|\\bDNB\\b|MD\\s*/\\s*MS',
        'exclude': '\\bMDS\\b|dental|nursing|M\\.?\\s*Sc|pharm|ayush|homoeo|ayurved|post[\\s_-]*PG|engagement|projectionist|\\bMS\\s*\\(RP\\)|study\\s+leave',
        'enabled': True,
    },
    # Arunachal Pradesh: no_pg_2026_yet — Official link: the Arunachal Health & FW dept site health.arunachal.gov.in → 'Directorate of Medical Education (T&R)' page (/dometr.php) links to https://www.dm
    'arunachal_pg': {
        'label': 'Arunachal DMETR — NEET-PG State Quota (MD/MS/DNB) notices',
        'short': 'Arunachal Pradesh',
        'authority_code': 'arunachal',
        'news_authority': 'state:Arunachal Pradesh',
        'url': 'https://dmetrap.in/notices/',
        'feeds': ['https://dmetrap.in/notices/feed/'],
        'reader': 'wp_feed',
        'include': 'NEET[\\s_-]*PG|\\bP\\.?\\s*G\\.?\\b|post[\\s-]*graduate|\\bMD\\b|MD\\s*/\\s*MS|\\bDNB\\b',
        'exclude': '\\bMDS\\b|dental|nursing|M\\.?\\s*Sc|pharm|ayush|homoeo|ayurved|post[\\s_-]*PG',
        'enabled': True,
    },
    # Meghalaya: no_pg_2026_yet — meghealth.gov.in is the official Health & FW dept, Govt of Meghalaya (DHS-MER posts admissions there). Meghalaya has no state MD/MS counselling. What it does po
    'neigrihms_pg': {
        'label': 'Meghalaya DHS (MER) — PG / Post-MBBS Diploma notices',
        'short': 'Meghalaya',
        'authority_code': 'neigrihms',
        'news_authority': 'state:Meghalaya',
        'url': 'https://meghealth.gov.in/',
        'reader': 'pdf_links_lastmod',
        'include': 'NEET[\\s-]*PG|PG[\\s-]*NEET|post[\\s-]*MBBS|\\bMD\\b|MD\\s*/\\s*MS|\\bDNB\\b|Post[\\s-]*Graduate\\s+(Medical|Degree|Diploma|course|seat|counsel|admission)|\\bPG\\s+(Medical|Degree|Diploma|course|seat|counsel|admission)|CPS\\s+Mumbai',
        'exclude': 'study\\s+leave|nursing|pharm|M\\.?\\s*Sc|AYUSH|ayurved|homoeo|BAMS|BHMS|\\bMDS\\b|dental|bond|RIPANS|paramedical|para-medical',
        'enabled': True,
    },
    # Mizoram: no_pg_2026_yet — Mizoram does run a state-quota NEET-PG counselling: the State Selection Board under the Dept of Higher & Technical Education (dhte.mizoram.gov.in, official) for
    'dict_mz_pg': {
        'label': 'Mizoram Higher & Technical Education (State Selection Board) — NEET-PG ZMC&H state quota',
        'short': 'Mizoram',
        'authority_code': 'dict_mz',
        'news_authority': 'state:Mizoram',
        'url': 'https://dhte.mizoram.gov.in/category/notice-board',
        'pages': ['https://dhte.mizoram.gov.in/category/notice-board', 'https://dhte.mizoram.gov.in/category/notice-board?page=2', 'https://dhte.mizoram.gov.in/category/notice-board?page=3'],
        'reader': 'mizoram_posts',
        'include': 'NEET[\\s_-]*\\(?PG|\\bPG\\b|post[\\s-]*graduate|\\bMD\\b|MD\\s*/\\s*MS|\\bDNB\\b',
        'exclude': 'RIPANS|\\bMDS\\b|dental|nursing|M\\.?\\s*Sc|pharm|ayush|homoeo|ayurved|BAMS|BHMS',
        'enabled': True,
    },
    # NE common: None — 
    'rims_imphal_pg': {
        'label': 'RIMS Imphal — common State Level PG Counselling (7 NE states)',
        'short': 'RIMS Imphal (NE)',
        'authority_code': 'rims_imphal',
        'news_authority': 'state:Manipur',
        'url': 'https://rims.edu.in/rimsman/category/admission/',
        'feeds': ['https://rims.edu.in/rimsman/category/admission/feed/', 'https://rims.edu.in/rimsman/category/admission/feed/?paged=2', 'https://rims.edu.in/rimsman/category/admission/feed/?paged=3'],
        'reader': 'wp_feed',
        'include': '\\bMD\\b|MD\\s*/\\s*MS|\\bPG\\b|P\\.G\\.|post[\\s-]*graduate|NEET[\\s-]*PG|\\bDCP\\b',
        'exclude': '\\bMDS\\b|dental|MBBS|B\\.?Sc|nursing|protocol|senior\\s+resid|M\\.?\\s*Sc',
        'enabled': True,
    },
}


# ── tables ───────────────────────────────────────────────────────────────────
def ensure_news_inbox_tables(conn=None):
    own = conn is None
    conn = conn or get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_news_inbox (
            id SERIAL PRIMARY KEY,
            source_code TEXT NOT NULL,
            authority_code TEXT DEFAULT '',
            item_key TEXT NOT NULL,                 -- the site's own id, else the link
            title TEXT NOT NULL DEFAULT '',
            raw_title TEXT DEFAULT '',
            url TEXT DEFAULT '',
            kind TEXT DEFAULT 'link',               -- 'pdf' | 'link'
            notice_date DATE,
            status TEXT DEFAULT 'new',              -- new | posted | dismissed | document | seen
            news_id INTEGER,
            reviewed_by TEXT DEFAULT '',
            reviewed_at TIMESTAMP,
            first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (source_code, item_key)
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_news_inbox_status ON pg_news_inbox (status, first_seen_at)")
        # AI draft + the official PDF (fetched on the Mac — the server can't reach the sites).
        for col, typ in (('draft_json', 'TEXT'), ('drafted_at', 'TIMESTAMP'), ('pdf_data', 'BYTEA'),
                         ('pdf_name', "TEXT DEFAULT ''"), ('redraft_requested', 'BOOLEAN DEFAULT FALSE'),
                         ('history_note', "TEXT DEFAULT ''")):
            conn.execute(f"ALTER TABLE pg_news_inbox ADD COLUMN IF NOT EXISTS {col} {typ}")
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_news_scrape_runs (
            id SERIAL PRIMARY KEY,
            source_code TEXT NOT NULL,
            ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ok BOOLEAN DEFAULT TRUE,
            found INTEGER DEFAULT 0,
            new_count INTEGER DEFAULT 0,
            error TEXT DEFAULT '',
            trigger TEXT DEFAULT 'schedule'
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_news_scrape_runs ON pg_news_scrape_runs (source_code, ran_at)")
        conn.commit()
    except Exception as e:
        logging.warning("ensure_news_inbox_tables: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        if own:
            conn.close()


# ── parsing helpers ──────────────────────────────────────────────────────────
_DATE_RE = re.compile(r'(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(20\d{2})')


def _text(fragment):
    return re.sub(r'\s+', ' ', _html.unescape(re.sub(r'<[^>]+>', ' ', fragment or ''))).strip()


def split_title_date(raw):
    """'PG MEDICAL 2026 NOTIFICATION.06-10-2026' → ('PG MEDICAL 2026 NOTIFICATION', date(2026,10,6)).
    Takes the LAST date in the text; leaves the title alone if none parses."""
    ms = list(_DATE_RE.finditer(raw or ''))
    if not ms:
        return (raw or '').strip(), None
    m = ms[-1]
    try:
        d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return (raw or '').strip(), None
    title = re.sub(r'[(\[]\s*[.,]?\s*[)\]]', '', raw[:m.start()] + raw[m.end():]).strip()   # "()" left by "(date)"
    for _ in range(3):                                         # "(dd-mm-yyyy)" leaves "(" + ")"
        title = re.sub(r'[\s.,:;\-–(\[]+$', '', title).strip()
        if title.endswith(')') and title.count(')') > title.count('('):
            title = title[:-1]
    title = re.sub(r'\s*[(\[]?\s*Dated?\s*[-:–]?\s*[)\]]?\s*$', '', title, flags=re.I).strip()  # leftover "( Dated )"
    return (title or raw.strip()), d


SEASON_FROM = date(2026, 7, 1)       # NEET-PG 2026 counselling season (bump each year)


def in_season(it, season_from=None):
    """Founder 2026-10-13: EVERY notice of the current NEET-PG counselling season is news, however
    old — only the previous season (2025-26) is left out."""
    t = f"{it.get('title') or ''} {it.get('url') or ''}"
    cur = season_from or SEASON_FROM
    y = cur.year
    if (re.search(rf'{y - 1}\s*[-–/]\s*(20)?{str(y)[2:]}|\b{y - 1}\b', t)
            and not re.search(rf'{y}\s*[-–/]\s*(20)?{str(y + 1)[2:]}|\b{y}\b', t)):
        return False
    yrs = [int(x) for x in re.findall(r'\b(20\d{2})\b', t)]
    if yrs and max(yrs) < y:          # names only past years (e.g. "PGMAC-2024", "Session 2023")
        return False
    d = it.get('notice_date')
    if d:
        return d >= cur
    return True                       # undated on a current-season page → keep


def norm_title(t):
    """For repeat detection: case/punctuation/space-insensitive."""
    return re.sub(r'[^a-z0-9]+', ' ', (t or '').lower()).strip()


def is_repeat(conn, code, it):
    """A notice the site RE-POSTED under a new id (founder: only fresh news): the same PDF
    file again, or the same title with the same date / same link. A new title on an old
    link (e.g. 'Round 2 payment' on the same portal) is fresh news, not a repeat."""
    nt = norm_title(it['title'])
    for r in conn.execute("SELECT title, url, kind, notice_date FROM pg_news_inbox WHERE source_code = ? "
                          "AND (url = ? OR LOWER(title) = LOWER(?) OR notice_date = ?)",
                          (code, it['url'], it['title'], it['notice_date'])).fetchall():
        if it['kind'] == 'pdf' and r['url'] == it['url']:
            return True
        if norm_title(r['title']) == nt and (r['url'] == it['url'] or
                                             (it['notice_date'] and r['notice_date'] == it['notice_date'])):
            return True
    return False


def _kind(url):
    return 'pdf' if re.search(r'\.pdf($|[?#])', url or '', re.I) else 'link'


# ── readers ──────────────────────────────────────────────────────────────────
def read_kea_aspnet(url):
    """KEA (cetonline.karnataka.gov.in/kea/...) — ASP.NET page, Kannada by default.
    Switch to English via the language postback, then read the notice accordion:
    <a id='lnk<ID>' href='<pdf or page>'>TITLE dd-mm-yyyy</a>."""
    import requests
    s = requests.Session()
    s.headers['User-Agent'] = UA
    if _proxies():
        s.proxies.update(_proxies())
    r = s.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    page = r.text
    hidden = dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', page))
    if '__VIEWSTATE' in hidden and 'ddlLanguage' in page:
        data = dict(hidden)
        data.update({'__EVENTTARGET': 'ctl00$ddlLanguage', '__EVENTARGUMENT': '', 'ctl00$ddlLanguage': 'E'})
        try:
            r2 = s.post(r.url, data=data, timeout=TIMEOUT)
            if r2.ok and 'lnk' in r2.text:
                page = r2.text
        except Exception as e:                     # fall back to the Kannada page
            logging.warning("kea english switch failed: %s", e)
    items = []
    for item_id, href, inner in re.findall(
            r"<a\s+id=['\"]lnk(\d+)['\"]\s+href=['\"]([^'\"]*)['\"][^>]*>(.*?)</a>", page, re.S | re.I):
        raw = _text(inner)
        href = _html.unescape(href).strip()
        if not raw or not href or href == '#':
            continue
        if not href.lower().startswith('http'):
            from urllib.parse import urljoin
            href = urljoin(r.url, href)
        title, d = split_title_date(raw)
        items.append({'item_key': 'lnk' + item_id, 'raw_title': raw, 'title': title,
                      'url': href, 'kind': _kind(href), 'notice_date': d})
    if not items:
        raise ValueError('No notices found on the page — the site layout may have changed.')
    return items


_URL_DATE_RE = re.compile(r'(20\d{2})(\d{2})(\d{2})\d{2,}')


def _wanted(title, include=None, exclude=None):
    """Course filter for sites that list every course on one page."""
    if include and not re.search(include, title or '', re.I):
        return False
    if exclude and re.search(exclude, title or '', re.I):
        return False
    return True


def _session():
    import requests
    s = requests.Session()
    s.headers['User-Agent'] = UA
    if _proxies():
        s.proxies.update(_proxies())
    return s


def read_pdf_links(url, pages=None, include=None, exclude=None):
    """Generic: every <a href="...pdf">TITLE</a> on the given pages (MCC style). The date
    comes from the title if present, else from a yyyymmdd stamp in the file name.
    item_key = the PDF URL (stable)."""
    import requests
    from urllib.parse import urljoin
    items, seen = [], set()
    s = requests.Session()
    s.headers['User-Agent'] = UA
    if _proxies():
        s.proxies.update(_proxies())
    for pg in (pages or [url]):
        r = s.get(pg, timeout=TIMEOUT)
        r.raise_for_status()
        for href, inner in re.findall(r'<a\b[^>]*href=["\']([^"\']+\.pdf)["\'][^>]*>(.*?)</a>', r.text, re.S | re.I):
            href = urljoin(r.url, _html.unescape(href).strip())
            raw = _text(inner)
            if href in seen or not raw or raw.lower() in ('view', 'download', 'click here'):
                continue
            seen.add(href)
            if not _wanted(raw, include, exclude):
                continue
            title, d = split_title_date(raw)
            if not d:
                m = _URL_DATE_RE.search(href.rsplit('/', 1)[-1])
                if m:
                    try: d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    except ValueError: d = None
            items.append({'item_key': href, 'raw_title': raw, 'title': title, 'url': href,
                          'kind': 'pdf', 'notice_date': d})
    if not items:
        raise ValueError('No notices found on the page — the site layout may have changed.')
    return items


# how-to / help PDFs on the course home pages — not news
_KERALA_HELP = re.compile(r'prerequisite|imageupload|howto|faq|postoffice|contact|forget|login|instruction', re.I)


def _kerala_home(s, url):
    """Kerala course home page → menu PDFs (prospectus, seat distribution, lists…) + one item
    for the Important Dates box, keyed by the dates themselves (a changed date = new item)."""
    from urllib.parse import urljoin
    r = s.get(url, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    out = []
    for href, inner in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r.text, re.S | re.I):
        href = urljoin(r.url, _html.unescape(href).strip())
        if not re.search(r'\.pdf($|\?)', href, re.I) or _KERALA_HELP.search(href):
            continue
        t = _text(inner)
        if t:
            out.append({'item_key': href, 'raw_title': t, 'title': 'Kerala PG Medical 2026 — ' + t, 'url': href,
                        'kind': 'pdf', 'notice_date': None})
    box = re.search(r'Important Dates(.*?)</table>', r.text, re.S | re.I)
    if box:
        pairs = [(_text(a), _text(b)) for a, b in re.findall(r'<label>(.*?)</label>.*?<td[^>]*>(.*?)</td>', box.group(1), re.S | re.I)]
        pairs = [(a.rstrip(':'), b) for a, b in pairs if a and b]
        if pairs:
            line = '; '.join(f'{a}: {b}' for a, b in pairs)
            out.append({'item_key': 'important-dates|' + url + '|' + line, 'raw_title': line,
                        'title': 'Kerala PG Medical 2026 — Important dates: ' + line, 'url': url,
                        'kind': 'link', 'notice_date': None})
    return out


def read_aspnet_filter(url, form, include=None, exclude=None):
    """ASP.NET page with a filter form (e.g. AP Dr NTR UHS "Degree" dropdown): GET, re-post every
    hidden/text field with the chosen filter, then read the PDF links of the filtered result."""
    from urllib.parse import urljoin
    s = _session()
    r = s.get(url, timeout=(10, 60))
    r.raise_for_status()
    page = r.text[r.text.find('<form'):]
    data = {}
    for tag in re.findall(r'<input\b[^>]*>', page, re.I):
        n, v, ty = (re.search(r'name="([^"]+)"', tag), re.search(r'value="([^"]*)"', tag),
                    re.search(r'type="([^"]+)"', tag))
        if n and (not ty or ty.group(1).lower() in ('hidden', 'text')):
            data[n.group(1)] = _html.unescape(v.group(1)) if v else ''
    data.update(form)
    r2 = s.post(r.url, data=data, timeout=(10, 60), headers={'Referer': r.url})
    r2.raise_for_status()
    items, seen = [], set()
    for href, inner in re.findall(r'<a\b[^>]*href=["\']([^"\']+\.pdf)["\'][^>]*>(.*?)</a>', r2.text, re.S | re.I):
        href = urljoin(r2.url, _html.unescape(href).strip())
        raw = _text(inner)
        if href in seen or not raw or not _wanted(raw, include, exclude):
            continue
        seen.add(href)
        title, d = split_title_date(raw)
        if not d:
            m = _URL_DATE_RE.search(href.rsplit('/', 1)[-1])
            if m:
                try: d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError: d = None
        items.append({'item_key': href, 'raw_title': raw, 'title': title, 'url': href, 'kind': 'pdf', 'notice_date': d})
    if not items:
        raise ValueError('No notices found after filtering — the site layout may have changed.')
    return items


def read_cee_kerala(pages, home=None):
    """Kerala CEE (cee.kerala.gov.in/<course><year>/notification) — rows of
    TITLE · [Notification] [Press Release] [Vacancy] links (noti_view/<id>/UploadN, serve PDFs) · dd-mm-yyyy.
    A page that doesn't exist yet (404, e.g. the candidate portal before it opens) is skipped."""
    from urllib.parse import urljoin
    s, items, seen, ok = _session(), [], set(), False
    for pg in pages:
        r = s.get(pg, timeout=TIMEOUT)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        ok = True
        for chunk in re.split(r'<div class="row">', r.text):
            links = re.findall(r"<a\s+href=['\"]([^'\"]*noti_view[^'\"]*)['\"][^>]*>(.*?)</a>", chunk, re.S | re.I)
            if not links:
                continue
            head = _text(re.sub(r'<!--.*?-->', ' ', chunk.split('<a', 1)[0], flags=re.S))
            head = re.sub(r'^\W+', '', head)
            _t, d = split_title_date(_text(re.sub(r'<!--.*?-->', ' ', chunk, flags=re.S)))
            for href, lt in links:
                href = urljoin(r.url, _html.unescape(href).strip())
                if href in seen:
                    continue
                seen.add(href)
                lt = _text(lt)
                title = head if (len(links) == 1 or not lt) else f"{head} — {lt}"
                items.append({'item_key': href, 'raw_title': title, 'title': title or lt, 'url': href,
                              'kind': 'pdf', 'notice_date': d})
    for hp in (home or []):
        got = _kerala_home(s, hp)
        if got is None:
            continue
        ok = True
        for it in got:
            if it['item_key'] not in seen:
                seen.add(it['item_key'])
                items.append(it)
    if not ok:
        raise ValueError('Notices page not found — the site may have moved it (new year?).')
    return items          # an empty list is fine early in the season


_DMY_FILE_RE = re.compile(r'(\d{2})(\d{2})(20\d{2})\d{4,}')


def read_tn_tagged(url, tag):
    """Tamil Nadu Selection Committee home page: every news line is
    <div class="cssNLink css<COURSE>"> … <a href='news/ddmmyyyyhhmmss.pdf'>TITLE</a>; keep one course tag."""
    from urllib.parse import urljoin
    r = _session().get(url, timeout=TIMEOUT)
    r.raise_for_status()
    items, seen = [], set()
    for cls, block in re.findall(r'<div class="cssNLink (css\w+)">(.*?)</div>', r.text, re.S):
        if cls != tag:
            continue
        for href, inner in re.findall(r"<a\s+href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", block, re.S | re.I):
            raw = _text(inner)
            href = urljoin(r.url, _html.unescape(href).strip())
            if not raw or href in seen:
                continue
            seen.add(href)
            title, d = split_title_date(raw)
            m = _DMY_FILE_RE.search(href.rsplit('/', 1)[-1])
            if m:
                try: d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                except ValueError: pass
            items.append({'item_key': href, 'raw_title': raw, 'title': title, 'url': href,
                          'kind': _kind(href), 'notice_date': d})
    if not items:
        raise ValueError('No PG Medical notices found — the site layout may have changed.')
    return items


def read_date_table(pages, include=None, exclude=None):
    """Telangana KNRUHS style: table rows <td class="date-cell">dd-mm-yyyy</td><td>TITLE</td><td><a href=PDF>."""
    s, items, seen, rows = _session(), [], set(), 0
    for pg in pages:
        r = s.get(pg, timeout=TIMEOUT)
        r.raise_for_status()
        for dtxt, inner, href in re.findall(
                r'<td class="date-cell">\s*([\d./-]+)\s*</td>\s*<td>(.*?)</td>\s*<td>.*?href="([^"]+)"', r.text, re.S):
            rows += 1
            raw = _text(inner)
            href = _html.unescape(href).strip()
            if href in seen or not _wanted(raw, include, exclude):
                continue
            seen.add(href)
            _x, d = split_title_date(dtxt)
            items.append({'item_key': href, 'raw_title': raw, 'title': raw, 'url': href,
                          'kind': _kind(href), 'notice_date': d})
    if not rows:
        raise ValueError('No notices table found — the site layout may have changed.')
    return items


READERS = {'kea_aspnet': read_kea_aspnet, 'pdf_links': read_pdf_links}


def read_source(code):
    items = _read_source(code)
    have = {i['item_key'] for i in items}
    for fd in SOURCES[code].get('fixed_docs') or []:      # e.g. a brochure on another page
        if fd['url'] not in have:
            items.append({'item_key': fd['url'], 'raw_title': fd['title'], 'title': fd['title'],
                          'url': fd['url'], 'kind': 'pdf', 'notice_date': None})
    return items


def _read_source(code):
    src = SOURCES[code]
    if src['reader'] == 'pdf_links':
        return read_pdf_links(src['url'], src.get('pages'), src.get('include'), src.get('exclude'))
    if src['reader'] == 'cee_kerala':
        return read_cee_kerala(src.get('pages') or [src['url']], src.get('home'))
    if src['reader'] == 'tn_tagged':
        return read_tn_tagged(src['url'], src['tag'])
    from pg_admin import news_readers_states as _SR      # batch-3 state readers
    if src['reader'] in _SR.DISPATCH:
        return _SR.DISPATCH[src['reader']](src)
    if src['reader'] == 'aspnet_filter':
        return read_aspnet_filter(src['url'], src['form'], src.get('include'), src.get('exclude'))
    if src['reader'] == 'date_table':
        return read_date_table(src.get('pages') or [src['url']], src.get('include'), src.get('exclude'))
    return READERS[src['reader']](src['url'])


# ── running ──────────────────────────────────────────────────────────────────
def _lock_key(code):
    return 'pg_news_scrape:' + code


def run_source(code, trigger='schedule'):
    """Check one source; insert new notices. Returns {'ok','found','new','error','skipped'}."""
    src = SOURCES.get(code)
    out = {'source': code, 'ok': False, 'found': 0, 'new': 0, 'error': '', 'skipped': ''}
    if not src:
        out['error'] = 'unknown source'; return out
    conn = get_db()
    locked = False
    try:
        ensure_news_inbox_tables(conn)
        try:
            locked = bool(conn.execute("SELECT pg_try_advisory_lock(hashtext(?)) AS ok",
                                       (_lock_key(code),)).fetchone()['ok'])
        except Exception:
            conn.rollback(); locked = True          # non-Postgres (local) — no locking
        if not locked:
            out['skipped'] = 'another check is running'; return out
        if trigger == 'schedule':
            recent = conn.execute(
                "SELECT COUNT(*) AS n FROM pg_news_scrape_runs WHERE source_code = ? AND ok "
                f"AND ran_at > CURRENT_TIMESTAMP - INTERVAL '{RECENT_SKIP_MINUTES} minutes'",
                (code,)).fetchone()['n']
            if recent:
                out['skipped'] = 'checked recently'; return out
        try:
            items = read_source(code)
        except Exception as e:
            out['error'] = str(e)[:400]
            conn.execute("INSERT INTO pg_news_scrape_runs (source_code, ok, error, trigger) VALUES (?,?,?,?)",
                         (code, False, out['error'], trigger))
            conn.commit()
            logging.warning("news scrape %s failed: %s", code, e)
            return out
        new = 0
        for it in items:
            if conn.execute("SELECT 1 FROM pg_news_inbox WHERE source_code = ? AND item_key = ?",
                            (code, it['item_key'])).fetchone():
                continue                                    # already have this exact notice
            if is_repeat(conn, code, it):
                continue                                    # re-posted copy of an earlier notice
            row = conn.execute(
                "INSERT INTO pg_news_inbox (source_code, authority_code, item_key, title, raw_title, url, "
                "kind, notice_date) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT (source_code, item_key) DO NOTHING RETURNING id",
                (code, src['authority_code'], it['item_key'], it['title'][:500], it['raw_title'][:800],
                 it['url'][:1000], it['kind'], it['notice_date'])).fetchone()
            new += 1 if row else 0
        conn.execute("INSERT INTO pg_news_scrape_runs (source_code, ok, found, new_count, trigger) "
                     "VALUES (?,?,?,?,?)", (code, True, len(items), new, trigger))
        conn.commit()
        out.update(ok=True, found=len(items), new=new)
        if new:
            logging.info("news scrape %s: %d new notice(s)", code, new)
        return out
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        out['error'] = str(e)[:400]
        logging.error("run_source %s: %s", code, e)
        return out
    finally:
        if locked:
            try:
                conn.execute("SELECT pg_advisory_unlock(hashtext(?))", (_lock_key(code),))
                conn.commit()
            except Exception:
                pass
        conn.close()


def run_all(trigger='schedule'):
    return [run_source(c, trigger) for c, s in SOURCES.items() if s.get('enabled')]


def run_all_background(trigger='manual'):
    """'Check now' without holding the web request open (a slow govt site must never tie
    up / time out a web worker). Results show on the inbox page when done."""
    import threading
    threading.Thread(target=run_all, args=(trigger,), daemon=True, name='pg-news-scrape').start()


def start_scheduler():
    """10:00 AM, 1:00 PM, 6:30 PM, 11:00 PM IST. Safe to call in every process (see module doc).
    Off unless NEWS_SERVER_FETCH=1 — the Mac fetches today (sites block the server's IP)."""
    if (os.environ.get('NEWS_SERVER_FETCH') or '').strip() != '1':
        logging.info("PG news: server-side fetch off (Mac fetcher in use)")
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        sch = BackgroundScheduler()
        for jid, (h, m) in {'am': (10, 0), 'pm': (13, 0), 'eve': (18, 30), 'night': (23, 0)}.items():
            sch.add_job(run_all, CronTrigger(hour=h, minute=m, timezone=ist),
                        id=f'pg_news_scrape_{jid}', misfire_grace_time=1800, coalesce=True)
        sch.start()
        logging.info("PG news scraper scheduled (10:00, 13:00, 18:30, 23:00 IST)")
    except ImportError:
        logging.warning("APScheduler not installed — news scraper schedule disabled")
    except Exception as e:
        logging.error("news scraper schedule failed: %s", e)


# ── "Add to News" helper ─────────────────────────────────────────────────────
MAX_PDF_BYTES = 25 * 1024 * 1024


def fetch_pdf(url):
    """Download an official notice PDF → (bytes, filename) or (None, reason)."""
    import requests
    try:
        r = requests.get(url, timeout=(10, 60), headers={'User-Agent': UA}, stream=True, proxies=_proxies())
        r.raise_for_status()
        buf = bytearray()
        for chunk in r.iter_content(64 * 1024):
            buf.extend(chunk)
            if len(buf) > MAX_PDF_BYTES:
                return None, 'PDF is larger than 25 MB'
        data = bytes(buf)
        if not data.startswith(b'%PDF'):
            return None, 'the link did not return a PDF'
        name = (url.split('?')[0].rstrip('/').rsplit('/', 1)[-1] or 'notice.pdf')[:200]
        return data, (name if name.lower().endswith('.pdf') else name + '.pdf')
    except Exception as e:
        if 'SSL' in type(e).__name__ or 'SSL' in str(e):
            return _fetch_pdf_curl(url)           # e.g. TLS-1.3-only govt hosts vs the Mac's old LibreSSL
        return None, str(e)[:200]


def _fetch_pdf_curl(url):
    import subprocess
    try:
        out = subprocess.run(['curl', '-sL', '-A', UA, '-m', '90', '--max-filesize', str(MAX_PDF_BYTES), url],
                             capture_output=True, timeout=120)
        data = out.stdout
        if not data.startswith(b'%PDF'):
            return None, 'the link did not return a PDF'
        name = (url.split('?')[0].rstrip('/').rsplit('/', 1)[-1] or 'notice.pdf')[:200]
        return data, (name if name.lower().endswith('.pdf') else name + '.pdf')
    except Exception as e:
        return None, str(e)[:200]
