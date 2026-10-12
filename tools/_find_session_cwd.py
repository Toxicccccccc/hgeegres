"""Find every place a Copilot session records its working directory.

The DB `sessions.cwd` patch alone did not clear the error, so the path must also
live somewhere else that Copilot reads first. Scans the session JSON, the
workspace storage state.vscdb (SQLite key/value), and the chat session stores.
"""
import os
import re
import sqlite3
import json
from pathlib import Path

CODE_USER = Path(os.environ["APPDATA"]) / "Code" / "User"
NEEDLE = re.compile(r"valoai-main[\\/]valoai-main|disabledassistanceV1|valoai-main_Old")

print("== 1. session state.json keys ==")
for p in (CODE_USER / "workspaceStorage").glob("*/chatEditingSessions/*/state.json"):
    data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    print(p.name, "top keys:", list(data))
    blob = json.dumps(data)
    print("   stale hits:", len(re.findall(r"valoai-main[\\/]valoai-main", blob)),
          "| v1 hits:", blob.count("disabledassistanceV1"))

print("\n== 2. workspace state.vscdb (all workspaces) ==")
for db in (CODE_USER / "workspaceStorage").glob("*/state.vscdb"):
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
        for t in tables:
            try:
                rows = con.execute(f'select * from "{t}"').fetchall()
            except sqlite3.Error:
                continue
            for row in rows:
                for cell in row:
                    if isinstance(cell, (str, bytes)):
                        s = cell.decode("utf-8", "replace") if isinstance(cell, bytes) else cell
                        if NEEDLE.search(s) and "valoai-main" in s:
                            for m in re.finditer(r".{60}valoai-main.{60}", s):
                                print(f"  {db.parent.name}/{t}: ...{m.group(0)}...")
                                break
        con.close()
    except sqlite3.Error as exc:
        print("  !", db, exc)

print("\n== 3. copilot session-store.db full dump of sessions ==")
db = CODE_USER / "globalStorage" / "github.copilot-chat" / "session-store.db"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
cols = [d[0] for d in con.execute("select * from sessions").description]
print("  cols:", cols)
for row in con.execute("select * from sessions"):
    rec = dict(zip(cols, row))
    print("  ", {k: v for k, v in rec.items() if v is not None})
con.close()

print("\n== 4. other chat session stores on disk ==")
for base in [CODE_USER / "globalStorage", CODE_USER / "workspaceStorage"]:
    for f in base.rglob("*"):
        if f.is_file() and f.suffix in {".json", ".jsonl", ".db"} and f.stat().st_size < 5_000_000:
            try:
                txt = f.read_bytes().decode("utf-8", "replace")
            except OSError:
                continue
            n = len(re.findall(r"valoai-main[\\/]valoai-main", txt))
            if n:
                print(f"  {f.relative_to(CODE_USER)}  stale-hit={n}")
