"""NEET-PG counselling authorities registry + per-authority document categories
(founder 2026-10-06).

One canonical list shared by the admin hub (/admin/pg/authorities) and the public
APIs (/api/pg/authorities, /api/pg/authority/<code>). The goocampus.in dashboard shows
a section per authority that has content — registration documents, annexure/format
files, fee-structure files, the seat matrix, and news. Only populated authorities are
surfaced to doctors.

Codes are stable slugs — never renumber; the frontend + stored docs key off them.
Source: reference list of the 35 counselling authorities (MCC + 34 state/UT bodies).
"""

# (code, display name, state/UT label, homepage, kind)
AUTHORITIES = [
    ("mcc",        "MCC — All India (AIQ)",                 "All India",          "https://mcc.nic.in",                          "central"),
    ("aniims",     "ANIIMS",                                "Andaman & Nicobar",  "https://andssw1.and.nic.in/aniims",           "state"),
    ("ntruhs",     "NTRUHS",                                "Andhra Pradesh",     "https://drntr.uhsap.in",                      "state"),
    ("arunachal",  "Dir. Higher & Tech Education",          "Arunachal Pradesh",  "https://dmetrap.in",                          "state"),
    ("dme_assam",  "DME Assam",                             "Assam",              "https://dme.assam.gov.in",                    "state"),
    ("bceceb",     "BCECEB",                                "Bihar",              "https://bceceboard.bihar.gov.in",             "state"),
    ("gmch_chd",   "GMCH Chandigarh",                       "Chandigarh",         "https://gmch.gov.in",                         "state"),
    ("dme_cg",     "DME Chhattisgarh",                      "Chhattisgarh",       "https://cgdme.co.in",                         "state"),
    ("dmhs_dnh",   "DMHS DNH",                              "Dadra & Nagar Haveli", "https://vbch.dnh.nic.in",                   "state"),
    ("ggsipu",     "GGSIPU",                                "Delhi",              "https://ipu.ac.in",                           "state"),
    ("dte_goa",    "DTE Goa",                               "Goa",                "https://dte.goa.gov.in",                      "state"),
    ("acpmec",     "ACPMEC",                                "Gujarat",            "https://medadmgujarat.org",                   "state"),
    ("dmer_hr",    "DMER Haryana",                          "Haryana",            "https://dmer.haryana.gov.in",                 "state"),
    ("amru_hp",    "AMRU",                                  "Himachal Pradesh",   "https://amruhp.ac.in",                        "state"),
    ("jk_bopee",   "J&K BOPEE",                             "Jammu & Kashmir",    "https://jkbopee.gov.in",                      "state"),
    ("jceceb",     "JCECEB",                                "Jharkhand",          "https://jceceb.jharkhand.gov.in",             "state"),
    ("kea",        "KEA — Karnataka Examinations Authority","Karnataka",          "https://cetonline.karnataka.gov.in/kea",      "state"),
    ("cee_kerala", "CEE Kerala",                            "Kerala",             "https://cee.kerala.gov.in",                   "state"),
    ("dme_mp",     "DME Madhya Pradesh",                    "Madhya Pradesh",     "https://dme.mponline.gov.in",                 "state"),
    ("cetcell_mh", "CET CELL",                              "Maharashtra",        "https://cetcell.mahacet.org",                 "state"),
    ("dhs_manipur","DHS Manipur",                           "Manipur",            "https://manipurhealthdirectorate.mn.gov.in",  "state"),
    ("rims_imphal","RIMS Imphal — common PG counselling (7 NE states)", "Manipur", "https://rims.edu.in/rimsman/category/admission/", "state"),
    ("neigrihms",  "Meghalaya — no own PG counselling (MCC + RIMS Imphal)", "Meghalaya", "https://meghealth.gov.in",       "state"),
    ("dict_mz",    "Mizoram H&TE — State Selection Board",  "Mizoram",            "https://dhte.mizoram.gov.in",                 "state"),
    ("dte_nagaland","DTE Nagaland",                         "Nagaland",           "",                                            "state"),
    ("ojee",       "DMET Odisha (PG Medical counselling)",  "Odisha",             "https://dmetodisha.in",                       "state"),
    ("centac",     "CENTAC",                                "Puducherry",         "https://centacpuducherry.in",                 "state"),
    ("bfuhs",      "BFUHS",                                 "Punjab",             "https://bfuhs.ac.in",                         "state"),
    ("ruhs",       "RUHS",                                  "Rajasthan",          "https://ruhsraj.org",                         "state"),
    ("smu_sikkim", "Sikkim Manipal University",             "Sikkim",             "https://smu.edu.in",                          "state"),
    ("dmer_tn",    "DMER Tamil Nadu",                       "Tamil Nadu",         "https://tnmedicalselection.net",              "state"),
    ("knruhs",     "KNRUHS",                                "Telangana",          "https://knruhs.telangana.gov.in",             "state"),
    ("dme_tripura","DME Tripura",                           "Tripura",            "https://dme.tripura.gov.in",                  "state"),
    ("dmetup",     "DMET Uttar Pradesh",                    "Uttar Pradesh",      "https://upneet.gov.in",                       "state"),
    ("hnbumu",     "HNBUMU",                                "Uttarakhand",        "https://hnbumu.ac.in",                        "state"),
    ("wbmcc",      "WBMCC",                                 "West Bengal",        "https://wbmcc.nic.in",                        "state"),
]

_BY_CODE = {a[0]: a for a in AUTHORITIES}


# An authority whose counselling serves doctors of several states (founder 2026-10-13): RIMS Imphal
# runs one State Level PG Counselling for Arunachal, Manipur, Meghalaya, Mizoram, Nagaland, Sikkim,
# Tripura (RIMS circular ACADEM/ADMN/PG/1/2025-RIMS). `covers_states` lets the website show it to all.
COVERS_STATES = {
    "rims_imphal": ["Arunachal Pradesh", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Sikkim", "Tripura"],
}


def as_dict(a):
    return {"code": a[0], "name": a[1], "state": a[2], "homepage": a[3], "kind": a[4],
            "covers_states": COVERS_STATES.get(a[0], [a[2]])}


# Not a counselling authority for our doctors (founder 2026-10-13): Delhi has no state PG counselling —
# all Delhi MD/MS seats (incl. DU + IP University quotas) are counselled by MCC. GGSIPU's own PGMC
# counselling is only a handful of seats for its own graduates. Kept here (codes never reused) but
# hidden from every list, dropdown, API and the news scraper.
REMOVED = {"ggsipu"}


def all_authorities():
    return [as_dict(a) for a in AUTHORITIES if a[0] not in REMOVED]


def get_authority(code):
    a = _BY_CODE.get((code or "").strip().lower())
    return as_dict(a) if a and a[0] not in REMOVED else None


# The per-authority document buckets (founder 2026-10-06; brochure added on review).
# A document may carry a file, a typed list/details (body_text), or both — e.g. a
# "Registration Documents" entry is often a numbered checklist typed in, not a PDF.
DOC_CATEGORIES = [
    ("brochure",          "Counselling Brochure / Bulletin / User Manual"),
    ("registration",      "Registration Documents"),
    ("formats_annexures", "Formats & Annexures"),
    ("fee_structure",     "Fee Structure"),
    ("seat_matrix",       "Seat Matrix"),
    ("merit_list",        "Merit List"),                  # 2026-10-13
    ("results",           "Results"),                     # round-wise allotment results (2026-10-13)
    ("other",             "Other / Notifications"),
]
_CAT_CODES = {c for c, _ in DOC_CATEGORIES}
_CAT_LABEL = {c: l for c, l in DOC_CATEGORIES}


def category_label(code):
    return _CAT_LABEL.get((code or "").strip(), "Other / Notifications")


def valid_category(code):
    return (code or "").strip() in _CAT_CODES
