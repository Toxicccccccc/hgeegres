"""Locate the per-session metadata that holds copilot.workingDirectory.

VS Code's agent host reads a session's cwd from session metadata keys named
`copilot.workingDirectory` / `copilot.workingDirectories` (see _META_CWD in
agentHostMain.js). This finds where those keys are stored on disk.
"""
import os
import re
import sqlite3
from pathlib import Path

CODE_USER = Path(os.environ["APPDATA"]) / "Code" / "User"
STALE = re.compile(r"valoai-main[\\/]valoai-main")

print("== A. key/value rows mentioning copilot.workingDirectory ==")
dbs = list(CODE_USER.rglob("*.db")) + list(CODE_USER.rglob("*.vscdb"))
for db in dbs:
    if ".venv" in str(db):
        continue
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        continue
    tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
    for t in tables:
        cols = [r[1] for r in con.execute(f'pragma table_info("{t}")')]
        if not cols:
            continue
        try:
            rows = con.execute(f'select * from "{t}"').fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            joined = "\t".join(
                v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
                for v in row)
            if "copilot.workingDirectory" in joined or STALE.search(joined):
                rel = db.relative_to(CODE_USER)
                hit_keys = sorted(set(re.findall(r"(copilot\.workingDirector\w*|claude\.working\w*)", joined)))
                stale = len(STALE.findall(joined))
                if stale or hit_keys:
                    print(f"  {rel} :: {t} :: cols={cols[:6]}")
                    print(f"      meta-keys={hit_keys} stale={stale}")
    con.close()

print("\n== B. session-state / events.jsonl files under userHome ==")
home = Path(os.path.expanduser("~"))
for p in home.rglob("events.jsonl"):
    print("  ", p)

print("\n== C. any file under Code/User holding copilot.workingDirectory ==")
for p in CODE_USER.rglob("*"):
    if not p.is_file() or p.stat().st_size > 20_000_000:
        continue
    if p.suffix.lower() in {".png", ".jpg", ".exe", ".dll", ".node", ".wasm", ".zip"}:
        continue
    try:
        txt = p.read_bytes().decode("utf-8", "replace")
    except OSError:
        continue
    if "copilot.workingDirectory" in txt or STALE.search(txt):
        print(f"  {p.relative_to(CODE_USER)}  copilotWD={'copilot.workingDirectory' in txt} stale={len(STALE.findall(txt))}")
