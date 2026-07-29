"""The entitlement engine — the single place that answers "is this doctor allowed?".

Every gate on goocampus.in goes through `check(conn, user_id, feature_code, item)`.
Nothing else should read pg_plan_features directly, so that when the founder changes
a number in the admin, every surface changes with it.

    allowed, info = check(conn, user_id, 'pdf_documents', item_key='42')
    if allowed:
        consume(conn, user_id, 'pdf_documents', item_key='42')

`check` never writes; `consume` never decides. Keeping them apart means a failed
download can't silently burn a slot, and a preview can ask "would this be allowed?"
without charging for it.

QUOTA SEMANTICS
    off        -> blocked outright
    unlimited  -> always allowed
    limited    -> boolean feature: allowed (the row's presence IS the grant)
                  quota feature:   allowed while used < limit_value
                                   limit 0 means the plan includes none of it

A doctor with no subscription falls back to the plan marked plan_kind='free'. That
is deliberate: an anonymous-but-logged-in user is a free user, not a blocked one.
"""
import logging
from datetime import datetime


_LIFETIME = 'lifetime'


def _period_key(reset_period, sub=None):
    """Which bucket does today's usage count against."""
    now = datetime.utcnow()
    if reset_period == 'monthly':
        return now.strftime('%Y-%m')
    if reset_period == 'daily':
        return now.strftime('%Y-%m-%d')
    if reset_period == 'plan_period' and sub and sub.get('id'):
        # Counted per purchase: renewing the plan hands back a fresh allowance,
        # which is what "3 sessions included" has to mean on a repeat purchase.
        return f"sub{sub['id']}"
    return _LIFETIME


def get_features(conn):
    """The catalogue, keyed by code. Small table, read often — fine to re-read."""
    try:
        rows = conn.execute(
            "SELECT * FROM pg_features WHERE COALESCE(is_active,1)=1 "
            "ORDER BY sort_order, id").fetchall()
        return {r['code']: dict(r) for r in rows}
    except Exception as e:
        conn.rollback()
        logging.error("entitlements.get_features: %s", e)
        return {}


def active_subscription(conn, user_id):
    """The doctor's live paid subscription, or None (= they're on the free plan).

    Expiry is evaluated here rather than by a nightly job, so a plan that ran out
    at midnight is genuinely inactive the next time they click — no cron to miss.
    """
    if not user_id:
        return None
    try:
        row = conn.execute(
            "SELECT s.*, p.code AS plan_code, p.name AS plan_name, "
            "       p.plan_kind, p.billing_period "
            "FROM pg_subscriptions s JOIN pg_plans p ON p.id = s.plan_id "
            "WHERE s.user_id = ? AND s.status = 'active' "
            "  AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP) "
            "  AND COALESCE(p.is_active,1) = 1 "
            "ORDER BY s.expires_at DESC NULLS FIRST, s.id DESC LIMIT 1",
            (user_id,)).fetchone()
        return dict(row) if row else None
    except Exception as e:
        conn.rollback()
        logging.error("entitlements.active_subscription: %s", e)
        return None


def free_plan(conn):
    try:
        row = conn.execute(
            "SELECT * FROM pg_plans WHERE plan_kind = 'free' "
            "AND COALESCE(is_active,1)=1 ORDER BY sort_order, id LIMIT 1").fetchone()
        return dict(row) if row else None
    except Exception as e:
        conn.rollback()
        logging.error("entitlements.free_plan: %s", e)
        return None


def effective_plan(conn, user_id):
    """(plan_row, subscription_row_or_None) — what this doctor is actually on."""
    sub = active_subscription(conn, user_id)
    if sub:
        try:
            row = conn.execute("SELECT * FROM pg_plans WHERE id = ?",
                               (sub['plan_id'],)).fetchone()
            if row:
                return dict(row), sub
        except Exception:
            conn.rollback()
    return free_plan(conn), None


def plan_feature_map(conn, plan_id):
    if not plan_id:
        return {}
    try:
        rows = conn.execute(
            "SELECT feature_code, value_type, limit_value, note "
            "FROM pg_plan_features WHERE plan_id = ?", (plan_id,)).fetchall()
        return {r['feature_code']: dict(r) for r in rows}
    except Exception as e:
        conn.rollback()
        logging.error("entitlements.plan_feature_map: %s", e)
        return {}


def _used(conn, user_id, feature_code, period_key, distinct):
    """How much of the allowance is gone.

    distinct -> count DISTINCT items unlocked (3 different PDFs)
    else     -> sum of hits (10 searches run)
    """
    try:
        col = "COUNT(*)" if distinct else "COALESCE(SUM(hits),0)"
        row = conn.execute(
            f"SELECT {col} AS n FROM pg_usage_items "
            "WHERE user_id = ? AND feature_code = ? AND period_key = ?",
            (user_id, feature_code, period_key)).fetchone()
        return int(row['n'] or 0) if row else 0
    except Exception as e:
        conn.rollback()
        logging.error("entitlements._used: %s", e)
        return 0


def check(conn, user_id, feature_code, item_key=None):
    """Read-only decision. Returns (allowed: bool, info: dict).

    info carries everything a UI needs to explain itself — limit, used, remaining,
    the plan name and, when blocked, a reason code the front-end can turn into the
    right upgrade prompt.
    """
    features = get_features(conn)
    feat = features.get(feature_code)
    plan, sub = effective_plan(conn, user_id)
    info = {
        'feature': feature_code,
        'plan': (plan or {}).get('code') or 'free',
        'plan_name': (plan or {}).get('name') or 'Free',
        'unit': (feat or {}).get('unit') or 'quota',
        'limit': None, 'used': 0, 'remaining': None,
        'unlimited': False, 'reason': '',
    }
    if not feat:
        # An unknown code must not silently unlock something. Fail closed.
        info['reason'] = 'unknown_feature'
        return False, info
    if not plan:
        info['reason'] = 'no_plan'
        return False, info

    grant = plan_feature_map(conn, plan['id']).get(feature_code)
    if not grant or grant.get('value_type') == 'off':
        info['reason'] = 'not_in_plan'
        return False, info

    if grant.get('value_type') == 'unlimited':
        info['unlimited'] = True
        return True, info

    # value_type == 'limited'
    if feat['unit'] == 'boolean':
        return True, info            # presence of the grant IS the permission

    limit = grant.get('limit_value')
    if limit is None:
        info['unlimited'] = True     # a quota with no number = uncapped
        return True, info

    limit = int(limit)
    period = _period_key(feat.get('reset_period') or _LIFETIME, sub)
    distinct = bool(feat.get('resource_kind'))
    used = _used(conn, user_id, feature_code, period, distinct)
    info.update({'limit': limit, 'used': used,
                 'remaining': max(0, limit - used), 'period_key': period})

    if limit <= 0:
        info['reason'] = 'not_included'
        return False, info

    # Something already unlocked stays unlocked forever — re-opening the same PDF
    # must never cost a second slot, or the quota feels broken to the doctor.
    if distinct and item_key:
        try:
            row = conn.execute(
                "SELECT 1 FROM pg_usage_items WHERE user_id = ? AND feature_code = ? "
                "AND period_key = ? AND item_key = ? LIMIT 1",
                (user_id, feature_code, period, str(item_key))).fetchone()
            if row:
                info['already_unlocked'] = True
                return True, info
        except Exception:
            conn.rollback()

    if used >= limit:
        info['reason'] = 'limit_reached'
        return False, info
    return True, info


def consume(conn, user_id, feature_code, item_key=None, hits=1):
    """Record usage. Caller must have had `check` say yes. Commits nothing —
    the caller owns the transaction, same as everywhere else in the portal."""
    if not user_id:
        return
    features = get_features(conn)
    feat = features.get(feature_code)
    if not feat or feat.get('unit') == 'boolean':
        return
    _, sub = effective_plan(conn, user_id)
    period = _period_key(feat.get('reset_period') or _LIFETIME, sub)
    key = str(item_key) if item_key else ''
    try:
        conn.execute(
            "INSERT INTO pg_usage_items (user_id, feature_code, period_key, item_key, hits) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT (user_id, feature_code, period_key, item_key) DO UPDATE "
            "SET hits = pg_usage_items.hits + EXCLUDED.hits, "
            "    last_used_at = CURRENT_TIMESTAMP",
            (user_id, feature_code, period, key, int(hits or 1)))
    except Exception as e:
        conn.rollback()
        logging.error("entitlements.consume: %s", e)


def summary(conn, user_id):
    """Everything the goocampus.in dashboard needs in one call: the plan, when it
    ends, and every feature with its limit/used/remaining. One round-trip so the
    front-end never has to ask per feature."""
    plan, sub = effective_plan(conn, user_id)
    features = get_features(conn)
    grants = plan_feature_map(conn, (plan or {}).get('id'))
    out = {}
    for code, feat in features.items():
        allowed, info = check(conn, user_id, code)
        out[code] = {
            'name': feat['name'],
            'unit': feat['unit'],
            'allowed': allowed,
            'limit': info.get('limit'),
            'used': info.get('used'),
            'remaining': info.get('remaining'),
            'unlimited': info.get('unlimited'),
            'reason': info.get('reason'),
            'note': (grants.get(code) or {}).get('note') or '',
        }
    return {
        'plan': {
            'code': (plan or {}).get('code') or 'free',
            'name': (plan or {}).get('name') or 'Free',
            'kind': (plan or {}).get('plan_kind') or 'free',
        },
        'subscription': {
            'active': bool(sub),
            'expires_at': (sub or {}).get('expires_at').isoformat()
                          if sub and sub.get('expires_at') else None,
            'status': (sub or {}).get('status') or 'free',
        },
        'features': out,
    }
