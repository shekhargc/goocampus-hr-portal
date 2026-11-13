"""Who may take which mock.

  - goocampus.in team members (pg_users.is_team_member = 1): every published mock — dry runs, never ranked;
  - the free sample mock: every logged-in doctor;
  - full mocks: a package covering that mock's position (Starter = first 5, Standard = 15, Pro = 30);
  - subject tests: Standard / Pro;  mini tests: Pro.
Once an attempt is open the doctor can always resume it, and results stay viewable, whatever happens to the
package later.
"""
from exam_engine import packages as K

MESSAGES = {
    'package_required': 'This mock is part of a mock-test package. Buy a package to unlock it.',
    'upgrade_required': 'Your package doesn\'t include this mock. Upgrade your package to unlock it.',
    'not_published': 'This mock is not available yet.',
}


def context(conn, user, tenant_id, exam_code):
    """Everything can_take needs, computed once per request."""
    return {'ent': K.entitlement(conn, user['id'], tenant_id, exam_code),
            'positions': K.full_mock_positions(conn, tenant_id, exam_code)}


def can_take(conn, user, paper, ctx=None):
    """→ (allowed, via, reason). via: team | free_sample | package."""
    if paper.get('status') != 'published':
        return False, None, 'not_published'
    try:
        # team first: their dry runs (even on the free sample) must never enter the doctors' ranking
        if int(user.get('is_team_member') or 0) == 1:
            return True, 'team', None
    except (TypeError, ValueError):
        pass
    if paper.get('is_free_sample'):
        return True, 'free_sample', None
    ctx = ctx or context(conn, user, paper['tenant_id'], paper['exam_code'])
    ent = ctx['ent']
    kind = paper.get('kind')
    if kind == 'full':
        pos = ctx['positions'].get(paper['id'])
        if pos and pos <= ent['full_mocks']:
            return True, 'package', None
    elif kind == 'subject' and ent['subject_tests']:
        return True, 'package', None
    elif kind == 'mini' and ent['mini_tests']:
        return True, 'package', None
    return False, None, ('upgrade_required' if ent['packages'] else 'package_required')
