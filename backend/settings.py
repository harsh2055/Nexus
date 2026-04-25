from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "nexus.db"
INDEX_PATH = ROOT / "index.html"
STATIC_ROOT = ROOT / "static"
SESSION_DAYS = 7
