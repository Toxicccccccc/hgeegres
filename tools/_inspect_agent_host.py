"""Inspect agent-host.db: where does it store a session's working directory?"""
import os
import re
import sqlite3
from pathlib import Path

db = Path(os.environ["APPDATA"]) / "Code" / "User" / "globalStorage" / "agent-host.db"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
print("TABLES:", tables)

for t in tables:
    cols = [r[1] for r in con.execute(f'pragma table_info("{t}")')]
    n = con.execute(f'select count(*) from "{t}"').fetchone()[0]
    print(f"\n-- {t}  rows={n}\n   cols={cols}")
    if n == 0:
        continue
    try:
        rows = con.execute(f'select * from "{t}" limit 5').fetchall()
    except sqlite3.Error as exc:
        print("   !", exc)
        continue
    for row in rows:
        out = {}
        for c, v in zip(cols, row):
            if isinstance(v, bytes):
                v = v[:120]
            s = str(v)
            if len(s) > 700:
                s = s[:700] + "..."
            out[c] = s
        print("   ", out)

print("\n=== rows whose text contains the stale path ===")
for t in tables:
    cols = [r[1] for r in con.execute(f'pragma table_info("{t}")')]
    try:
        rows = con.execute(f'select * from "{t}"').fetchall()
    except sqlite3.Error:
        continue
    for row in rows:
        for c, v in zip(cols, row):
            s = v.decode("utf-8", "replace") if isinstance(v, bytes) else (v if isinstance(v, str) else "")
            if re.search(r"valoai-main[\\/]valoai-main", s):
                print(f"  [{t}.{c}]", s[:220].replace("\n", " "))
                break
