"""
core/registration.py — per-pathway registration number generator.

GooCampus uses different reg-number formats per pathway so each pathway is
visually distinct at a glance:

  PLAB (UK / PLAB Pathway, UK PGCP)   GCUKIP/<FY>/<NNN>   e.g. GCUKIP/26-27/001
  Australia (AMC, AUSIP)              GCAUSIP/<FY>/<NNN>  e.g. GCAUSIP/26-27/001
  UAE                                 GCUAEIP/<FY>/<NNN>
  Consulting                          GCCONS/<FY>/<NNN>

Conventions:
  - <FY> is the Indian financial year (Apr-Mar) as a two-digit pair, e.g. 26-27.
  - <NNN> is a 3-digit zero-padded sequence that resets each FY per pathway.
  - Sequence is computed by looking at the latest registration_number that
    matches the prefix+FY pattern, regardless of which `pathway` column value
    a row carries (the format itself is canonical).

The product -> pathway mapping is keyword-based on the product name so the
generator works even when a new product is added through the /products UI
without a code deploy. Unknown / unmatched products fall back to PLAB
(historical default) so nothing breaks.
"""

from datetime import date
import re


# Pathway -> reg prefix. Source of truth.
# S-3 (2026-06-03): consulting prefix changed GCCONS -> GCCSS to match the
# user's existing Zoho data (GC Consulting Standard Service). Any future
# consulting signups now get GCCSS/<FY>/<NNN> consistent with imported rows.
PATHWAY_REG_PREFIX = {
    'plab': 'GCUKIP',
    'australia': 'GCAUSIP',
    'uae': 'GCUAEIP',
    'consulting': 'GCCSS',
}


def pathway_from_product_name(product_name):
    """Infer pathway from a free-text product name.

    Keyword match is case-insensitive and uses the most specific match first
    (e.g. a product named 'Australia AMC' matches 'australia' before falling
    through to anything else).

    Returns the pathway slug ('plab' / 'australia' / 'uae' / 'consulting').
    Falls back to 'plab' for unknown / empty names so existing behaviour
    is preserved when the column is missing or a new product hasn't been
    classified yet.
    """
    n = (product_name or '').upper()
    if not n:
        return 'plab'
    # Australia / AMC pathway
    if 'AUSTRALIA' in n or 'AMC' in n or 'AUSIP' in n or n.startswith('AUS '):
        return 'australia'
    # UAE pathway
    if 'UAE' in n:
        return 'uae'
    # Standard Consulting
    if 'CONSULT' in n:
        return 'consulting'
    # Default — covers UK / PLAB / PGCP / unknown
    return 'plab'


def indian_financial_year(today=None):
    """Return Indian financial year as 'YY-YY' (Apr 1 -> Mar 31).

    Examples (assuming Indian FY):
      2026-05-31  ->  '26-27'  (FY 2026-27 is in progress)
      2026-02-15  ->  '25-26'
      2026-04-01  ->  '26-27'
    """
    today = today or date.today()
    if today.month >= 4:
        start = today.year
        end = today.year + 1
    else:
        start = today.year - 1
        end = today.year
    return f"{start % 100:02d}-{end % 100:02d}"


def _next_sequence(conn, prefix, fy):
    """Return the next 3-digit sequence number for prefix+FY.

    Looks at the highest existing registration_number matching the pattern
    prefix/fy/<NNN> across BOTH client_registrations (v2) and plab_clients
    (legacy PLAB table — only relevant for the GCUKIP prefix, but querying
    it for other prefixes is cheap and returns no rows).
    """
    pattern = f"{prefix}/{fy}/%"
    max_seq = 0

    for table in ('client_registrations', 'plab_clients'):
        try:
            rows = conn.execute(
                f"SELECT registration_number FROM {table} WHERE registration_number LIKE ?",
                (pattern,),
            ).fetchall()
        except Exception:
            # Table doesn't exist on this environment — skip.
            continue
        for r in rows:
            rn = r['registration_number'] if hasattr(r, 'keys') else r[0]
            m = re.search(r'/(\d+)\s*$', rn or '')
            if m:
                try:
                    max_seq = max(max_seq, int(m.group(1)))
                except ValueError:
                    pass

    return max_seq + 1


def next_registration_number(conn, product_name, today=None):
    """Generate the next registration number for a product.

    Args:
        conn: a db connection (already open) — used for sequence lookup.
        product_name: the product's name (free text from products_services).
        today: optional date for testing.

    Returns:
        str — e.g. 'GCUKIP/26-27/042' or 'GCAUSIP/26-27/001'.

    Raises:
        Nothing — falls back to PLAB prefix for unknown products.
    """
    pathway = pathway_from_product_name(product_name)
    prefix = PATHWAY_REG_PREFIX.get(pathway, 'GCUKIP')
    fy = indian_financial_year(today)
    seq = _next_sequence(conn, prefix, fy)
    return f"{prefix}/{fy}/{seq:03d}"
