"""Quick DB connection + table inspection script."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv()

import os
from sqlalchemy import create_engine, inspect, text
import urllib.parse

url = os.environ["DATABASE_URL"]
url = url.replace("postgresql+psycopg://", "postgresql+psycopg2://")
url = urllib.parse.unquote(url)

engine = create_engine(url, pool_pre_ping=True)
with engine.connect() as conn:
    pg_ver = conn.execute(text("SELECT version()")).scalar()
    print(f"PostgreSQL: {pg_ver[:60]}")

inspector = inspect(engine)
tables = sorted(inspector.get_table_names())
print(f"\nTables ({len(tables)}):")
for t in tables:
    cols = inspector.get_columns(t)
    print(f"  {t:35s} {len(cols):2d} cols")

print("\nDB connection: OK")
