"""College shared utilities — currency conversion + slug. From app.py."""
import time, re, logging
import requests
import requests as http_requests

_currency_cache = {'rates': {}, 'last_fetch': 0}


def _make_slug(name):
    """Generate URL-friendly slug from college name."""
    import re
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


def _currency_sym(code):
    """Return currency symbol for a code, or the code itself as fallback."""
    return CURRENCY_SYMBOLS.get((code or 'USD').upper(), code or '$')


def _get_exchange_rates():
    """Fetch exchange rates with 6-hour caching."""
    now = _time.time()
    if _currency_cache['rates'] and (now - _currency_cache['last_fetch']) < 21600:
        return _currency_cache['rates']
    try:
        import urllib.request
        import json as _json
        url = "https://open.er-api.com/v6/latest/USD"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = _json.loads(resp.read().decode())
            if data.get('result') == 'success':
                _currency_cache['rates'] = data['rates']
                _currency_cache['last_fetch'] = now
                logging.info(f"Currency rates refreshed: INR={data['rates'].get('INR')}")
    except Exception as e:
        logging.error(f"Currency fetch error: {e}")
        if not _currency_cache['rates']:
            _currency_cache['rates'] = {'INR': 85.0, 'RUB': 0.011 * 85.0, 'USD': 1.0}
    return _currency_cache['rates']


def _to_inr(amount, currency, rates):
    """Convert amount in given currency to INR using live rates.
    Rates dict is from open.er-api (base USD): rates[X] = how many X per 1 USD.
    So 1 unit of X in INR = INR_per_USD / X_per_USD."""
    if not amount or not rates:
        return 0
    currency = (currency or 'INR').upper()
    inr_rate = rates.get('INR', 85.0)
    if currency == 'INR':
        return float(amount)
    elif currency == 'USD':
        return float(amount) * inr_rate
    else:
        # Generic: 1 unit of currency = INR_per_USD / currency_per_USD
        cur_rate = rates.get(currency)
        if cur_rate and cur_rate > 0:
            return float(amount) * (inr_rate / cur_rate)
        return float(amount)
