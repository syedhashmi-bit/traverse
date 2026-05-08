"""Shared Flask-Caching instance.

Single-process gunicorn workers each keep their own SimpleCache, which is fine
for personal-scale dashboards (small TTLs, idempotent endpoints). Routes that
must always return fresh data should NOT be decorated with @cache.cached.
"""
from flask_caching import Cache

cache = Cache(config={
    'CACHE_TYPE': 'SimpleCache',
    'CACHE_DEFAULT_TIMEOUT': 30,
})
