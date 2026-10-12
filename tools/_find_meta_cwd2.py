"""Narrow probe: find where copilot.workingDirectory metadata is stored."""
import os
import re
import sqlite3
from pathlib import Path

CODE_USER = Path(os.environ["APPDATA"]) / "Code" / "User"
STALE = re.compile(r"valoai-main[\\/]valoai-main")

# Only the stores the agent host actually uses.
candidates = [
    CODE_USER / "globalStorage" / "agent-host.db",
    CODE_USER / "globalStorage" / "storage.json",
    CODE_USER / "globalStorage" / "agent-host-config.json",
    CODE_USER / "globalStorage" / "agent-host-storage.json",
]
candidates += list((CODE_USER / "workspaceStorage").glob("*/state.vscdb"))

for db in candidates:
    if not db.exists():
        print(f"-- missing {db.name}")
        continue
    print(f"\n==== {db.relative_to(CODE_USER)} ({db.stat().st_size} bytes)")
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        print("   not sqlite:", exc)
        continue
    for t in [r[0] for r in con.execute("select name from sqlite_master where type='table'")]:
        try:
            rows = con.execute(f'select * from "{t}"').fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            joined = "\t".join(
                v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v) for v in row)
            if "copilot.workingDirectory" in joined or "workingDirectories" in joined:
                n = len(STALE.findall(joined))
                keys = sorted(set(re.findall(r"copilot\.workingDirector\w*", joined)))
                print(f"   [{t}] meta-keys={keys} stale={n} len={len(joined)}")
                for m in re.finditer(r".{80}workingDirector.{160}", joined):
                    print("      ...", m.group(0)[:260].replace("\n", " "))
                    break
            elif STALE.search(joined):
                print(f"   [{t}] STALE ONLY stale={len(STALE.findall(joined))} len={len(joined)}")
    con.close()
