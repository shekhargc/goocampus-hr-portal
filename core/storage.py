"""
core/storage.py -- Cloudflare R2 object-storage client for client docs.

Replaces the BYTEA-in-Postgres approach (which filled the basic_1gb plan
on the 913-doc bulk import). Now Postgres only stores the R2 object key
in plab_client_documents.file_path; the file bytes live in R2.

Security model
==============
- R2 bucket is PRIVATE (no Public Development URL enabled).
- App reads / writes via S3-compatible API using account credentials
  loaded from Render env vars (never committed).
- File serving uses **presigned URLs** generated per-request:
    1. browser requests /operations/plab/doc/<id>/file
    2. Flask route checks admin_required (existing behaviour)
    3. server generates a 15-min presigned URL pointing at R2
    4. server returns 302 redirect to that URL
    5. browser fetches directly from R2 over HTTPS
- URLs expire after PRESIGNED_TTL_SECONDS (default 900s / 15 min).
- Files are encrypted at rest by R2 (AES-256) and in transit over
  TLS 1.3 -- this is part of R2's baseline, no config needed.

Environment variables (Render -> goocampus-hr-portal-staging)
=============================================================
  R2_ACCOUNT_ID         Cloudflare account id (hex string)
  R2_ACCESS_KEY_ID      S3-compat access key
  R2_SECRET_ACCESS_KEY  S3-compat secret
  R2_BUCKET_NAME        bucket name (e.g. goocampus-client-docs)
  R2_ENDPOINT           https://<account-id>.r2.cloudflarestorage.com

Falls back to local-only mode when any env var is missing -- the
module exposes is_configured() so callers can skip R2 in dev.
"""

import logging
import os
from typing import Optional


PRESIGNED_TTL_SECONDS = 900  # 15 minutes


_client = None
_client_init_attempted = False


def is_configured() -> bool:
    """True if every required R2 env var is set. Cheap -- no network."""
    return all(os.environ.get(k) for k in (
        'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY',
        'R2_ENDPOINT', 'R2_BUCKET_NAME',
    ))


def get_bucket_name() -> Optional[str]:
    return os.environ.get('R2_BUCKET_NAME')


def get_client():
    """Return a boto3 S3 client configured for R2. Lazy-initialised
    on first call so module import has zero cost when R2 is unused."""
    global _client, _client_init_attempted
    if _client is not None:
        return _client
    if _client_init_attempted:
        return None
    _client_init_attempted = True
    if not is_configured():
        logging.info("storage.get_client: R2 env vars not set, returning None")
        return None
    try:
        import boto3
        from botocore.config import Config
    except ImportError as e:
        logging.error(f"storage.get_client: boto3 not installed ({e})")
        return None
    try:
        _client = boto3.client(
            's3',
            endpoint_url=os.environ['R2_ENDPOINT'],
            aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
            aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
            region_name='auto',     # R2 uses 'auto'; not us-east-1
            config=Config(
                signature_version='s3v4',
                retries={'max_attempts': 3, 'mode': 'standard'},
                connect_timeout=10,
                read_timeout=30,
            ),
        )
        return _client
    except Exception as e:
        logging.error(f"storage.get_client: init failed: {e}")
        return None


def upload_bytes(key: str, body: bytes, content_type: str = 'application/octet-stream') -> bool:
    """Upload raw bytes to R2 at the given object key.

    `key` is the R2 path -- we use the convention
        <pathway>/<reg-number-safe>/<doc_type>/<filename>
    so files are organised by client + doc type for easy browsing in
    the R2 dashboard.

    Returns True on success, False on any failure (logged).
    """
    c = get_client()
    if c is None:
        return False
    try:
        c.put_object(
            Bucket=get_bucket_name(),
            Key=key,
            Body=body,
            ContentType=content_type,
        )
        return True
    except Exception as e:
        logging.error(f"storage.upload_bytes({key}): {e}")
        return False


def presigned_get_url(key: str, ttl_seconds: int = PRESIGNED_TTL_SECONDS,
                     filename_for_download: Optional[str] = None) -> Optional[str]:
    """Generate a short-lived signed URL the browser can fetch directly.

    If `filename_for_download` is set, the response also forces a
    Content-Disposition: attachment header with that filename -- useful
    when the user clicks a "Download" link. Pass None to keep the
    browser's default behaviour (display PDF/image inline).
    """
    c = get_client()
    if c is None:
        return None
    try:
        params = {'Bucket': get_bucket_name(), 'Key': key}
        if filename_for_download:
            params['ResponseContentDisposition'] = \
                f'attachment; filename="{filename_for_download}"'
        return c.generate_presigned_url(
            'get_object',
            Params=params,
            ExpiresIn=ttl_seconds,
        )
    except Exception as e:
        logging.error(f"storage.presigned_get_url({key}): {e}")
        return None


def download_bytes(key: str) -> Optional[bytes]:
    """Download an R2 object's raw bytes (server-side). Used to stream a file
    same-origin through the portal so the browser (e.g. PDF.js) can read it
    without needing cross-origin/CORS access to R2. Returns None on failure."""
    c = get_client()
    if c is None:
        return None
    try:
        obj = c.get_object(Bucket=get_bucket_name(), Key=key)
        return obj['Body'].read()
    except Exception as e:
        logging.error(f"storage.download_bytes({key}): {e}")
        return None


def delete_object(key: str) -> bool:
    """Delete one R2 object. Used when a client doc is deleted via UI
    or when the bulk importer's wipe step clears prior pathway data."""
    c = get_client()
    if c is None:
        return False
    try:
        c.delete_object(Bucket=get_bucket_name(), Key=key)
        return True
    except Exception as e:
        logging.error(f"storage.delete_object({key}): {e}")
        return False


def list_objects(prefix: str = '', max_keys: int = 1000) -> list:
    """List R2 objects under a prefix. Used by the bulk-import wipe
    step to find existing keys to delete before re-importing."""
    c = get_client()
    if c is None:
        return []
    keys = []
    continuation = None
    try:
        while True:
            kwargs = {'Bucket': get_bucket_name(),
                      'Prefix': prefix,
                      'MaxKeys': max_keys}
            if continuation:
                kwargs['ContinuationToken'] = continuation
            resp = c.list_objects_v2(**kwargs)
            for obj in resp.get('Contents', []):
                keys.append(obj['Key'])
            if not resp.get('IsTruncated'):
                break
            continuation = resp.get('NextContinuationToken')
        return keys
    except Exception as e:
        logging.error(f"storage.list_objects({prefix}): {e}")
        return keys


def _safe_segment(s: str) -> str:
    """Slugify a string for use in an R2 object key (no slashes /
    spaces / weird chars)."""
    import re
    s = (s or '').strip()
    s = re.sub(r'[^\w\-]+', '_', s)
    return s.strip('_') or 'unknown'


def make_doc_key(pathway: str, reg_number: str, doc_type: str, filename: str) -> str:
    """Build a canonical R2 object key for a client document.

    Example:
      make_doc_key('plab', 'GCUKIP/24-25/003', 'Photograph', 'IMG_1234.jpg')
      -> 'plab/GCUKIP_24-25_003/Photograph/IMG_1234.jpg'
    """
    return "/".join([
        _safe_segment(pathway),
        _safe_segment(reg_number),
        _safe_segment(doc_type),
        filename,  # keep original filename as the leaf (already a safe filename)
    ])
