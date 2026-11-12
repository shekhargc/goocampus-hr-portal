"""Builds the fixed Word template the founder's team writes questions in (downloaded from the import page)."""
import io


def _sample_png():
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (480, 260), (236, 240, 245))
    d = ImageDraw.Draw(im)
    d.rectangle((8, 8, 471, 251), outline=(120, 130, 150), width=2)
    d.text((150, 120), 'Paste the X-ray / ECG / photo here', fill=(60, 70, 90))
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    buf.seek(0)
    return buf


def build_template():
    import docx
    from docx.shared import Inches, Pt, RGBColor

    d = docx.Document()
    st = d.styles['Normal']
    st.font.name = 'Calibri'
    st.font.size = Pt(11)

    h = d.add_heading('GooCampus — NEET PG question template', level=1)
    d.add_paragraph('How to fill this in (the importer reads these labels):')
    for line in [
        'Start every question with Q and its number: "Q1." then the question text.',
        'Paste a picture or diagram on its own line straight under the question text (before the options).',
        'Type the four options as "A.", "B.", "C.", "D." — one per line.',
        'Then "Answer: B" (just the letter).',
        'Then "Explanation:" and the explanation. Pictures pasted after the Answer line go with the explanation.',
        'Optional: "Subject:" (one of the 19 NEET PG subjects) and "Topic:".',
        'Paste pictures as normal pictures (PNG/JPG). Avoid Word drawings/clip-art — they can\'t be shown to doctors.',
        'You can put many questions in one file. Delete these instructions and the examples before uploading if you like.',
    ]:
        d.add_paragraph(line, style='List Bullet')

    d.add_heading('Example 1 — with a picture', level=2)
    d.add_paragraph('Q1. A 28-year-old woman presents with palpitations. She is haemodynamically stable. '
                    'Her ECG is shown below. What is the most appropriate initial management?')
    d.add_paragraph().add_run().add_picture(_sample_png(), width=Inches(3.6))
    for t in ['A. Adenosine 6 mg IV bolus', 'B. Synchronised cardioversion', 'C. Vagal manoeuvres', 'D. Verapamil 5 mg IV']:
        d.add_paragraph(t)
    d.add_paragraph('Answer: C')
    d.add_paragraph('Explanation: Stable narrow-complex tachycardia (AVNRT) — vagal manoeuvres first; '
                    'adenosine if they fail; cardioversion only if unstable.')
    d.add_paragraph('Subject: Medicine')
    d.add_paragraph('Topic: Cardiology — arrhythmias')

    d.add_heading('Example 2 — text only', level=2)
    d.add_paragraph('Q2. Drug of choice for absence seizures in a child is:')
    for t in ['A. Phenytoin', 'B. Carbamazepine', 'C. Ethosuximide', 'D. Phenobarbitone']:
        d.add_paragraph(t)
    d.add_paragraph('Answer: C')
    d.add_paragraph('Explanation: Ethosuximide (or valproate) is first-line for childhood absence epilepsy; '
                    'carbamazepine and phenytoin can worsen absences.')
    d.add_paragraph('Subject: Pharmacology')
    d.add_paragraph('Topic: Antiepileptics')

    p = d.add_paragraph('Subjects: Anatomy, Physiology, Biochemistry, Pathology, Pharmacology, Microbiology, '
                        'Forensic Medicine, Community Medicine, ENT, Ophthalmology, Medicine, Surgery, '
                        'Obstetrics & Gynaecology, Paediatrics, Orthopaedics, Dermatology, Psychiatry, '
                        'Anaesthesia, Radiology. Specialities like Cardiology or Urology are fine as the Topic.')
    for r in p.runs:
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(90, 100, 120)
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()
