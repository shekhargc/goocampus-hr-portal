"""Who may take which mock.

  - the free sample mock: every logged-in doctor;
  - goocampus.in team members (pg_users.is_team_member = 1): every published mock — for dry runs;
  - everything else: a purchased package — wired to plans/entitlements in step 7.
"""

MESSAGES = {
    'package_required': 'This mock is part of a mock-test package. Buy a package to unlock it.',
    'not_published': 'This mock is not available yet.',
}


def can_take(conn, user, paper):
    """→ (allowed, via, reason). via: free_sample | team | package."""
    if paper.get('status') != 'published':
        return False, None, 'not_published'
    if paper.get('is_free_sample'):
        return True, 'free_sample', None
    try:
        if int(user.get('is_team_member') or 0) == 1:
            return True, 'team', None
    except (TypeError, ValueError):
        pass
    # Step 7: packages (pg_plans / entitlements) decide here.
    return False, None, 'package_required'
