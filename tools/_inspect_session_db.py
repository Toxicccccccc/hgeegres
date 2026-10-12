"""One-off probe: show the schema and the sessions recorded in Copilot's store."""
import os
import sqlite3

db = os.path.join(
    os.environ["APPDATA"],
    "Code", "User", "globalStorage", "github.copilot-chat", "session-store.db",
)
print("DB:", db, "exists=", os.path.exists(db))

con = sqlite3.connect(db)
tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
print("TABLES:", tables)
for t in tables:
    print(" ", t, "rows =", con.execute('select count(*) from "%s"' % t).fetchone()[0])

for t in tables:
    cols = [r[1] for r in con.execute('pragma table_info("%s")' % t)]
    textual = [c for c in cols if "path" in c.lower() or "dir" in c.lower() or "folder" in c.lower() or "cwd" in c.lower() or "title" in c.lower() or "session" in c.lower()]
    if textual:
        print("\n--", t, "textual cols:", textual)
        sel = ", ".join('"%s"' % c for c in textual)
        for row in con.execute('select %s from "%s" limit 30' % (sel, t)):
            print("   ", row)
con.close()
