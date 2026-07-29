import os
from pathlib import Path

DB_PATH = Path(os.environ.get("URL_SHORTENER_DB", "url_shortener.db"))
SHORT_CODE_LENGTH = 7
SHORT_CODE_MAX_ATTEMPTS = 5

RATE_LIMIT_CAPACITY = int(os.environ.get("URL_SHORTENER_RATE_LIMIT_CAPACITY", "20"))
RATE_LIMIT_REFILL_PER_SECOND = float(os.environ.get("URL_SHORTENER_RATE_LIMIT_REFILL_PER_SECOND", "0.5"))
IDEMPOTENCY_TTL_SECONDS = float(os.environ.get("URL_SHORTENER_IDEMPOTENCY_TTL_SECONDS", "300"))
REDIRECT_CACHE_SIZE = int(os.environ.get("URL_SHORTENER_REDIRECT_CACHE_SIZE", "1024"))

DENYLIST_DOMAINS = [
    d.strip().lower()
    for d in os.environ.get(
        "URL_SHORTENER_DENYLIST_DOMAINS", "malware-example.test,phishing-example.test"
    ).split(",")
    if d.strip()
]
REPORT_THRESHOLD = int(os.environ.get("URL_SHORTENER_REPORT_THRESHOLD", "3"))
