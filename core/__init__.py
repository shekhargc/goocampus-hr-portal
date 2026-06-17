"""
core/ — shared helpers used across all sections.

This folder will hold:
- auth.py         (login_required, admin_required, client_required decorators)
- helpers.py      (hash_password, allowed_file, get_user, etc.)
- filters.py      (Jinja filters: format_date, format_reg)
- leave_calc.py   (leave-balance math used by HR routes)
- notifications.py (internal _notify_* helpers)

See REFACTOR_PLAN.md for the migration plan.
Currently empty — population happens in subsequent refactor steps.
"""
