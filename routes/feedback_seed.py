"""
routes/feedback_seed.py — canonical question spec for the client feedback
forms, transcribed verbatim from the founder's live Fillout forms
(2026-07-02). Used to seed the feedback_forms / feedback_questions tables.

IMPORTANT anonymity rule: the original Fillout forms include a "Your Name"
question. We deliberately OMIT it — identity is tracked ONLY via the unique
per-send token linked to the registration number, so the client can give
open feedback without putting their name.

Question tuple shape:
    (qtype, text, required, options_or_scale)
  qtype:  'star'   -> 5-star rating
          'scale'  -> 0-10 recommend scale (NPS style)
          'choice' -> single-choice; options_or_scale = list of choices
          'short'  -> single-line text
          'long'   -> paragraph text
  options_or_scale: list[str] for 'choice'; dict for 'scale'
          {'left': .., 'right': ..}; else None.

`match_stages` lists the ops `current_stage` values a form applies to, so
the centralised "send by stage" screen can list the right clients. Pathway
uses the same slugs as plab_clients.pathway.
"""

_NPS = {'left': "Wouldn't recommend", 'right': 'Highly recommend'}
_YESNO = ['Yes', 'No']

FEEDBACK_FORM_SEED = [
    # ─────────────── UK PGCP (pathway = plab) ───────────────
    {
        'pathway': 'plab', 'stage_key': 'english',
        'title': 'UK PGCP — English Stage',
        'match_stages': ['English Stage'],
        'questions': [
            ('star',  'How satisfied were you with the speed and efficiency of our service?', True, None),
            ('star',  'How satisfied were you with how quickly our team responded to you?', True, None),
            ('star',  'How satisfied were you with how clearly our team communicated with you?', True, None),
            ('star',  'How satisfied were you with what we delivered compared to what we promised?', True, None),
            ('choice', "Are there any issues or concerns that you'd like us to address immediately?", True, _YESNO),
            ('short', 'What is the main reason for your score?', False, None),
            ('scale', 'How likely are you to recommend our services to others?', True, _NPS),
        ],
    },
    {
        'pathway': 'plab', 'stage_key': 'plab1',
        'title': 'UK PGCP — PLAB 1 Stage',
        'match_stages': ['PLAB 1 Stage'],
        'questions': [
            ('star',  'How satisfied were you with the speed and efficiency of our service?', True, None),
            ('star',  'How satisfied were you with how quickly our team responded to you?', True, None),
            ('star',  'How satisfied were you with how clearly our team communicated with you?', True, None),
            ('star',  'How satisfied were you with what we delivered compared to what we promised?', True, None),
            ('choice', "Are there any issues or concerns that you'd like us to address immediately?", True, _YESNO),
            ('short', 'Any additional comments or feedback?', False, None),
            ('scale', 'How likely are you to recommend our services to others?', True, _NPS),
        ],
    },
    {
        'pathway': 'plab', 'stage_key': 'plab2_job',
        'title': 'UK PGCP — PLAB 2 & Job Stage',
        'match_stages': ['PLAB 2 Stage', 'Job Stage', 'Job by GC', 'Job by Own'],
        'questions': [
            ('star',  'How satisfied were you with the speed and efficiency of our service?', True, None),
            ('star',  'How satisfied were you with how quickly our team responded to you?', True, None),
            ('star',  'How satisfied were you with how clearly our team communicated with you?', True, None),
            ('star',  'How satisfied were you with what we delivered compared to what we promised?', True, None),
            ('choice', "Are there any issues or concerns that you'd like us to address immediately?", True, _YESNO),
            ('short', 'Any additional comments or feedback?', False, None),
            ('scale', 'How likely are you to recommend our services to others?', True, _NPS),
        ],
    },
    # ─────────────── AUS PGCP (pathway = australia) ───────────────
    {
        'pathway': 'australia', 'stage_key': 'amc1',
        'title': 'AUS PGCP — AMC 1 Stage',
        'match_stages': ['AMC 1'],
        'questions': [
            ('short', 'Which other materials have you purchased apart from the ones provided by us?', False, None),
            ('choice', 'Were the study materials and resources provided adequate for your preparation?', True, _YESNO),
            ('star',  'How would you rate the timeliness & efficiency of our services?', True, None),
            ('star',  'How would you rate the effectiveness of your tutor in helping you prepare for the AMC?', True, None),
            ('star',  'Did our team members communicate clearly and effectively with you?', True, None),
            ('star',  'Did we meet your expectations in terms of delivering the services?', True, None),
            ('choice', "Are there any issues or concerns that you'd like us to address immediately?", True, _YESNO),
            ('short', 'Any additional comments or feedback?', False, None),
            ('scale', 'How likely are you to recommend our services to others?', True, _NPS),
        ],
    },
    {
        'pathway': 'australia', 'stage_key': 'amc2',
        'title': 'AUS PGCP — AMC 2 Stage',
        'match_stages': ['AMC 2'],
        'questions': [
            ('star',  'How would you rate the timeliness & efficiency of our services?', True, None),
            ('star',  'Were our team members responsive to your needs & requests?', True, None),
            ('star',  'Did our team members communicate clearly and effectively with you?', True, None),
            ('star',  'Did we meet your expectations in terms of delivering the services?', True, None),
            ('choice', "Are there any issues or concerns that you'd like us to address immediately?", True, _YESNO),
            ('short', 'Any additional comments or feedback?', False, None),
            ('scale', 'How likely are you to recommend our services to others?', True, _NPS),
        ],
    },
    # ─────────────── Standard Consulting (pathway = consulting) ───────────────
    {
        'pathway': 'consulting', 'stage_key': 'consulting',
        'title': 'Standard Consulting',
        'match_stages': ['AMC 1', 'AMC 2', 'English Stage', 'Job Stage'],
        'questions': [
            ('star',  'How would you rate the timeliness & efficiency of our services?', True, None),
            ('star',  'Were our team members responsive to your needs & requests?', True, None),
            ('star',  'Did our team members communicate clearly and effectively with you?', True, None),
            ('star',  'Did we meet your expectations in terms of delivering the services?', True, None),
            ('choice', "Are there any issues or concerns that you'd like us to address immediately?", True, _YESNO),
            ('short', 'Any additional comments or feedback?', False, None),
            ('scale', 'How likely are you to recommend our services to others?', True, _NPS),
        ],
    },
    # ─────────────── Portfolio Pathway (pathway = portfolio) ───────────────
    {
        'pathway': 'portfolio', 'stage_key': 'portfolio',
        'title': 'Portfolio Pathway',
        'match_stages': [],  # all portfolio clients (no stage filter)
        'questions': [
            ('star',  'How satisfied were you with the speed and efficiency of our service?', True, None),
            ('star',  'How satisfied were you with how quickly our team responded to you?', True, None),
            ('star',  'How satisfied were you with how clearly our team communicated with you?', True, None),
            ('star',  'How satisfied were you with what we delivered compared to what we promised?', True, None),
            ('choice', "Are there any issues or concerns that you'd like us to address immediately?", True, _YESNO),
            ('short', 'What is the main reason for your score?', False, None),
            ('scale', 'How likely are you to recommend our services to others?', True, _NPS),
        ],
    },
]
