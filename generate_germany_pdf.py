"""
Generate Germany Pathway Package PDF using WeasyPrint.
Branded PDF with full package details, checklist, and comparison table.
"""
import os
from weasyprint import HTML

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), 'static', 'docs', 'germany-pathway-package.pdf')

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

body {
  font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
  color: var(--text);
  line-height: 1.55;
  font-size: 9.5pt;
}

/* ── PAGE 1: COVER ── */
.cover {
  width: 210mm;
  height: 297mm;
  background: var(--navy);
  color: #fff;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  position: relative;
  overflow: hidden;
  page-break-after: always;
}
.cover::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 6px;
  background: linear-gradient(90deg, #000 33%, #DD0000 33%, #DD0000 66%, #FFCC00 66%);
}
.cover::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 6px;
  background: linear-gradient(90deg, #000 33%, #DD0000 33%, #DD0000 66%, #FFCC00 66%);
}
.cover-badge {
  font-size: 8pt;
  font-weight: 700;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: var(--gold);
  margin-bottom: 16px;
}
.cover h1 {
  font-size: 28pt;
  font-weight: 900;
  line-height: 1.15;
  letter-spacing: -0.02em;
  margin-bottom: 10px;
  max-width: 420px;
}
.cover h1 span { color: var(--gold-light); }
.cover-sub {
  font-size: 11pt;
  color: rgba(255,255,255,.55);
  max-width: 380px;
  margin-bottom: 36px;
  line-height: 1.6;
}
.cover-price {
  background: rgba(255,255,255,.08);
  border: 1.5px solid rgba(196,146,42,.35);
  border-radius: 14px;
  padding: 24px 44px;
  margin-bottom: 36px;
}
.cover-price .label {
  font-size: 7.5pt;
  font-weight: 600;
  color: rgba(255,255,255,.4);
  text-transform: uppercase;
  letter-spacing: 1.5px;
}
.cover-price .amt {
  font-size: 36pt;
  font-weight: 900;
  line-height: 1;
  margin-top: 4px;
}
.cover-price .sub {
  font-size: 9pt;
  color: rgba(255,255,255,.45);
  margin-top: 6px;
}
.cover-price .inr {
  font-size: 8.5pt;
  color: var(--gold-light);
  font-weight: 600;
  margin-top: 4px;
}
.cover-footer {
  position: absolute;
  bottom: 28px;
  font-size: 7.5pt;
  color: rgba(255,255,255,.25);
}
.cover-logo {
  font-size: 14pt;
  font-weight: 800;
  color: #fff;
  margin-bottom: 6px;
}
.cover-logo span { color: var(--gold-light); }

/* ── COMMON PAGE STYLES ── */
.page {
  width: 210mm;
  min-height: 297mm;
  padding: 22mm 20mm 18mm;
  background: var(--white);
  position: relative;
  page-break-after: always;
}
.page::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 4px;
  background: linear-gradient(90deg, #000 33%, #DD0000 33%, #DD0000 66%, #FFCC00 66%);
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 18px;
  padding-bottom: 10px;
  border-bottom: 1.5px solid var(--border);
}
.page-header .brand {
  font-size: 9pt;
  font-weight: 700;
  color: var(--navy);
}
.page-header .brand span { color: var(--gold); }
.page-header .page-title {
  font-size: 7.5pt;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 1.5px;
}

.section-label {
  font-size: 7pt;
  font-weight: 700;
  letter-spacing: 2.5px;
  text-transform: uppercase;
  color: var(--gold);
  margin-bottom: 5px;
}
.section-title {
  font-size: 15pt;
  font-weight: 800;
  color: var(--navy);
  margin-bottom: 5px;
  letter-spacing: -0.01em;
}
.section-sub {
  font-size: 8.5pt;
  color: var(--muted);
  margin-bottom: 16px;
  line-height: 1.5;
}

/* ── INSTALLMENT CARDS ── */
.inst-grid {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.inst-card {
  flex: 1;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 12px;
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
.inst-card.i1::before { background: linear-gradient(90deg, #FF9933, #ffb366); }
.inst-card.i2::before { background: linear-gradient(90deg, #1565c0, #42a5f5); }
.inst-card.i3::before { background: linear-gradient(90deg, #2e7d32, #66bb6a); }
.inst-num {
  font-size: 7pt;
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
  margin-bottom: 3px;
}
.inst-card.i1 .inst-num { color: #e65100; }
.inst-card.i2 .inst-num { color: #1565c0; }
.inst-card.i3 .inst-num { color: #2e7d32; }
.inst-amt {
  font-size: 16pt;
  font-weight: 900;
  color: var(--navy);
  margin-bottom: 1px;
}
.inst-when {
  font-size: 7pt;
  color: var(--muted);
  font-style: italic;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}
.inst-title {
  font-size: 8pt;
  font-weight: 700;
  color: var(--navy);
  margin-bottom: 6px;
}
.inst-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.inst-list li {
  position: relative;
  padding: 2.5px 0 2.5px 14px;
  font-size: 7.2pt;
  color: var(--text);
  line-height: 1.45;
}
.inst-list li::before {
  content: '\\2713';
  position: absolute;
  left: 0;
  color: var(--gold);
  font-weight: 800;
  font-size: 7pt;
}

/* ── CHECKLIST ── */
.check-grid {
  display: flex;
  gap: 16px;
  margin-bottom: 14px;
}
.check-col {
  flex: 1;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
  position: relative;
  overflow: hidden;
  background: var(--cream);
}
.check-col::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
}
.check-col.included::before { background: linear-gradient(90deg, #1a6b3a, #66bb6a); }
.check-col.not-included::before { background: linear-gradient(90deg, #C41230, #ef5350); }
.check-col h3 {
  font-size: 9pt;
  font-weight: 800;
  margin-bottom: 8px;
}
.check-col.included h3 { color: var(--green); }
.check-col.not-included h3 { color: var(--red); }
.check-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.check-list li {
  position: relative;
  padding: 2.5px 0 2.5px 15px;
  font-size: 7.5pt;
  color: var(--text);
  line-height: 1.5;
  border-bottom: 1px solid rgba(0,0,0,.03);
}
.check-list li:last-child { border-bottom: none; }
.check-list li::before {
  position: absolute;
  left: 0;
  font-weight: 800;
  font-size: 8pt;
}
.included .check-list li::before { content: '\\2713'; color: var(--green); }
.not-included .check-list li::before { content: '\\2717'; color: var(--red); }

/* ── SERVICES PHASE ── */
.svc-phase {
  margin-bottom: 16px;
}
.svc-phase-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.svc-phase-num {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  font-size: 10pt;
  color: #fff;
  flex-shrink: 0;
}
.svc-phase.p1 .svc-phase-num { background: linear-gradient(135deg, #FF9933, #ffb366); }
.svc-phase.p2 .svc-phase-num { background: linear-gradient(135deg, #1565c0, #42a5f5); }
.svc-phase.p3 .svc-phase-num { background: linear-gradient(135deg, #2e7d32, #66bb6a); }
.svc-phase-title {
  font-size: 10pt;
  font-weight: 700;
  color: var(--navy);
}
.svc-phase-sub {
  font-size: 7pt;
  color: var(--muted);
  margin-top: 1px;
}
.svc-items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.svc-item {
  width: calc(50% - 3px);
  background: var(--white);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 7px 8px;
  display: flex;
  align-items: flex-start;
  gap: 6px;
}
.svc-item .s-ico {
  font-size: 11pt;
  flex-shrink: 0;
  margin-top: 1px;
}
.svc-item .s-text {
  font-size: 7.2pt;
  color: var(--text);
  line-height: 1.4;
}
.svc-item .s-text strong {
  color: var(--navy);
  font-weight: 600;
}

/* ── NOTE BOX ── */
.note-box {
  background: #fff3e0;
  border: 1px solid #ffcc80;
  border-radius: 8px;
  padding: 12px 14px;
  margin: 12px 0;
}
.note-box h3 {
  font-size: 8.5pt;
  font-weight: 700;
  color: #e65100;
  margin-bottom: 6px;
}
.note-box ul {
  list-style: none;
  padding: 0;
  margin: 0;
}
.note-box li {
  padding: 2px 0 2px 12px;
  font-size: 7.2pt;
  color: var(--text);
  position: relative;
  line-height: 1.45;
}
.note-box li::before {
  content: '\\2022';
  position: absolute;
  left: 0;
  color: #e65100;
  font-weight: 700;
}

/* ── COMPARISON TABLE ── */
.compare-table {
  width: 100%;
  border-collapse: collapse;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--border);
  margin-top: 12px;
}
.compare-table th {
  background: var(--navy);
  color: #fff;
  font-size: 7.5pt;
  font-weight: 600;
  padding: 8px 10px;
  text-align: left;
}
.compare-table td {
  padding: 6px 10px;
  font-size: 7.5pt;
  border-bottom: 1px solid var(--border);
}
.compare-table tr:nth-child(even) td {
  background: rgba(250,248,244,.5);
}
.compare-table tr:last-child td { border-bottom: none; }
.chk { color: var(--green); font-weight: 700; }
.xmk { color: var(--red); font-weight: 700; }

/* ── BLOCKED ACCOUNT NOTE ── */
.blocked-note {
  margin-top: 10px;
  padding: 10px 12px;
  background: var(--gold-pale);
  border: 1px solid rgba(196,146,42,.25);
  border-radius: 8px;
}
.blocked-note p {
  font-size: 7pt;
  color: var(--muted);
  line-height: 1.5;
}
.blocked-note strong {
  color: var(--navy);
}

/* ── CONTACT / CTA ── */
.cta-box {
  background: var(--navy);
  border-radius: 10px;
  padding: 20px 24px;
  text-align: center;
  color: #fff;
  margin-top: 18px;
  position: relative;
  overflow: hidden;
}
.cta-box::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: linear-gradient(90deg, #000 33%, #DD0000 33%, #DD0000 66%, #FFCC00 66%);
}
.cta-box h3 {
  font-size: 12pt;
  font-weight: 800;
  margin-bottom: 4px;
}
.cta-box p {
  font-size: 8pt;
  color: rgba(255,255,255,.5);
  margin-bottom: 10px;
}
.cta-details {
  display: flex;
  justify-content: center;
  gap: 28px;
}
.cta-detail {
  text-align: center;
}
.cta-detail .lbl {
  font-size: 6.5pt;
  color: rgba(255,255,255,.4);
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 2px;
}
.cta-detail .val {
  font-size: 9pt;
  font-weight: 700;
  color: var(--gold-light);
}

/* ── PAGE FOOTER ── */
.page-foot {
  position: absolute;
  bottom: 12mm;
  left: 20mm;
  right: 20mm;
  text-align: center;
  font-size: 6.5pt;
  color: rgba(0,0,0,.2);
  border-top: 1px solid var(--border);
  padding-top: 6px;
}
</style>
</head>
<body>

<!-- ═══════════ PAGE 1: COVER ═══════════ -->
<div class="cover">
  <div class="cover-logo">Goo<span>Campus</span></div>
  <div class="cover-badge">Germany PG Career Pathway</div>
  <h1>Complete Package<br><span>Details &amp; Breakdown</span></h1>
  <p class="cover-sub">Everything included in the GooCampus Germany PGCP — from language training in India to permanent residency guidance in Germany.</p>
  <div class="cover-price">
    <div class="label">Total Programme Fee</div>
    <div class="amt">&euro;15,000</div>
    <div class="sub">3 milestone-based installments of &euro;5,000 each</div>
    <div class="inr">Approx. &#8377;13.5L at current rates</div>
  </div>
  <div class="cover-footer">GooCampus &mdash; Your Gateway to Global Medical Careers &bull; goocampus.org/germanypathway</div>
</div>

<!-- ═══════════ PAGE 2: INSTALLMENTS ═══════════ -->
<div class="page">
  <div class="page-header">
    <div class="brand">Goo<span>Campus</span> Germany PGCP</div>
    <div class="page-title">Payment Milestones</div>
  </div>

  <div class="section-label">Payment Structure</div>
  <div class="section-title">Three Milestone-Based Installments</div>
  <p class="section-sub">Each payment unlocks the next phase of your Germany PG journey. No hidden fees, no surprises.</p>

  <div class="inst-grid">
    <div class="inst-card i1">
      <div class="inst-num">Installment 1</div>
      <div class="inst-amt">&euro;5,000</div>
      <div class="inst-when">Paid at enrolment</div>
      <div class="inst-title">India Phase &mdash; Language &amp; Documents</div>
      <ul class="inst-list">
        <li>German language training A1 &ndash; B1 (online, India-based)</li>
        <li>Complete document preparation for Defizitbescheid</li>
        <li>Document evaluation &amp; certified German translation</li>
        <li>Letter of Recommendation (LOR) assistance</li>
        <li>Motivation letter writing &amp; review</li>
        <li>Contract agreement execution</li>
        <li>Dedicated counsellor assignment</li>
      </ul>
    </div>
    <div class="inst-card i2">
      <div class="inst-num">Installment 2</div>
      <div class="inst-amt">&euro;5,000</div>
      <div class="inst-when">After Installment 1 completion</div>
      <div class="inst-title">Visa Phase &mdash; Defizitbescheid &amp; Travel</div>
      <ul class="inst-list">
        <li>Defizitbescheid (Deficit Letter) application filing</li>
        <li>Document attestation from authorities</li>
        <li>Complete visa documentation preparation</li>
        <li>Visa appointment booking &amp; interview prep</li>
        <li>D16 visa fee (included in package)</li>
        <li>Foreign exchange assistance</li>
        <li>Blocked account opening guidance</li>
        <li>Travel &amp; health insurance assistance</li>
      </ul>
    </div>
    <div class="inst-card i3">
      <div class="inst-num">Installment 3</div>
      <div class="inst-amt">&euro;5,000</div>
      <div class="inst-when">After visa is received</div>
      <div class="inst-title">Germany Phase &mdash; Exams, Job &amp; PR</div>
      <ul class="inst-list">
        <li>B2 &amp; C1 medical German course (in Germany)</li>
        <li>Airport pickup &amp; initial accommodation</li>
        <li>City registration (Anmeldung) &amp; bank account</li>
        <li>Document evaluation / Eingangsbest&auml;tigung</li>
        <li>FSP exam training &amp; booking</li>
        <li>Approbation / Kenntnispr&uuml;fung exam guidance</li>
        <li>Temporary employment registration</li>
        <li>Observership placement (2&ndash;3 months)</li>
        <li>Job guidance after Approbation</li>
        <li>Health insurance setup in Germany</li>
        <li>Visa extension support throughout stay</li>
        <li>PR (Permanent Residency) guidance</li>
      </ul>
    </div>
  </div>

  <div class="note-box">
    <h3>&#9888;&#65039; Important Financial Notes</h3>
    <ul>
      <li><strong>D16 visa fee IS included</strong> in the GooCampus package &mdash; you don&rsquo;t pay separately for this</li>
      <li><strong>Blocked account (~&euro;13,000&ndash;&euro;14,000)</strong> is required by German authorities &mdash; this is YOUR money, not a fee</li>
      <li><strong>Living expenses</strong> come from your blocked account (~&euro;1,000&ndash;&euro;1,500/month)</li>
      <li><strong>Exam fees</strong> (FSP, KP, language exams) are paid directly to German authorities &mdash; NOT included</li>
      <li><strong>No hidden costs</strong> &mdash; the &euro;15,000 covers all GooCampus services across all 3 phases</li>
      <li>Once earning as Assistenzarzt (~&euro;4,500&ndash;&euro;5,500/month), the fee is recoverable within 3&ndash;4 months</li>
    </ul>
  </div>

  <div class="page-foot">GooCampus Germany PGCP &bull; Package Details &bull; Page 2</div>
</div>

<!-- ═══════════ PAGE 3: INCLUDED vs NOT INCLUDED ═══════════ -->
<div class="page">
  <div class="page-header">
    <div class="brand">Goo<span>Campus</span> Germany PGCP</div>
    <div class="page-title">Service Checklist</div>
  </div>

  <div class="section-label">Full Transparency</div>
  <div class="section-title">What&rsquo;s Included &amp; What&rsquo;s Not</div>
  <p class="section-sub">Complete breakdown of everything covered in the &euro;15,000 package and what you&rsquo;ll need to arrange separately.</p>

  <div class="check-grid">
    <div class="check-col included">
      <h3>&#10003; Included in Package (&euro;15,000)</h3>
      <ul class="check-list">
        <li>German language training A1 to B1 (India, online)</li>
        <li>B2 &amp; C1 medical German course (Germany)</li>
        <li>Complete document preparation &amp; translation</li>
        <li>Defizitbescheid / Deficit letter application</li>
        <li>Document attestation</li>
        <li>Letter of Recommendation (LOR) assistance</li>
        <li>Motivation letter writing</li>
        <li>D16 visa fee</li>
        <li>Visa documentation &amp; appointment booking</li>
        <li>Visa interview preparation</li>
        <li>Foreign exchange assistance</li>
        <li>Blocked account opening guidance</li>
        <li>Travel &amp; health insurance assistance</li>
        <li>Airport pickup on arrival in Germany</li>
        <li>Initial accommodation assistance</li>
        <li>City registration (Anmeldung)</li>
        <li>German bank account opening</li>
        <li>Document evaluation / Eingangsbest&auml;tigung</li>
        <li>FSP exam training &amp; booking</li>
        <li>Approbation / Kenntnispr&uuml;fung guidance</li>
        <li>Temporary employment registration</li>
        <li>Observership placement (2&ndash;3 months)</li>
        <li>Job guidance after Approbation</li>
        <li>Health insurance setup in Germany</li>
        <li>Visa extension support</li>
        <li>PR (Permanent Residency) guidance</li>
        <li>Dedicated counsellor throughout journey</li>
        <li>Contract agreement &amp; legal support</li>
      </ul>
    </div>
    <div class="check-col not-included">
      <h3>&#10007; Not Included (Candidate&rsquo;s Responsibility)</h3>
      <ul class="check-list">
        <li>Flight tickets (India to Germany)</li>
        <li>Accommodation in Germany (after initial setup)</li>
        <li>Blocked account deposit (~&euro;13,000&ndash;&euro;14,000)</li>
        <li>Living expenses in Germany (~&euro;1,000&ndash;&euro;1,500/month from blocked account)</li>
        <li>Employment visa process cost (after 1 year of stay)</li>
        <li>FSP / Kenntnispr&uuml;fung exam fees (paid to German authorities)</li>
        <li>German language exam fees (Goethe/Telc/TestDaF)</li>
        <li>Personal expenses (food, transport, clothing)</li>
        <li>Medical council registration fees (German &Auml;rztekammer)</li>
        <li>Notarization costs for additional documents</li>
      </ul>

      <div class="blocked-note">
        <p><strong>&#128161; About the Blocked Account:</strong> The blocked account (~&euro;13,000&ndash;&euro;14,000) is required by German authorities as proof of financial support. This money is <strong>yours</strong> &mdash; you withdraw ~&euro;1,000&ndash;&euro;1,500/month for living expenses. It is NOT a fee; it&rsquo;s your own savings for your stay in Germany.</p>
      </div>
    </div>
  </div>

  <div class="page-foot">GooCampus Germany PGCP &bull; Service Checklist &bull; Page 3</div>
</div>

<!-- ═══════════ PAGE 4: DETAILED SERVICES (INDIA + VISA) ═══════════ -->
<div class="page">
  <div class="page-header">
    <div class="brand">Goo<span>Campus</span> Germany PGCP</div>
    <div class="page-title">Detailed Services</div>
  </div>

  <div class="section-label">Phase-by-Phase</div>
  <div class="section-title">Service Delivery Breakdown</div>
  <p class="section-sub">Every service you receive at each milestone, from enrollment to permanent residency.</p>

  <div class="svc-phase p1">
    <div class="svc-phase-head">
      <div class="svc-phase-num">1</div>
      <div>
        <div class="svc-phase-title">India Phase &mdash; Preparation &amp; Documentation</div>
        <div class="svc-phase-sub">Duration: 6&ndash;12 months &bull; Location: India (online)</div>
      </div>
    </div>
    <div class="svc-items">
      <div class="svc-item"><div class="s-text"><strong>Language Training A1&ndash;B1</strong> &mdash; Structured German classes from scratch to B1 level, covering general + medical vocabulary</div></div>
      <div class="svc-item"><div class="s-text"><strong>Document Preparation</strong> &mdash; Degree certificates, transcripts, internship completion compiled for German authorities</div></div>
      <div class="svc-item"><div class="s-text"><strong>German Translation</strong> &mdash; Certified translation of all documents by authorized translators</div></div>
      <div class="svc-item"><div class="s-text"><strong>LOR &amp; Motivation Letter</strong> &mdash; Professionally written recommendation and motivation letters</div></div>
      <div class="svc-item"><div class="s-text"><strong>Dedicated Counsellor</strong> &mdash; Personal counsellor assigned for entire journey guidance</div></div>
      <div class="svc-item"><div class="s-text"><strong>Contract Execution</strong> &mdash; Legal agreement and service terms documentation</div></div>
    </div>
  </div>

  <div class="svc-phase p2">
    <div class="svc-phase-head">
      <div class="svc-phase-num">2</div>
      <div>
        <div class="svc-phase-title">Visa Phase &mdash; Applications &amp; Travel Prep</div>
        <div class="svc-phase-sub">Duration: 3&ndash;6 months &bull; Location: India</div>
      </div>
    </div>
    <div class="svc-items">
      <div class="svc-item"><div class="s-text"><strong>Defizitbescheid Filing</strong> &mdash; Application for deficit letter from German medical authority</div></div>
      <div class="svc-item"><div class="s-text"><strong>Document Attestation</strong> &mdash; Official attestation from relevant Indian and German authorities</div></div>
      <div class="svc-item"><div class="s-text"><strong>Visa Process</strong> &mdash; Complete D16 visa documentation, appointment booking &amp; interview preparation</div></div>
      <div class="svc-item"><div class="s-text"><strong>D16 Visa Fee</strong> &mdash; Visa application fee covered within package</div></div>
      <div class="svc-item"><div class="s-text"><strong>Blocked Account</strong> &mdash; Guidance on opening Sperrkonto (blocked account) with German bank</div></div>
      <div class="svc-item"><div class="s-text"><strong>Insurance Setup</strong> &mdash; Travel insurance + health insurance arrangement for Germany</div></div>
    </div>
  </div>

  <div class="svc-phase p3">
    <div class="svc-phase-head">
      <div class="svc-phase-num">3</div>
      <div>
        <div class="svc-phase-title">Germany Phase &mdash; Exams, Employment &amp; Settlement</div>
        <div class="svc-phase-sub">Duration: 12&ndash;24 months &bull; Location: Germany</div>
      </div>
    </div>
    <div class="svc-items">
      <div class="svc-item"><div class="s-text"><strong>B2 &amp; C1 Medical German</strong> &mdash; Advanced language + medical terminology course in Germany</div></div>
      <div class="svc-item"><div class="s-text"><strong>Airport Pickup</strong> &mdash; Meet &amp; greet at German airport + transport to accommodation</div></div>
      <div class="svc-item"><div class="s-text"><strong>Accommodation</strong> &mdash; Initial housing arrangement assistance on arrival</div></div>
      <div class="svc-item"><div class="s-text"><strong>City Registration</strong> &mdash; Anmeldung (city registration) + bank account opening</div></div>
      <div class="svc-item"><div class="s-text"><strong>FSP Exam Prep</strong> &mdash; Fachsprachpr&uuml;fung training, mock exams &amp; booking</div></div>
      <div class="svc-item"><div class="s-text"><strong>Approbation Guidance</strong> &mdash; Kenntnispr&uuml;fung exam preparation and application</div></div>
      <div class="svc-item"><div class="s-text"><strong>Observership</strong> &mdash; 2&ndash;3 month placement at private clinic for clinical exposure</div></div>
      <div class="svc-item"><div class="s-text"><strong>Job Guidance</strong> &mdash; Hospital job application support after Approbation/license</div></div>
      <div class="svc-item"><div class="s-text"><strong>Visa Extensions</strong> &mdash; Ongoing visa extension support throughout your stay</div></div>
      <div class="svc-item"><div class="s-text"><strong>PR Guidance</strong> &mdash; Permanent Residency application (Blue Card route, 21-month fast-track)</div></div>
    </div>
  </div>

  <div class="page-foot">GooCampus Germany PGCP &bull; Detailed Services &bull; Page 4</div>
</div>

<!-- ═══════════ PAGE 5: COMPARISON + CTA ═══════════ -->
<div class="page" style="page-break-after: auto;">
  <div class="page-header">
    <div class="brand">Goo<span>Campus</span> Germany PGCP</div>
    <div class="page-title">Comparison &amp; Contact</div>
  </div>

  <div class="section-label">GooCampus vs Others</div>
  <div class="section-title">Why GooCampus Germany PGCP Stands Out</div>
  <p class="section-sub">Compare our end-to-end package with other providers and the DIY route.</p>

  <table class="compare-table">
    <thead>
      <tr>
        <th style="width:35%">Service</th>
        <th style="width:22%">GooCampus PGCP</th>
        <th style="width:22%">Other Consultants</th>
        <th style="width:21%">DIY Route</th>
      </tr>
    </thead>
    <tbody>
      <tr><td>Language Training A1&ndash;C1</td><td><span class="chk">&#10003;</span> Included</td><td>Extra cost</td><td>Self-arranged</td></tr>
      <tr><td>Document Prep &amp; Translation</td><td><span class="chk">&#10003;</span> Included</td><td>Partial</td><td>Self-arranged</td></tr>
      <tr><td>Defizitbescheid Application</td><td><span class="chk">&#10003;</span> Included</td><td>Extra cost</td><td>Self-arranged</td></tr>
      <tr><td>Visa Process + D16 Fee</td><td><span class="chk">&#10003;</span> Fee included</td><td>Fee not included</td><td>Self-arranged</td></tr>
      <tr><td>Airport Pickup in Germany</td><td><span class="chk">&#10003;</span> Included</td><td><span class="xmk">&#10007;</span></td><td><span class="xmk">&#10007;</span></td></tr>
      <tr><td>B2/C1 Medical German in Germany</td><td><span class="chk">&#10003;</span> Included</td><td>Extra &euro;3,000+</td><td>Self-arranged</td></tr>
      <tr><td>FSP Exam Training</td><td><span class="chk">&#10003;</span> Included</td><td>Extra cost</td><td>Self-arranged</td></tr>
      <tr><td>Observership Placement</td><td><span class="chk">&#10003;</span> 2&ndash;3 months</td><td><span class="xmk">&#10007;</span></td><td><span class="xmk">&#10007;</span></td></tr>
      <tr><td>Job Guidance after License</td><td><span class="chk">&#10003;</span> Included</td><td><span class="xmk">&#10007;</span></td><td><span class="xmk">&#10007;</span></td></tr>
      <tr><td>PR Guidance</td><td><span class="chk">&#10003;</span> Included</td><td><span class="xmk">&#10007;</span></td><td><span class="xmk">&#10007;</span></td></tr>
      <tr><td>Milestone-Based Payments</td><td><span class="chk">&#10003;</span> 3 installments</td><td>Upfront usually</td><td>N/A</td></tr>
      <tr><td><strong>Estimated Total Cost</strong></td><td><strong>&euro;15,000</strong></td><td><strong>&euro;18,000&ndash;&euro;25,000+</strong></td><td><strong>&euro;12,000&ndash;&euro;20,000+</strong></td></tr>
    </tbody>
  </table>

  <div class="cta-box">
    <h3>Ready to Start Your Germany Journey?</h3>
    <p>Get in touch with our team to begin your PG Career Pathway</p>
    <div class="cta-details">
      <div class="cta-detail">
        <div class="lbl">Website</div>
        <div class="val">goocampus.org/germanypathway</div>
      </div>
      <div class="cta-detail">
        <div class="lbl">WhatsApp</div>
        <div class="val">+91 636 314 1075</div>
      </div>
      <div class="cta-detail">
        <div class="lbl">Email</div>
        <div class="val">info@goocampus.in</div>
      </div>
    </div>
  </div>

  <div class="page-foot">GooCampus Germany PGCP &bull; &copy; 2025 GooCampus. All rights reserved. &bull; Page 5</div>
</div>

</body>
</html>
"""

if __name__ == '__main__':
    print("Generating Germany Pathway Package PDF...")
    html = HTML(string=HTML_CONTENT)
    html.write_pdf(OUTPUT_PATH)
    print(f"PDF saved to: {OUTPUT_PATH}")
    # Verify file size
    size = os.path.getsize(OUTPUT_PATH)
    print(f"File size: {size:,} bytes ({size/1024:.1f} KB)")
