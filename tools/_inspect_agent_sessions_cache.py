import sqlite3, os, pathlib, json, sys

base = pathlib.Path(os.environ["APPDATA"]) / "Code" / "User"
KEY = "agentSessions.model.cache"
for wsdir in (base / "workspaceStorage").iterdir():
    db = wsdir / "state.vscdb"
    if not db.exists():
        continue
    con = sqlite3.connect(str(db))
    try:
        row = con.execute("select value from ItemTable where key=?", (KEY,)).fetchone()
    except Exception as e:
        print(wsdir.name, "err", e); continue
    if not row:
        continue
    v = row[0].decode() if isinstance(row[0], bytes) else row[0]
    d = json.loads(v)
    print("==", wsdir.name)
    def walk(o, path=""):
        if isinstance(o, dict):
            for k, val in o.items(): walk(val, path + "/" + str(k))
        elif isinstance(o, list):
            for i, val in enumerate(o): walk(val, path + f"[{i}]")
        elif isinstance(o, str) and ("valoai" in o.lower()):
            print("  ", path, "->", o[:120])
    walk(d)
    con.close()
