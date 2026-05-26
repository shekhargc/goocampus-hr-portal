"""
Generate Germany PG Brochure PDF — GooCampus branded, A4 pages.
Cover with Germany image, Why Germany, Journey, Package (elaborated), Checklist.
"""
import os
from weasyprint import HTML

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), 'static', 'docs', 'germany-pg-brochure.pdf')

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');

@page {
  size: A4;
  margin: 0;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
  color: #1C1C1C;
  line-height: 1.55;
  font-size: 10pt;
}

:root {
  --navy: #0B1F3A;
  --gold: #C4922A;
  --gold-light: #f0c96c;
  --gold-pale: #fef5e3;
  --cream: #FAF8F4;
  --white: #fff;
  --green: #1a6b3a;
  --red: #C41230;
  --text: #1C1C1C;
  --muted: #5A5A5A;
  --border: #E0DBD4;
}

.de-bar {
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 5px;
  background: linear-gradient(90deg, #000 33%, #DD0000 33%, #DD0000 66%, #FFCC00 66%);
}
.de-bar-bottom {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 5px;
  background: linear-gradient(90deg, #000 33%, #DD0000 33%, #DD0000 66%, #FFCC00 66%);
}

.page {
  width: 210mm;
  height: 297mm;
  position: relative;
  overflow: hidden;
  page-break-after: always;
}
.page:last-child { page-break-after: auto; }

.page-bar {
  position: absolute;
  top: 5px; left: 0; right: 0;
  height: 44px;
  background: var(--navy);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
}
.page-bar .logo { font-size: 12pt; font-weight: 800; color: #fff; }
.page-bar .logo span { color: var(--gold-light); }
.page-bar .tag { font-size: 7pt; font-weight: 600; color: rgba(255,255,255,.45); text-transform: uppercase; letter-spacing: 1.5px; }

.body { padding: 60px 28px 28px; }

/* ═══ PAGE 1: COVER ═══ */
.cover {
  background: var(--white);
  display: flex;
  flex-direction: column;
}
.cover-top {
  text-align: center;
  padding: 40px 32px 24px;
  flex-shrink: 0;
}
.cover-logo {
  font-size: 15pt;
  font-weight: 900;
  color: var(--navy);
  margin-bottom: 18px;
}
.cover-logo span { color: var(--gold); }
.cover-logo-sub {
  font-size: 7pt;
  font-weight: 600;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: var(--muted);
  margin-top: 2px;
}
.cover-country {
  font-size: 48pt;
  font-weight: 900;
  color: var(--navy);
  letter-spacing: -0.03em;
  line-height: 1;
  margin-bottom: 6px;
}
.cover-program {
  font-size: 18pt;
  font-weight: 800;
  color: var(--navy);
  line-height: 1.2;
  margin-bottom: 6px;
}
.cover-badge {
  display: inline-block;
  font-size: 9pt;
  font-weight: 800;
  color: var(--white);
  background: var(--navy);
  border-radius: 8px;
  padding: 8px 24px;
  margin-top: 14px;
  letter-spacing: 1px;
}
.cover-img {
  flex: 1;
  overflow: hidden;
  position: relative;
}
.cover-img img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.cover-img::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 60px;
  background: linear-gradient(180deg, var(--white), transparent);
  z-index: 1;
}

/* ═══ SECTION STYLES ═══ */
.sec-label { font-size: 7pt; font-weight: 700; letter-spacing: 2.5px; text-transform: uppercase; color: var(--gold); margin-bottom: 5px; }
.sec-title { font-size: 17pt; font-weight: 800; color: var(--navy); margin-bottom: 6px; letter-spacing: -0.01em; }
.sec-sub { font-size: 9pt; color: var(--muted); margin-bottom: 18px; line-height: 1.5; }

/* WHY GERMANY */
.why-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}
.why-card {
  width: calc(50% - 5px);
  background: var(--cream);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 14px;
  position: relative;
  overflow: hidden;
}
.why-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0;
  width: 4px; height: 100%;
}
.why-card:nth-child(1)::before { background: #FFCC00; }
.why-card:nth-child(2)::before { background: #DD0000; }
.why-card:nth-child(3)::before { background: #2e7d32; }
.why-card:nth-child(4)::before { background: #1565c0; }
.why-card:nth-child(5)::before { background: #e65100; }
.why-card:nth-child(6)::before { background: #7b1fa2; }
.why-card h4 { font-size: 9.5pt; font-weight: 700; color: var(--navy); margin-bottom: 4px; }
.why-card p { font-size: 8pt; color: var(--muted); line-height: 1.45; }

.salary-box {
  background: var(--navy);
  border-radius: 10px;
  padding: 18px 22px;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
}
.salary-box .s-left h4 { font-size: 10pt; font-weight: 700; margin-bottom: 3px; }
.salary-box .s-left p { font-size: 7.5pt; color: rgba(255,255,255,.5); }
.salary-box .s-right { text-align: center; }
.salary-box .s-amt { font-size: 22pt; font-weight: 900; color: var(--gold-light); }
.salary-box .s-per { font-size: 7pt; color: rgba(255,255,255,.4); }

/* JOURNEY */
.journey-steps { margin-top: 10px; }
.j-step {
  display: flex;
  gap: 14px;
  margin-bottom: 12px;
  align-items: flex-start;
}
.j-num {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  font-size: 12pt;
  color: #fff;
  flex-shrink: 0;
}
.j-step:nth-child(1) .j-num { background: #FF9933; }
.j-step:nth-child(2) .j-num { background: #e53935; }
.j-step:nth-child(3) .j-num { background: #1565c0; }
.j-step:nth-child(4) .j-num { background: #2e7d32; }
.j-step:nth-child(5) .j-num { background: #7b1fa2; }
.j-step:nth-child(6) .j-num { background: #e65100; }
.j-step:nth-child(7) .j-num { background: var(--gold); }
.j-content { flex: 1; }
.j-content h4 { font-size: 10pt; font-weight: 700; color: var(--navy); margin-bottom: 2px; }
.j-content .j-dur { font-size: 7pt; color: var(--gold); font-weight: 600; text-transform: uppercase; letter-spacing: .5px; }
.j-content p { font-size: 8pt; color: var(--muted); margin-top: 3px; line-height: 1.45; }

/* PACKAGE */
.pkg-header {
  background: var(--navy);
  border-radius: 12px;
  padding: 20px 24px;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.pkg-header .left h3 { font-size: 12pt; font-weight: 800; }
.pkg-header .left p { font-size: 8pt; color: rgba(255,255,255,.5); margin-top: 2px; }
.pkg-header .right .amt { font-size: 28pt; font-weight: 900; text-align: right; }
.pkg-header .right .sub { font-size: 7.5pt; color: var(--gold-light); text-align: right; }

/* Installment cards */
.inst-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 10px;
  position: relative;
  overflow: hidden;
  background: var(--white);
}
.inst-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
}
.inst-card.i1::before { background: #FF9933; }
.inst-card.i2::before { background: #1565c0; }
.inst-card.i3::before { background: #2e7d32; }
.inst-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}
.inst-top .i-label { font-size: 8pt; font-weight: 700; text-transform: uppercase; letter-spacing: .8px; }
.inst-card.i1 .i-label { color: #e65100; }
.inst-card.i2 .i-label { color: #1565c0; }
.inst-card.i3 .i-label { color: #2e7d32; }
.inst-top .i-amt { font-size: 16pt; font-weight: 900; color: var(--navy); }
.inst-top .i-when { font-size: 7pt; color: var(--muted); font-style: italic; }
.inst-title { font-size: 9pt; font-weight: 700; color: var(--navy); margin-bottom: 6px; }
.inst-services {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 0;
}
.inst-services li {
  width: 50%;
  padding: 1.5px 0 1.5px 14px;
  font-size: 7.5pt;
  color: var(--text);
  position: relative;
  line-height: 1.4;
  list-style: none;
}
.inst-services li::before { content: '\\2713'; position: absolute; left: 0; color: var(--gold); font-weight: 800; font-size: 7pt; }

/* Payment table */
.pay-table {
  width: 100%;
  border-collapse: collapse;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  margin: 14px 0 12px;
}
.pay-table th {
  background: var(--navy);
  color: #fff;
  font-size: 7.5pt;
  font-weight: 600;
  padding: 8px 12px;
  text-align: left;
}
.pay-table td {
  padding: 7px 12px;
  font-size: 8pt;
  border-bottom: 1px solid var(--border);
}
.pay-table tr:last-child td { border-bottom: none; font-weight: 700; }
.pay-table tr:nth-child(even) td { background: rgba(250,248,244,.5); }

/* CHECKLIST */
.chk-grid { display: flex; gap: 14px; }
.chk-col {
  flex: 1;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
  position: relative;
  overflow: hidden;
  background: var(--cream);
}
.chk-col::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
}
.chk-col.inc::before { background: linear-gradient(90deg, #1a6b3a, #66bb6a); }
.chk-col.exc::before { background: linear-gradient(90deg, #C41230, #ef5350); }
.chk-col h3 { font-size: 9.5pt; font-weight: 800; margin-bottom: 8px; }
.chk-col.inc h3 { color: var(--green); }
.chk-col.exc h3 { color: var(--red); }
.chk-list { list-style: none; padding: 0; margin: 0; }
.chk-list li { padding: 2.5px 0 2.5px 14px; font-size: 7.5pt; color: var(--text); position: relative; line-height: 1.45; border-bottom: 1px solid rgba(0,0,0,.03); }
.chk-list li:last-child { border-bottom: none; }
.chk-list li::before { position: absolute; left: 0; font-weight: 800; font-size: 7.5pt; }
.inc .chk-list li::before { content: '\\2713'; color: var(--green); }
.exc .chk-list li::before { content: '\\2717'; color: var(--red); }

.blocked-note {
  margin-top: 12px;
  padding: 10px 14px;
  background: var(--gold-pale);
  border: 1px solid rgba(196,146,42,.25);
  border-radius: 8px;
}
.blocked-note p { font-size: 7.5pt; color: var(--muted); line-height: 1.5; }
.blocked-note strong { color: var(--navy); }

/* Contact box */
.contact-box {
  background: var(--navy);
  border-radius: 12px;
  padding: 22px 28px;
  color: #fff;
  text-align: center;
  position: relative;
  overflow: hidden;
  margin-top: 16px;
}
.contact-box::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: linear-gradient(90deg, #000 33%, #DD0000 33%, #DD0000 66%, #FFCC00 66%);
}
.contact-box h3 { font-size: 14pt; font-weight: 800; margin-bottom: 4px; }
.contact-box .csub { font-size: 8.5pt; color: rgba(255,255,255,.45); margin-bottom: 14px; }
.contact-row { display: flex; justify-content: center; gap: 36px; }
.contact-item { text-align: center; }
.contact-item .cl { font-size: 6.5pt; color: rgba(255,255,255,.35); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 2px; }
.contact-item .cv { font-size: 9.5pt; font-weight: 700; color: var(--gold-light); }

/* PAGE FOOTER */
.pf {
  position: absolute;
  bottom: 10px;
  left: 28px; right: 28px;
  text-align: center;
  font-size: 6.5pt;
  color: rgba(0,0,0,.18);
  border-top: 1px solid var(--border);
  padding-top: 5px;
}
</style>
</head>
<body>

<!-- ═══ PAGE 1: COVER ═══ -->
<div class="page cover">
  <div class="de-bar"></div>
  <div class="de-bar-bottom"></div>
  <div class="cover-top">
    <div class="cover-logo">Goo<span>Campus</span>
      <div class="cover-logo-sub">Your Gateway to Global Medical Careers</div>
    </div>
    <div class="cover-country">GERMANY</div>
    <div class="cover-program">Post-Graduate<br>Career Pathway</div>
    <div class="cover-badge">GERMANY &mdash; PGCP</div>
  </div>
  <div class="cover-img">
    <img src="https://images.unsplash.com/photo-1467269204594-9661b134dd2b?w=1200&q=85" alt="Germany cityscape">
  </div>
</div>

<!-- ═══ PAGE 2: WHY GERMANY ═══ -->
<div class="page">
  <div class="de-bar"></div>
  <div class="page-bar"><div class="logo">Goo<span>Campus</span></div><div class="tag">Germany PG Career Pathway</div></div>
  <div class="body">
    <div class="sec-label">Why Germany?</div>
    <div class="sec-title">The Best Destination for Indian Medical Graduates</div>
    <p class="sec-sub">Germany offers Indian MBBS graduates a clear, structured pathway to practice medicine in one of the world's most advanced healthcare systems.</p>

    <div class="why-grid">
      <div class="why-card">
        <h4>Zero Tuition Fees</h4>
        <p>Medical PG training in Germany has no tuition fees. You train as a paid Assistenzarzt (resident doctor) in German hospitals from day one.</p>
      </div>
      <div class="why-card">
        <h4>Earn While You Train</h4>
        <p>Assistenzarzt salary ranges from &euro;4,500 to &euro;5,500 per month. Your investment is recovered within 3&ndash;4 months of starting work.</p>
      </div>
      <div class="why-card">
        <h4>World-Class Healthcare</h4>
        <p>Germany's healthcare system ranks among the top globally. You'll train with advanced equipment in modern hospitals and university clinics.</p>
      </div>
      <div class="why-card">
        <h4>Permanent Residency</h4>
        <p>EU Blue Card route offers PR eligibility in just 21 months. Germany actively recruits international doctors to fill its shortage of 20,000+ physicians.</p>
      </div>
      <div class="why-card">
        <h4>Globally Recognized Degree</h4>
        <p>German Facharzt (specialist) qualification is recognized worldwide. After completing your training, you can practice in any EU country.</p>
      </div>
      <div class="why-card">
        <h4>Structured Pathway</h4>
        <p>Clear step-by-step process: Language &rarr; Defizitbescheid &rarr; Visa &rarr; FSP Exam &rarr; Approbation &rarr; Assistenzarzt position &rarr; Facharzt.</p>
      </div>
    </div>

    <div class="salary-box">
      <div class="s-left">
        <h4>Assistenzarzt Salary in Germany</h4>
        <p>Net take-home after taxes, with annual increments</p>
      </div>
      <div class="s-right">
        <div class="s-amt">&euro;4,500 &ndash; &euro;5,500</div>
        <div class="s-per">per month</div>
      </div>
    </div>
  </div>
  <div class="pf">GooCampus Germany PGCP &bull; Why Germany &bull; Page 2</div>
</div>

<!-- ═══ PAGE 3: PATHWAY / JOURNEY ═══ -->
<div class="page">
  <div class="de-bar"></div>
  <div class="page-bar"><div class="logo">Goo<span>Campus</span></div><div class="tag">Germany PG Career Pathway</div></div>
  <div class="body">
    <div class="sec-label">Your Journey</div>
    <div class="sec-title">Step-by-Step Pathway to Medical PG in Germany</div>
    <p class="sec-sub">From your first German class in India to your Assistenzarzt position and permanent residency in Germany.</p>

    <div class="journey-steps">
      <div class="j-step">
        <div class="j-num">1</div>
        <div class="j-content">
          <h4>German Language Training (A1 &ndash; B1)</h4>
          <div class="j-dur">6&ndash;12 months &bull; India (Online)</div>
          <p>Start learning German from scratch. Our structured programme takes you from A1 to B1 level, covering both general and medical vocabulary essential for the FSP exam and clinical practice.</p>
        </div>
      </div>
      <div class="j-step">
        <div class="j-num">2</div>
        <div class="j-content">
          <h4>Document Preparation &amp; Translation</h4>
          <div class="j-dur">Parallel with language training</div>
          <p>Complete document compilation including degree certificates, transcripts, internship completion, certified German translation, Letter of Recommendation, and motivation letter.</p>
        </div>
      </div>
      <div class="j-step">
        <div class="j-num">3</div>
        <div class="j-content">
          <h4>Defizitbescheid (Deficit Letter) Application</h4>
          <div class="j-dur">3&ndash;6 months processing</div>
          <p>Apply for the deficit letter from German medical authority (Landespr&uuml;fungsamt). This confirms which exams you need to pass for your German medical license.</p>
        </div>
      </div>
      <div class="j-step">
        <div class="j-num">4</div>
        <div class="j-content">
          <h4>D16 Visa &amp; Travel to Germany</h4>
          <div class="j-dur">2&ndash;3 months</div>
          <p>Complete visa documentation, open blocked account (Sperrkonto), arrange travel insurance, book visa appointment at German Embassy, and travel to Germany.</p>
        </div>
      </div>
      <div class="j-step">
        <div class="j-num">5</div>
        <div class="j-content">
          <h4>B2/C1 Medical German &amp; FSP Exam</h4>
          <div class="j-dur">6&ndash;12 months &bull; Germany</div>
          <p>Advanced medical German training in Germany. Prepare for and pass the Fachsprachpr&uuml;fung (FSP) &mdash; the medical language exam required for your temporary license.</p>
        </div>
      </div>
      <div class="j-step">
        <div class="j-num">6</div>
        <div class="j-content">
          <h4>Approbation &amp; Observership</h4>
          <div class="j-dur">3&ndash;6 months &bull; Germany</div>
          <p>Pass the Kenntnispr&uuml;fung (knowledge exam) for full Approbation. Complete 2&ndash;3 month observership at a private clinic for hands-on clinical exposure.</p>
        </div>
      </div>
      <div class="j-step">
        <div class="j-num">7</div>
        <div class="j-content">
          <h4>Assistenzarzt Position &amp; PR</h4>
          <div class="j-dur">Ongoing &bull; Germany</div>
          <p>Start as Assistenzarzt (&euro;4,500&ndash;&euro;5,500/month). Apply for EU Blue Card. Eligible for Permanent Residency within 21 months via fast-track Blue Card route.</p>
        </div>
      </div>
    </div>
  </div>
  <div class="pf">GooCampus Germany PGCP &bull; Journey Map &bull; Page 3</div>
</div>

<!-- ═══ PAGE 4: PACKAGE & PAYMENT DETAILS (ELABORATED) ═══ -->
<div class="page">
  <div class="de-bar"></div>
  <div class="page-bar"><div class="logo">Goo<span>Campus</span></div><div class="tag">Germany PG Career Pathway</div></div>
  <div class="body">
    <div class="sec-label">Programme Fee</div>
    <div class="sec-title">Package &amp; Payment Structure</div>
    <p class="sec-sub">Three milestone-based installments. Each payment unlocks the next phase of services. No hidden charges.</p>

    <div class="pkg-header">
      <div class="left">
        <h3>Total Programme Fee</h3>
        <p>3 milestone-based installments &bull; Pay as you progress</p>
      </div>
      <div class="right">
        <div class="amt">&euro;15,000</div>
        <div class="sub">Approx. &#8377;13.5 Lakhs at current rates</div>
      </div>
    </div>

    <!-- Installment 1 -->
    <div class="inst-card i1">
      <div class="inst-top">
        <div>
          <div class="i-label">Installment 1 &mdash; India Phase</div>
          <div class="i-when">Paid at enrolment &bull; Before language training begins</div>
        </div>
        <div class="i-amt">&euro;5,000</div>
      </div>
      <div class="inst-title">Services Covered:</div>
      <ul class="inst-services">
        <li>German language training A1 to B1</li>
        <li>Dedicated counsellor assignment</li>
        <li>Complete document preparation</li>
        <li>Certified German translation</li>
        <li>Letter of Recommendation drafting</li>
        <li>Motivation letter preparation</li>
        <li>Contract &amp; agreement signing</li>
        <li>Ongoing progress monitoring</li>
      </ul>
    </div>

    <!-- Installment 2 -->
    <div class="inst-card i2">
      <div class="inst-top">
        <div>
          <div class="i-label">Installment 2 &mdash; Visa Phase</div>
          <div class="i-when">After Phase 1 completion &bull; Before visa application</div>
        </div>
        <div class="i-amt">&euro;5,000</div>
      </div>
      <div class="inst-title">Services Covered:</div>
      <ul class="inst-services">
        <li>Defizitbescheid application</li>
        <li>Document attestation</li>
        <li>Visa documentation &amp; file prep</li>
        <li>D16 visa fee (included)</li>
        <li>Visa appointment booking</li>
        <li>Visa interview preparation</li>
        <li>Blocked account guidance</li>
        <li>Travel &amp; health insurance assistance</li>
      </ul>
    </div>

    <!-- Installment 3 -->
    <div class="inst-card i3">
      <div class="inst-top">
        <div>
          <div class="i-label">Installment 3 &mdash; Germany Phase</div>
          <div class="i-when">After visa received &bull; Before arrival in Germany</div>
        </div>
        <div class="i-amt">&euro;5,000</div>
      </div>
      <div class="inst-title">Services Covered:</div>
      <ul class="inst-services">
        <li>B2 &amp; C1 medical German</li>
        <li>Airport pickup on arrival</li>
        <li>Initial accommodation assistance</li>
        <li>City registration (Anmeldung)</li>
        <li>German bank account opening</li>
        <li>FSP exam training &amp; booking</li>
        <li>Approbation / KP exam guidance</li>
        <li>Observership (2&ndash;3 months)</li>
        <li>Health insurance setup</li>
        <li>Job guidance after license</li>
        <li>Visa extension support</li>
        <li>PR (Permanent Residency) guidance</li>
      </ul>
    </div>

  </div>
  <div class="pf">GooCampus Germany PGCP &bull; Package Details &bull; Page 4</div>
</div>

<!-- ═══ PAGE 5: PAYMENT TABLE + FINANCIAL NOTES + CHECKLIST + CONTACT ═══ -->
<div class="page" style="page-break-after:auto">
  <div class="de-bar"></div>
  <div class="page-bar"><div class="logo">Goo<span>Campus</span></div><div class="tag">Germany PG Career Pathway</div></div>
  <div class="body">
    <div class="sec-label">Costing &amp; Installments</div>
    <div class="sec-title">Payment Summary &amp; Important Notes</div>

    <table class="pay-table">
      <thead>
        <tr>
          <th style="width:30%">Particulars</th>
          <th style="width:20%">Fee (EUR)</th>
          <th style="width:25%">Approx. INR</th>
          <th style="width:25%">When to Pay</th>
        </tr>
      </thead>
      <tbody>
        <tr><td>Installment 1 &mdash; India Phase</td><td>&euro;5,000</td><td>&#8377;4,50,000</td><td>At enrolment</td></tr>
        <tr><td>Installment 2 &mdash; Visa Phase</td><td>&euro;5,000</td><td>&#8377;4,50,000</td><td>After Phase 1</td></tr>
        <tr><td>Installment 3 &mdash; Germany Phase</td><td>&euro;5,000</td><td>&#8377;4,50,000</td><td>After visa received</td></tr>
        <tr><td><strong>Total Programme Fee</strong></td><td><strong>&euro;15,000</strong></td><td><strong>&#8377;13,50,000</strong></td><td></td></tr>
      </tbody>
    </table>

    <div style="background:#fff3e0;border:1px solid #ffcc80;border-radius:8px;padding:12px 14px;margin-bottom: 14px">
      <h4 style="font-size:8.5pt;font-weight:700;color:#e65100;margin-bottom:6px">Important Financial Notes</h4>
      <ul style="list-style:none;padding:0;margin:0">
        <li style="padding:3px 0 3px 14px;font-size:7.8pt;position:relative;line-height:1.5"><span style="position:absolute;left:0;color:#e65100;font-weight:700">&bull;</span><strong>D16 visa fee IS included</strong> in Installment 2 &mdash; no separate visa fee to pay</li>
        <li style="padding:3px 0 3px 14px;font-size:7.8pt;position:relative;line-height:1.5"><span style="position:absolute;left:0;color:#e65100;font-weight:700">&bull;</span><strong>Blocked account (~&euro;13K&ndash;&euro;14K)</strong> is YOUR money deposited in a German bank for living expenses &mdash; you withdraw ~&euro;1K&ndash;&euro;1.5K/month. It is NOT a fee paid to GooCampus</li>
        <li style="padding:3px 0 3px 14px;font-size:7.8pt;position:relative;line-height:1.5"><span style="position:absolute;left:0;color:#e65100;font-weight:700">&bull;</span><strong>Exam fees</strong> for FSP, Kenntnispr&uuml;fung, and language exams (Goethe/Telc) are paid directly to German authorities &mdash; not included in programme fee</li>
        <li style="padding:3px 0 3px 14px;font-size:7.8pt;position:relative;line-height:1.5"><span style="position:absolute;left:0;color:#e65100;font-weight:700">&bull;</span><strong>Flight tickets, accommodation</strong> (after initial setup), personal expenses, and medical council fees are the candidate's responsibility</li>
        <li style="padding:3px 0 3px 14px;font-size:7.8pt;position:relative;line-height:1.5"><span style="position:absolute;left:0;color:#e65100;font-weight:700">&bull;</span><strong>INR amounts are approximate</strong> based on current exchange rates and may vary at time of payment</li>
        <li style="padding:3px 0 3px 14px;font-size:7.8pt;position:relative;line-height:1.5"><span style="position:absolute;left:0;color:#e65100;font-weight:700">&bull;</span>Fee is <strong>recoverable within 3&ndash;4 months</strong> of starting your Assistenzarzt position (&euro;4,500&ndash;&euro;5,500/month salary)</li>
      </ul>
    </div>

    <div style="background:var(--cream);border:1px solid var(--border);border-radius:8px;padding:12px 14px;margin-bottom:14px">
      <h4 style="font-size:8.5pt;font-weight:700;color:var(--navy);margin-bottom:4px">Additional Costs (Not Included &mdash; Paid by Candidate)</h4>
      <div style="display:flex;flex-wrap:wrap;gap:0">
        <div style="width:50%;padding:2px 0;font-size:7.5pt;color:var(--text)">&#10007; Flight tickets (India to Germany)</div>
        <div style="width:50%;padding:2px 0;font-size:7.5pt;color:var(--text)">&#10007; Blocked account deposit (~&euro;13K&ndash;&euro;14K)</div>
        <div style="width:50%;padding:2px 0;font-size:7.5pt;color:var(--text)">&#10007; Accommodation (after initial setup)</div>
        <div style="width:50%;padding:2px 0;font-size:7.5pt;color:var(--text)">&#10007; Living expenses (~&euro;1K&ndash;&euro;1.5K/month)</div>
        <div style="width:50%;padding:2px 0;font-size:7.5pt;color:var(--text)">&#10007; FSP / KP exam fees</div>
        <div style="width:50%;padding:2px 0;font-size:7.5pt;color:var(--text)">&#10007; Language exam fees (Goethe/Telc)</div>
        <div style="width:50%;padding:2px 0;font-size:7.5pt;color:var(--text)">&#10007; Employment visa (after 1 year)</div>
        <div style="width:50%;padding:2px 0;font-size:7.5pt;color:var(--text)">&#10007; Medical council &amp; notarization fees</div>
      </div>
    </div>

    <div class="contact-box">
      <h3>Ready to Start Your Germany Journey?</h3>
      <p class="csub">Book a free counselling session with our Germany pathway experts</p>
      <div class="contact-row">
        <div class="contact-item"><div class="cl">Website</div><div class="cv">goocampus.org/germanypathway</div></div>
        <div class="contact-item"><div class="cl">WhatsApp</div><div class="cv">+91 636 314 1075</div></div>
        <div class="contact-item"><div class="cl">Email</div><div class="cv">info@goocampus.in</div></div>
      </div>
    </div>
  </div>
  <div class="pf">GooCampus Germany PGCP &bull; &copy; 2025 GooCampus. All rights reserved. &bull; Page 5</div>
</div>

</body>
</html>
"""

if __name__ == '__main__':
    print("Generating Germany PG Brochure PDF...")
    html = HTML(string=HTML_CONTENT)
    html.write_pdf(OUTPUT_PATH)
    size = os.path.getsize(OUTPUT_PATH)
    print(f"Brochure saved to: {OUTPUT_PATH}")
    print(f"File size: {size:,} bytes ({size/1024:.1f} KB)")
