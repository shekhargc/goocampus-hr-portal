"""Odisha NEET PG 2026-27 provisional seat matrices (Convenor, PG (Medical) Counselling Committee, MKCG Medical
College Brahmapur, 26.10.2026) → standardised seat rows, bridged to Odisha's 2025 cut-offs. Three PDFs:
  mdms     — No. 46: MD/MS. In-service State Quota and Direct State Quota, each 11 colleges (seat count + the
             category list, e.g. "1-SEBC 1-SC 3-UR"), a Total, then the 3 private Management columns (counts only)
  diploma  — No. 47: Post-MBBS (NBEMS) Diploma, 20 hospitals (count + category list), Total, Grand Total
  dnb      — No. 48: Post-MBBS DNB, 3 colleges (count + category list), Total, Grand Total (page printed sideways)
All three are SCANNED (no text layer), so the tables are transcribed below cell by cell, exactly as printed,
and pinned to the PDFs' SHA-256 (a re-issued PDF stops the script — re-transcribe it). Every printed number is
checked: each cell's count equals its category list, every row adds up to its Total, every column to the
printed TOTAL row. Run with /usr/bin/python3 (PyMuPDF):
  odisha.py <mdms.pdf> <diploma.pdf> <dnb.pdf> <cutoffs2025.json> <out.json>"""
import re, sys, os, json, hashlib, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import load_cuts, build, report

MDMS, DIP, DNB, CUTS, OUT = sys.argv[1:6]
SHA = {MDMS: '988917d37176a4208c284e87606717f28fd4d6120a290015e457a40b090a84ea',
       DIP: 'e73c0bd519bfb419a83e98b55324b0cd58daaeb89f0daa0fd2c650c328285c87',
       DNB: 'ea73b2315d0f9d4749def6d740ac3ae8a2ec41fad11d64b329dacdc05283d902'}
for path, sha in SHA.items():
    if hashlib.sha256(open(path, 'rb').read()).hexdigest() != sha:
        raise SystemExit(f'{path}: not the PDF this transcription was made from — re-transcribe it')
    doc = fitz.open(path)
    if len(doc) != 1 or doc[0].get_text().strip():
        raise SystemExit(f'{path}: expected one scanned page with no text layer')

COLLEGES = {  # PDF column heading → standard institute name (2025 cut-offs)
    'SCB MC': 'SCB Medical College, Cuttack',
    'MKCG MC': 'Maharaja Krushna Chandra Gajapati Medical College and Hospital, Brahmapur',
    'VIMSAR': 'Veer Surendra Sai Institute of Medical Sciences and Research, Burla',
    'PGIMER': 'Postgraduate Institute of Medical Education & Research and Capital Hospital, Bhubaneswar',
    'AHRCC': 'Acharya Harihar Post Graduate Institute of Cancer, Cuttack',
    'FM MC': 'Fakir Mohan Medical College and Hospital, Balasore, Odisha',
    'PRM MC': 'Pandit Raghunath Murmu Medical College and Hospital, Baripada, Mayurbhanj, Odisha',
    'BB MC': 'Bhima Bhoi Medical College and Hospital, Balangir, Odisha',
    'Hi-Tech, BBSR': 'Hi-Tech Medical College & Hospital, Bhubaneswar',
    'Hi-Tech, Rourkela': 'Hi-Tech Medical College & Hospital, Rourkela',
    'DRIEMS, Kataka': 'DRIEMS Institute Of Health Sciences And Hospital, Tangi, Odisha'}
COLS = list(COLLEGES)                                     # the 11 college columns, left to right
MGT = ['Hi-Tech, BBSR', 'Hi-Tech, Rourkela', 'DRIEMS, Kataka']   # "…-MGT" columns (counts only)
HOSPITALS = {  # diploma / DNB headings → standard name; the 2025 cut-off name where it exists, else a new one
    'FM MCH, BALASORE': 'Fakir Mohan Medical College and Hospital, Balasore, Odisha',
    'PRM MCH, BARIPADA': 'Pandit Raghunath Murmu Medical College and Hospital, Baripada, Mayurbhanj, Odisha',
    'BB MCH, BALANGIR': 'Bhima Bhoi Medical College and Hospital, Balangir, Odisha',
    'Capital Hospital, Bhubaneswar': 'Capital Hospital, Bhubaneswar, Odisha',
    'SLN MCH, KORAPUT': 'Saheed Laxman Nayak Medical College and Hospital, Koraput, Odisha',
    'DHH PURI': 'District Head Quarters Hospital, Puri, Odisha',                          # new
    'DHH, NAYAGARH': 'District Head Quarter Hospital, Nayagarh, Odisha',
    'DHH, Sambalpur': 'District Head Quarter Hospital, Modipada, Sambalpur, Odisha',
    'Rourkela Govt. Hospital': 'Rourkela Government Hospital, Rourkela, Sundargarh, Odisha',
    'DHH, Kalahandi': 'District Head Quarters Hospital, Kalahandi, Bhawanipatna, Odisha',
    'DHH, Bolangir': 'District Head Quarters Hospital, Sudpada, Balangir, Odisha',
    'DHH, Kendrapara': 'District Head Quarters Hospital, Samagudi, Baladevje, Kendrapara, Odisha',
    'DHH, Khordha': 'District Head Quarters Hospital, Khordha, Odisha',
    'DHH, Baripada': 'District Head Quarters Hospital, Baripada, Mayurbhanj, Odisha',      # new
    'DHH, Angul': 'District Head Quarters Hospital, Angul, Odisha',                        # new
    'DHH, Jagatsinghpur': 'District Head Quarters Hospital, Jagatsinghpur, Odisha',        # new
    'DHH, Jeypore, Koraput': 'District Head Quarters Hospital, Jeypore, Koraput, Odisha',  # new
    'DHH, Phulbani, Kandhamal': 'District Head Quarters Hospital, Phulbani, Kandhamal, Odisha',  # new
    'DHH, Rayagada': 'District Head Quarters Hospital, Rayagada, Odisha',                  # new
    'DHH, Dhenkanal': 'District Head Quarters Hospital, Dhenkanal, Odisha',                # new
    'SJ MCH,PURI': 'Shri Jagannath Medical College and Hospital, Puri, Odisha'}            # new (DNB only)
COURSES = {
    'Anatomy': 'MD/MS - Anatomy', 'Physiology': 'MD - Physiology', 'Biochemistry': 'MD - Biochemistry',
    'Pharmacology': 'MD - Pharmacology', 'Forensic Medicine': 'MD - Forensic Medicine', 'Pathology': 'MD - Pathology',
    'Microbiology': 'MD - Microbiology', 'Community Medicine': 'MD - Social & Preventive Medicine / Community Medicine',
    'General Medicine': 'MD - General Medicine', 'Pediatrics': 'MD - Paediatrics', 'Psychiatry': 'MD - Psychiatry',
    'Respiratory Medicine': 'MD - Respiratory Medicine', 'Skin & VD [DVL]': 'MD - Dermatology',
    'Transfusion Medicine': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'Obst. & Gyn.': 'MS - Obstetrics and Gynaecology', 'General Surgery': 'MS - General Surgery',
    'Orthopaedics': 'MS - Orthopaedics', 'Ophthalmology': 'MS - Ophthalmology', 'ENT': 'MS - ENT (Otorhinolaryngology)',
    'Anesthesiology': 'MD - Anaesthesiology', 'Radiodiagnosis': 'MD - Radio-Diagnosis',
    'Radiotherapy': 'MD - Radiotherapy / Radiation Oncology'}
DIPLOMA = {'Ophthalmology': 'Diploma in Ophthalmology', 'Pediatrics': 'Diploma in Child Health / Paediatrics',
           'Radiodiagnosis': 'Diploma in Radio Diagnosis', 'ENT': 'Diploma in ENT',
           'Anaesthesiology': 'Diploma in Anaesthesiology', 'Family Medicine': 'Diploma in Family Medicine',
           'O&G': 'Diploma in Obstetrics and Gynaecology', 'TB & CD': 'Diploma in Respiratory Medicine'}
DNB_COURSES = {'General Medicine': 'DNB - General Medicine (Post-MBBS)',
               'O&G': 'DNB - Obstetrics and Gynaecology (Post-MBBS)', 'General Surgery': 'DNB - General Surgery (Post-MBBS)',
               'Paediatrics': 'DNB - Paediatrics (Post-MBBS)', 'Ophthalmology': 'DNB - Ophthalmology (Post-MBBS)',
               'Respiratory Medicine': 'DNB - Respiratory Medicine (Post-MBBS)',
               'Anaesthesiology': 'DNB - Anaesthesiology (Post-MBBS)'}

# ── No. 46 MD/MS, transcribed. Per course: the 11 college cells (count=category list, "0" = none) | printed Total |
#    the 3 MGT counts | printed MGT Total. Columns: SCB MKCG VIMSAR PGIMER AHRCC FM PRM BB HiTech-BBSR HiTech-RKL DRIEMS
IN_SERVICE = """
Anatomy              | 2=1-UR,1-SC | 1=1-SEBC | 1=1-UR(GC) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1=1-ST | 5 | 0 0 1 | 1
Physiology           | 2=1-UR(ES),1-SC | 1=1-EWS | 1=1-ST | 0 | 0 | 0 | 0 | 0 | 1=1-UR | 0 | 1=1-UR | 6 | 1 0 1 | 2
Biochemistry         | 1=1-EWS | 2=1-ST,1-UR | 2=1-SC,1-UR | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 0 0 0 | 0
Pharmacology         | 2=1-EWS,1-SEBC | 2=1-ST,1-UR | 2=1-SC,1-UR | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 0 0 | 0
Forensic Medicine    | 1=1-ST(PwD) | 1=1-UR | 1=1-UR | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 0 0 | 0
Pathology            | 2=1-UR,1-SC | 3=1-SEBC,1-SC,1-UR(GC) | 1=1-EWS | 1=1-UR | 1=1-ST(PwD) | 0 | 0 | 0 | 2=1-ST,1-UR | 0 | 0 | 10 | 2 0 0 | 2
Microbiology         | 2=1-ST,1-EWS | 2=1-SC,1-UR | 2=1-UR,1-ST | 1=1-UR | 0 | 0 | 0 | 0 | 1=1-UR | 0 | 1=1-SEBC | 9 | 1 1 1 | 3
Community Medicine   | 1=1-UR | 3=1-ST,1-SC,2-UR | 3=1-UR(ES),1-SEBC,1-ST | 0 | 0 | 0 | 0 | 0 | 1=1-UR | 0 | 1=1-UR | 9 | 2 0 0 | 2
General Medicine     | 7=1-SEBC,1-SC(ES),1-ST,1-ST(GC),3-UR | 4=1-ST,1-SC,1-UR | 5=1-SEBC,1-SC,1-ST,2-UR | 1=1-UR(PwD) | 0 | 0 | 1=1-SC(PwD) | 0 | 3=1-ST,2-UR | 0 | 0 | 21 | 3 0 0 | 3
Pediatrics           | 6=1-SEBC,1-SC,1-ST,1-UR(GC),2-UR | 3=1-SEBC(PwD),1-ST,1-UR | 3=1-ST,1-UR,1-UR(PwD) | 1=1-UR | 0 | 0 | 1=1-UR | 0 | 2=1-SC(GC),1-UR | 1=1-ST | 0 | 17 | 2 1 0 | 3
Psychiatry           | 2=1-ST,1-UR(PwD) | 1=1-UR | 0 | 0 | 0 | 0 | 0 | 0 | 1=1-SC | 0 | 0 | 4 | 1 0 0 | 1
Respiratory Medicine | 1=1-UR(PwD) | 0 | 1=1-SC | 1=1-UR | 0 | 0 | 1=1-ST | 0 | 1=1-SEBC | 0 | 0 | 5 | 1 0 0 | 1
Skin & VD [DVL]      | 2=1-ST,1-UR | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2=1-SEBC,1-SC | 1=1-UR(PwD) | 0 | 5 | 1 1 0 | 2
Transfusion Medicine | 1=1-ST | 1=1-UR | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 0 0 | 0
Obst. & Gyn.         | 5=1-SEBC,1-SC,3-UR | 3=1-SC(GC),1-ST,1-UR | 2=1-ST,1-UR | 1=1-SEBC | 0 | 1=1-SC | 0 | 0 | 3=1-ST,1-UR,1-UR(GC) | 1=1-UR | 0 | 16 | 3 0 0 | 3
General Surgery      | 6=1-SEBC(GC),1-ST,3-UR,1-UR(ES) | 5=1-SEBC,1-SC,1-ST,2-UR | 5=1-SEBC,1-SC,1-ST,2-UR | 1=1-ST | 0 | 0 | 1=1-UR | 1=1-ST | 3=1-SC,2-UR | 0 | 0 | 22 | 3 1 0 | 4
Orthopaedics         | 4=1-SC,1-ST,2-UR | 2=1-ST,1-UR | 2=1-SEBC,1-SC | 0 | 0 | 0 | 0 | 1=1-UR | 2=1-ST,1-UR | 0 | 1=1-UR | 12 | 2 1 1 | 4
Ophthalmology        | 2=1-ST,1-UR | 2=1-SC,1-SEBC | 1=1-UR | 1=1-ST(ES) | 0 | 0 | 0 | 0 | 1=1-UR | 1=1-UR | 0 | 8 | 1 0 0 | 1
ENT                  | 1=1-UR | 0 | 1=1-UR | 0 | 0 | 1=1-UR | 0 | 0 | 2=1-SEBC,1-ST | 1=1-SC | 0 | 6 | 1 0 0 | 1
Anesthesiology       | 5=1-SEBC(ES),1-ST,1-SC,2-UR | 3=1-ST,2-UR | 3=1-ST(GC),2-UR | 1=1-UR | 1=1-UR | 0 | 1=1-SEBC | 0 | 2=1-SC,1-UR | 0 | 1=1-SC | 17 | 2 0 1 | 3
Radiodiagnosis       | 2=1-SC,1-UR | 1=1-UR | 0 | 0 | 0 | 0 | 0 | 0 | 1=1-ST | 0 | 0 | 4 | 1 0 1 | 2
Radiotherapy         | 1=1-UR | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 0 0 | 0
TOTAL                | 58 | 40 | 36 | 9 | 2 | 2 | 5 | 2 | 28 | 5 | 6 | 193 | 27 5 6 | 38
"""
DIRECT = """
Anatomy              | 2=1-SC,1-UR | 1=1-ST | 2=1-EWS,1-UR | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 0 0 0 | 0
Physiology           | 1=1-SEBC | 2=1-ST(PwD),1-UR | 1=1-SC | 0 | 0 | 0 | 0 | 0 | 1=1-UR | 0 | 1=1-UR | 6 | 1 0 1 | 2
Biochemistry         | 2=1-SC,1-UR | 1=1-UR(ES) | 1=1-ST | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1=1-SEBC | 5 | 0 0 1 | 1
Pharmacology         | 1=1-SC | 2=1-EWS,1-UR | 2=1-ST,1-UR(PwD) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 0 0 0 | 0
Forensic Medicine    | 2=1-ST,1-UR | 1=1-SEBC | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1=1-UR | 4 | 0 0 1 | 1
Pathology            | 2=1-EWS,1-SEBC | 2=2-UR | 2=1-SC,1-UR | 0 | 1=1-ST | 0 | 0 | 0 | 2=1-ST,1-UR(GC) | 1=1-UR | 0 | 10 | 2 1 0 | 3
Microbiology         | 1=1-UR | 2=1-SC,1-UR | 1=1-EWS | 1=1-UR | 0 | 0 | 1=1-UR | 0 | 1=1-SEBC | 1=1-ST | 1=1-ST(GC) | 9 | 1 0 1 | 2
Community Medicine   | 2=1-EWS,1-UR(PwD) | 3=1-SC,1-ST,1-UR | 2=1-SEBC,1-UR | 0 | 0 | 0 | 0 | 0 | 2=1-ST,1-UR | 0 | 1=1-SC | 10 | 1 0 1 | 2
General Medicine     | 8=1-SEBC,1-SC,1-ST,1-ST(GC),3-UR,1-UR(GC) | 3=1-SC,1-ST,1-UR | 5=1-SEBC,1-ST,2-UR,1-UR(GC) | 1=1-UR | 0 | 0 | 1=1-SC | 0 | 3=1-ST,1-UR,1-UR(PwD) | 0 | 0 | 21 | 3 0 0 | 3
Pediatrics           | 6=1-SEBC,1-SC,1-ST(PwD),2-UR,1-UR(ES) | 3=1-ST,1-UR,1-UR(GC) | 2=1-ST,1-SC | 1=1-SC | 0 | 0 | 1=1-ST | 1=1-UR | 2=1-SEBC,1-UR | 1=1-UR | 0 | 17 | 2 1 0 | 3
Psychiatry           | 2=1-ST,1-UR | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1=1-UR | 0 | 0 | 3 | 2 0 0 | 2
Respiratory Medicine | 2=1-ST,1-UR | 1=1-SEBC(GC) | 1=1-UR | 1=1-UR | 0 | 0 | 0 | 0 | 1=1-SC | 0 | 0 | 6 | 1 0 0 | 1
Skin & VD [DVL]      | 1=1-ST | 1=1-SC | 1=1-UR | 0 | 0 | 0 | 0 | 0 | 1=1-UR | 0 | 0 | 4 | 1 0 0 | 1
Transfusion Medicine | 1=1-UR | 1=1-SEBC | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 0 0 | 0
Obst. & Gyn.         | 5=1-SEBC,1-SC,1-ST(ES),2-UR | 3=1-SC,1-ST,1-UR | 3=1-SC,2-UR | 1=1-UR | 0 | 0 | 1=1-UR | 0 | 3=1-SEBC(PwD),1-ST,1-UR | 0 | 0 | 16 | 3 1 0 | 4
General Surgery      | 6=1-SEBC,1-SC(GC),1-ST,3-UR | 5=1-SC,1-ST,2-UR,1-UR(GC) | 4=1-SC,1-ST,1-UR,1-UR(PwD) | 2=1-ST,1-UR | 0 | 0 | 0 | 1=1-ST | 3=1-SC,1-UR,1-UR(ES) | 1=1-SEBC | 0 | 22 | 3 0 0 | 3
Orthopaedics         | 3=1-SC,2-UR | 2=1-ST,1-UR | 1=1-SEBC(ES) | 1=1-ST | 0 | 0 | 0 | 1=1-UR | 2=2-UR | 1=1-SC | 1=1-ST | 12 | 2 0 1 | 3
Ophthalmology        | 3=1-SC(PwD),2-UR | 2=1-SEBC,1-UR | 2=1-ST,1-UR | 0 | 0 | 0 | 0 | 0 | 1=1-ST | 0 | 0 | 8 | 1 1 0 | 2
ENT                  | 1=1-SEBC | 1=1-UR | 1=1-UR | 0 | 0 | 1=1-SC | 0 | 0 | 1=1-ST | 0 | 0 | 5 | 1 1 0 | 2
Anesthesiology       | 5=1-SC,1-ST,2-UR,1-UR(PwD) | 2=1-ST,1-UR | 4=1-SEBC,1-SC,1-ST,1-UR | 1=1-SEBC | 0 | 1=1-UR | 1=1-UR | 0 | 2=1-SC,1-UR(GC) | 0 | 0 | 16 | 2 0 0 | 2
Radiodiagnosis       | 1=1-ST | 1=1-UR | 1=1-UR | 0 | 0 | 0 | 0 | 0 | 1=1-SC | 0 | 1=1-UR | 5 | 2 0 0 | 2
Radiotherapy         | 2=1-ST,1-UR | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 0 0 | 0
TOTAL                | 59 | 39 | 36 | 9 | 1 | 2 | 5 | 3 | 27 | 5 | 7 | 193 | 28 5 6 | 39
"""
# Two printed cells whose category list does not add up to their seat count (the counts do add up to every
# total). Their seats are kept with no category rather than guessing which label is wrong.
MISPRINTS = {('In-service', 'MKCG MC', 'Community Medicine'): '3 seats but the list "1-ST 1-SC 2-UR" adds to 4',
             ('In-service', 'MKCG MC', 'General Medicine'): '4 seats but the list "1-ST 1-SC 1-UR" adds to 3'}

# ── No. 47 Post-MBBS Diploma: per subject, the hospital cells (heading=category list) | printed Total
DIP_COLS = ['FM MCH, BALASORE', 'PRM MCH, BARIPADA', 'BB MCH, BALANGIR', 'Capital Hospital, Bhubaneswar',
            'SLN MCH, KORAPUT', 'DHH PURI', 'DHH, NAYAGARH', 'DHH, Sambalpur', 'Rourkela Govt. Hospital', 'DHH, Kalahandi',
            'DHH, Bolangir', 'DHH, Kendrapara', 'DHH, Khordha', 'DHH, Baripada', 'DHH, Angul', 'DHH, Jagatsinghpur',
            'DHH, Jeypore, Koraput', 'DHH, Phulbani, Kandhamal', 'DHH, Rayagada', 'DHH, Dhenkanal']
DIPLOMA_ROWS = """
Ophthalmology   | FM MCH, BALASORE=1-SC; PRM MCH, BARIPADA=1-ST; Capital Hospital, Bhubaneswar=1-UR; Rourkela Govt. Hospital=1-UR | 4
Pediatrics      | FM MCH, BALASORE=1-ST,1-UR; Capital Hospital, Bhubaneswar=1-ST,1-UR; SLN MCH, KORAPUT=1-SC,1-UR; DHH PURI=1-ST; DHH, NAYAGARH=1-UR(ES); DHH, Sambalpur=1-SC; Rourkela Govt. Hospital=1-SC; DHH, Kalahandi=1-UR(PwD); DHH, Bolangir=1-UR(GC); DHH, Kendrapara=1-SEBC; DHH, Khordha=1-UR; DHH, Baripada=1-SEBC; DHH, Angul=1-UR; DHH, Jagatsinghpur=1-ST; DHH, Jeypore, Koraput=1-UR; DHH, Phulbani, Kandhamal=1-SEBC; DHH, Rayagada=1-UR; DHH, Dhenkanal=1-UR | 21
Radiodiagnosis  | FM MCH, BALASORE=1-UR; PRM MCH, BARIPADA=1-SEBC; Capital Hospital, Bhubaneswar=1-ST | 3
ENT             | PRM MCH, BARIPADA=1-UR | 1
Anaesthesiology | BB MCH, BALANGIR=1-SC,1-UR; Capital Hospital, Bhubaneswar=1-SEBC; SLN MCH, KORAPUT=1-ST,1-UR | 5
Family Medicine | BB MCH, BALANGIR=1-ST(PwD),1-UR; Capital Hospital, Bhubaneswar=1-SC,1-UR | 4
O&G             | Capital Hospital, Bhubaneswar=1-SC,1-UR; Rourkela Govt. Hospital=1-ST(GC); DHH, Jagatsinghpur=1-UR | 4
TB & CD         | Capital Hospital, Bhubaneswar=1-UR | 1
"""
# the cell counts printed beside each list (checked against the list) and the Grand Total row
DIP_COUNTS = {('Pediatrics', 'FM MCH, BALASORE'): 2, ('Pediatrics', 'Capital Hospital, Bhubaneswar'): 2,
              ('Pediatrics', 'SLN MCH, KORAPUT'): 2, ('Anaesthesiology', 'BB MCH, BALANGIR'): 2,
              ('Anaesthesiology', 'SLN MCH, KORAPUT'): 2, ('Family Medicine', 'BB MCH, BALANGIR'): 2,
              ('Family Medicine', 'Capital Hospital, Bhubaneswar'): 2, ('O&G', 'Capital Hospital, Bhubaneswar'): 2}
DIP_GRAND = dict(zip(DIP_COLS, [4, 3, 4, 10, 4, 1, 1, 1, 3, 1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1]))
DIP_GRAND_TOTAL = 43

# ── No. 48 Post-MBBS DNB: SJ MCH Puri | BB MCH Balangir | SLN MCH Koraput (count=category list) | printed Total
DNB_COLS = ['SJ MCH,PURI', 'BB MCH, BALANGIR', 'SLN MCH, KORAPUT']
DNB_ROWS = """
General Medicine     | 2=1-ST,1-UR | 0 | 2=1-SC,1-UR | 4
O&G                  | 1=1-SC | 0 | 2=1-ST,1-UR | 3
General Surgery      | 2=1-SEBC,1-UR | 0 | 0 | 2
Paediatrics          | 2=1-ST,1-UR | 0 | 0 | 2
Ophthalmology        | 1=1-UR(PwD) | 0 | 0 | 1
Respiratory Medicine | 1=1-UR(GC) | 0 | 0 | 1
Anaesthesiology      | 2=1-SC,1-UR(ES) | 1=1-ST | 2=1-SEBC,1-UR | 5
Grand Total          | 11 | 1 | 6 | 18
"""

TOKEN = re.compile(r'(\d+)-(UR|SC|ST|SEBC|EWS)(?:\((GC|ES|PwD)\))?$')


def categories(lst):
    """'1-SEBC,1-SC(ES),3-UR' → {'SEBC':1, 'SC-ES':1, 'UR':3}"""
    out = collections.Counter()
    for tok in lst.split(','):
        m = TOKEN.match(tok.strip())
        if not m:
            raise SystemExit(f'bad category token {tok!r}')
        out[m.group(2) + ('-' + m.group(3) if m.group(3) else '')] += int(m.group(1))
    return out


def cell(s):
    """'3=1-ST,1-SC,1-UR' → (3, Counter) · '0' → (0, {})"""
    s = s.strip()
    if '=' not in s:
        return int(s), collections.Counter()
    n, lst = s.split('=')
    return int(n), categories(lst)


rows, checks = [], {}


def add(college, course, quota, section, cats):
    for cat, n in cats.items():
        rows.append({'college': college, 'course': course, 'quota': quota, 'seats': n, 'section': section, 'category': cat})


# ── MD/MS ──
for label, text, quota, mquota in (('In-service', IN_SERVICE, 'In-service Quota', 'Management Quota (In-service)'),
                                   ('Direct', DIRECT, 'State Quota', 'Management Quota')):
    col, mcol, tot, mtot = collections.Counter(), collections.Counter(), 0, 0
    for line in text.strip().splitlines():
        f = [x.strip() for x in line.split('|')]
        if len(f) != 15:
            raise SystemExit(f'{label}: {f[0]} has {len(f)} fields')
        name, cells, total, mgt, mtotal = f[0], f[1:12], int(f[12]), [int(x) for x in f[13].split()], int(f[14])
        if name == 'TOTAL':
            for i, c in enumerate(COLS):
                checks[f'MD/MS {label} | {c}'] = (col[c], int(cells[i]))
            checks[f'MD/MS {label} | Total'] = (tot, total)
            for c, n in zip(MGT, mgt):
                checks[f'MD/MS {label} | {c}-MGT'] = (mcol[c], n)
            checks[f'MD/MS {label} | MGT Total'] = (mtot, mtotal)
            continue
        course = COURSES[name]
        row_sum = 0
        for c, s in zip(COLS, cells):
            n, cats = cell(s)
            if sum(cats.values()) != n:
                if (label, c, name) not in MISPRINTS:
                    raise SystemExit(f'{label} {c} {name}: count {n} but categories {dict(cats)}')
                cats = collections.Counter({'': n})
            elif (label, c, name) in MISPRINTS:
                raise SystemExit(f'{label} {c} {name}: listed as a misprint but adds up')
            add(COLLEGES[c], course, quota, 'mdms', cats)
            col[c] += n; row_sum += n
        if row_sum != total:
            raise SystemExit(f'{label} {name}: colleges add to {row_sum}, printed Total {total}')
        if sum(mgt) != mtotal:
            raise SystemExit(f'{label} {name}: MGT columns add to {sum(mgt)}, printed {mtotal}')
        for c, n in zip(MGT, mgt):
            add(COLLEGES[c], course, mquota, 'mdms', collections.Counter({'': n}) if n else {})
            mcol[c] += n
        tot += row_sum; mtot += mtotal

# ── Post-MBBS Diploma ──
gcol, dsum = collections.Counter(), 0
for line in DIPLOMA_ROWS.strip().splitlines():
    name, cells, total = [x.strip() for x in line.split('|')]
    row_sum = 0
    for part in cells.split(';'):
        h, lst = [x.strip() for x in part.split('=', 1)]
        if h not in DIP_COLS:
            raise SystemExit(f'unknown diploma hospital {h!r}')
        cats = categories(lst)
        if sum(cats.values()) != DIP_COUNTS.get((name, h), 1):
            raise SystemExit(f'diploma {name} {h}: printed count vs categories {dict(cats)}')
        add(HOSPITALS[h], DIPLOMA[name], 'Diploma Quota', 'diploma', cats)
        gcol[h] += sum(cats.values()); row_sum += sum(cats.values())
    if row_sum != int(total):
        raise SystemExit(f'diploma {name}: hospitals add to {row_sum}, printed Total {total}')
    dsum += row_sum
for h in DIP_COLS:
    checks[f'Diploma | {h}'] = (gcol[h], DIP_GRAND[h])
checks['Diploma | Grand Total'] = (dsum, DIP_GRAND_TOTAL)

# ── Post-MBBS DNB ──
ncol, nsum = collections.Counter(), 0
for line in DNB_ROWS.strip().splitlines():
    f = [x.strip() for x in line.split('|')]
    if f[0] == 'Grand Total':
        for h, v in zip(DNB_COLS, f[1:4]):
            checks[f'DNB | {h}'] = (ncol[h], int(v))
        checks['DNB | Grand Total'] = (nsum, int(f[4]))
        continue
    row_sum = 0
    for h, s in zip(DNB_COLS, f[1:4]):
        n, cats = cell(s)
        if sum(cats.values()) != n:
            raise SystemExit(f'DNB {f[0]} {h}: count {n} but categories {dict(cats)}')
        add(HOSPITALS[h], DNB_COURSES[f[0]], 'DNB Quota', 'dnb', cats)
        ncol[h] += n; row_sum += n
    if row_sum != int(f[4]):
        raise SystemExit(f'DNB {f[0]}: colleges add to {row_sum}, printed Total {f[4]}')
    nsum += row_sum

# merge repeats (same college × course × quota × category)
agg = collections.OrderedDict()
for x in rows:
    k = (x['college'], x['course'], x['quota'], x['category'])
    if k in agg:
        agg[k]['seats'] += x['seats']
    else:
        agg[k] = dict(x)
rows = list(agg.values())

# 2025 quotas: 'Government Quota' is a prefix of 'Government Quota-Inservice' (same for Management) → '$' = exact
FAMILY = {'State Quota': ('Government Quota$',), 'In-service Quota': ('Government Quota-Inservice',),
          'Management Quota': ('Management Quota$',), 'Management Quota (In-service)': ('Management Quota-Inservice',),
          'Diploma Quota': ('Government Quota$', 'Government Quota-Inservice'),   # 2025 diplomas: direct + in-service
          'DNB Quota': ('DNB',)}
HORIZONTAL = {'GC': ('GCH', 'GC'), 'ES': ('ES',), 'PwD': ('PH',)}   # 2025: GCH/GC green card, ES ex-serviceman, PH


def cat_match(x):
    if not x['category']:
        return ()
    base, _, sub = x['category'].partition('-')
    return HORIZONTAL.get(sub, ()) + (base,)


cuts = load_cuts(CUTS, 'Odisha')
out = build(rows, cuts, 'Odisha', 'OD', lambda q: FAMILY[q], cat_match)
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
for k, why in MISPRINTS.items():
    print('   PDF misprint kept without category:', ' / '.join(k), '—', why)