"""Subjects per exam + the speciality → subject mapping (founder 2026-11-13).

NEET PG results are analysed by NBEMS's 19 subjects, but question papers are often tagged by
speciality ("CARDIOLOGY", "HIV", "UROLOGY"). Each tag is mapped to one of the 19 subjects; the
speciality is kept as the question's topic. Tags we can't place with confidence (Oncology,
Genetics, Hematology …) are left unmapped on purpose — the check report asks the team to choose,
and their choice is remembered (ex_subject_aliases) for every later file.
"""
import re

# exam_code → ordered subject list (the 19 NEET PG subjects, NBEMS order: pre-clinical → para → clinical)
SUBJECTS = {
    'neet_pg': [
        'Anatomy', 'Physiology', 'Biochemistry',
        'Pathology', 'Pharmacology', 'Microbiology', 'Forensic Medicine', 'Community Medicine',
        'ENT', 'Ophthalmology',
        'Medicine', 'Surgery', 'Obstetrics & Gynaecology', 'Paediatrics',
        'Orthopaedics', 'Dermatology', 'Psychiatry', 'Anaesthesia', 'Radiology',
    ],
}

# Seed aliases: normalised tag → subject name. Only confident mappings live here.
SEED_ALIASES = {
    'neet_pg': {
        # the subjects themselves + common spellings
        'anatomy': 'Anatomy', 'physiology': 'Physiology', 'biochemistry': 'Biochemistry',
        'pathology': 'Pathology', 'pharmacology': 'Pharmacology', 'microbiology': 'Microbiology',
        'forensic medicine': 'Forensic Medicine', 'forensic': 'Forensic Medicine', 'fmt': 'Forensic Medicine',
        'forensic medicine and toxicology': 'Forensic Medicine', 'toxicology': 'Forensic Medicine',
        'community medicine': 'Community Medicine', 'psm': 'Community Medicine', 'spm': 'Community Medicine',
        'preventive and social medicine': 'Community Medicine', 'social and preventive medicine': 'Community Medicine',
        'ent': 'ENT', 'otorhinolaryngology': 'ENT', 'otolaryngology': 'ENT',
        'ophthalmology': 'Ophthalmology', 'ophthal': 'Ophthalmology', 'eye': 'Ophthalmology',
        'medicine': 'Medicine', 'general medicine': 'Medicine', 'internal medicine': 'Medicine',
        'surgery': 'Surgery', 'general surgery': 'Surgery',
        'obg': 'Obstetrics & Gynaecology', 'obgy': 'Obstetrics & Gynaecology', 'og': 'Obstetrics & Gynaecology',
        'obstetrics': 'Obstetrics & Gynaecology', 'gynecology': 'Obstetrics & Gynaecology',
        'gynaecology': 'Obstetrics & Gynaecology', 'obstetrics and gynaecology': 'Obstetrics & Gynaecology',
        'obstetrics and gynecology': 'Obstetrics & Gynaecology', 'obstetrics gynaecology': 'Obstetrics & Gynaecology',
        'pediatrics': 'Paediatrics', 'paediatrics': 'Paediatrics', 'neonatology': 'Paediatrics',
        'orthopedics': 'Orthopaedics', 'orthopaedics': 'Orthopaedics', 'ortho': 'Orthopaedics',
        'dermatology': 'Dermatology', 'skin': 'Dermatology', 'venereology': 'Dermatology',
        'psychiatry': 'Psychiatry',
        'anesthesia': 'Anaesthesia', 'anaesthesia': 'Anaesthesia', 'anesthesiology': 'Anaesthesia',
        'anaesthesiology': 'Anaesthesia',
        'radiology': 'Radiology', 'radiodiagnosis': 'Radiology', 'radiotherapy': 'Radiology',
        # medical specialities → Medicine
        'cardiology': 'Medicine', 'neurology': 'Medicine', 'gastroenterology': 'Medicine',
        'hepatology': 'Medicine', 'nephrology': 'Medicine', 'endocrinology': 'Medicine',
        'pulmonology': 'Medicine', 'pulmonary medicine': 'Medicine', 'respiratory medicine': 'Medicine',
        'rheumatology': 'Medicine', 'hiv': 'Medicine', 'infectious diseases': 'Medicine',
        'critical care': 'Medicine', 'geriatrics': 'Medicine',
        # surgical specialities → Surgery
        'urology': 'Surgery', 'trauma': 'Surgery', 'neurosurgery': 'Surgery', 'cardiothoracic surgery': 'Surgery',
        'plastic surgery': 'Surgery', 'paediatric surgery': 'Surgery', 'pediatric surgery': 'Surgery',
        # pharmacology sub-areas
        'pharmacogenomics': 'Pharmacology',
    },
}
# Deliberately NOT mapped (the team decides; it depends on the question): oncology, genetics,
# hematology/haematology, immunology, emergency medicine.


def norm_tag(s):
    """'OBSTETRICS & GYNAECOLOGY ' → 'obstetrics and gynaecology'."""
    s = (s or '').strip().lower().replace('&', ' and ')
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def pretty_tag(s):
    """'GASTROENTEROLOGY' → 'Gastroenterology'; keeps short acronyms (ENT, HIV) upper-case."""
    s = re.sub(r'\s+', ' ', (s or '').strip())
    if not s:
        return ''
    if len(s) <= 4 and s.isalpha():
        return s.upper()
    if s.isupper():
        return s.title().replace(' And ', ' and ')
    return s
