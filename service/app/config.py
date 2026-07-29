import os
from pathlib import Path

DB_PATH = Path(os.environ.get("URL_SHORTENER_DB", "url_shortener.db"))
SHORT_CODE_LENGTH = 7
SHORT_CODE_MAX_ATTEMPTS = 5
