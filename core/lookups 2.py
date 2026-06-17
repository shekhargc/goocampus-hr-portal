"""
core/lookups.py — pathway-scoped reads from the lookup_options table.

GooCampus has a `lookup_options` table that stores dropdown choices for
forms (exam names, status values, document types, etc.). With multi-pathway
support, the SAME category name can hold different values per pathway:

  category='exam_name', pathway='plab'        -> ["PLAB 1", "PLAB 2"]
  category='exam_name', pathway='australia'   -> ["AMC MCQ", "AMC Clinical", "OET"]

Any code that builds a dropdown for a pathway-specific page MUST go through
get_options_for_pathway(...) so it never accidentally shows PLAB exams to
Australia users (or vice versa).

User constraint locked 2026-05-31:
    "I'll go with B as long as you don't mix up the data and dropdown
    fields in certain sections."
"""

from typing import List, Dict, Any, Optional


def get_options_for_pathway(
    conn,
    category: str,
    pathway: str = 'plab',
    active_only: bool = True,
) -> List[Dict[str, Any]]:
    """Return dropdown options for one (category, pathway) scope.

    Args:
        conn: open DB connection.
        category: e.g. 'exam_name', 'gmc_license_status'.
        pathway: 'plab' / 'australia' / 'uae' / 'consulting'. Defaults to 'plab'.
        active_only: if True (default) only return rows where is_active = 1.

    Returns:
        List of dicts with keys: id, label, value, sort_order.
        Empty list if the (category, pathway) pair has no rows yet.
    """
    sql = (
        "SELECT id, label, value, sort_order "
        "FROM lookup_options "
        "WHERE category = ? AND pathway = ?"
    )
    params = [category, pathway]
    if active_only:
        sql += " AND is_active = 1"
    sql += " ORDER BY sort_order, label"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_options_values_for_pathway(conn, category, pathway='plab', active_only=True):
    """Convenience: return just the `value` strings (in display order).

    Useful when the caller only needs the strings to populate a <select>.
    """
    return [r['value'] for r in get_options_for_pathway(conn, category, pathway, active_only)]


def upsert_option_for_pathway(
    conn,
    category: str,
    label: str,
    value: str,
    pathway: str = 'plab',
    sort_order: int = 0,
    is_active: bool = True,
):
    """Insert or update a single lookup option scoped to a pathway.

    Use for Excel-driven seed scripts that populate per-pathway dropdowns.
    Idempotent — same (category, pathway, value) will update label / sort
    instead of inserting a duplicate.
    """
    existing = conn.execute(
        "SELECT id FROM lookup_options WHERE category = ? AND pathway = ? AND value = ?",
        (category, pathway, value),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE lookup_options SET label = ?, sort_order = ?, is_active = ? WHERE id = ?",
            (label, sort_order, 1 if is_active else 0, existing['id']),
        )
    else:
        conn.execute(
            "INSERT INTO lookup_options (category, pathway, label, value, sort_order, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (category, pathway, label, value, sort_order, 1 if is_active else 0),
        )


def all_categories_for_pathway(conn, pathway: str = 'plab') -> List[str]:
    """List every distinct category present for a pathway. Useful for admin UIs."""
    rows = conn.execute(
        "SELECT DISTINCT category FROM lookup_options WHERE pathway = ? ORDER BY category",
        (pathway,),
    ).fetchall()
    return [r['category'] for r in rows]
