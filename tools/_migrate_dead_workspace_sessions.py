"""Migrate Copilot chat sessions from the dead workspace storage to the live one.

Why this is needed
------------------
The old sessions live in
    workspaceStorage\\a3e5d196...  (folder = ...\\valoai-main\\valoai-main, DELETED)
but the project now opens as
    workspaceStorage\\1b8155ff...  (folder = ...\\valoai-main, EXISTS)

VS Code picks the storage folder by hashing the open folder's URI, so the dead
storage is unreachable forever. The only way to make the old sessions show up
again is to copy them into the storage of the folder you actually open.

Copies (with path repointing):
  1. agentSessions.model.cache   -> merged into the target cache (dedupe by id)
  2. chat.ChatSessionStore.index -> merged the same way
  3. chatEditingSessions\\*      -> copied as files (state.json paths repointed)

Usage:  python tools/_migrate_dead_workspace_sessions.py [--apply]
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

STALE = r"c:\Users\Administrator\Desktop\valoai-main\valoai-main"
TARGET = r"c:\Users\Administrator\Desktop\valoai-main\disabledassistanceV1"

DEAD_WS = "a3e5d196b7d36499eaaad1cb36d65d47"
LIVE_WS = "1b8155ff42aa18956fbefba1aa169db8"

CODE_USER = Path(os.environ["APPDATA"]) / "Code" / "User"
WS_ROOT = CODE_USER / "workspaceStorage"
DEAD = WS_ROOT / DEAD_WS
LIVE = WS_ROOT / LIVE_WS
CACHE_KEY = "agentSessions.model.cache"
STATE_KEY = "agentSessions.state.cache"
INDEX_KEY = "chat.ChatSessionStore.index"
MEMENTO_KEY = "memento/interactive-session"
STAMP = time.strftime("%Y%m%dT%H%M%S")


def fix_text(s: str) -> str:
    return s.replace(STALE, TARGET)


def code_running() -> bool:
    try:
        import subprocess
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Code.exe", "/NH"],
                             capture_output=True, text=True, check=False).stdout
    except OSError:
        return False
    return "Code.exe" in out


def read_key(con: sqlite3.Connection, key: str):
    row = con.execute("select value from ItemTable where key=?", (key,)).fetchone()
    if not row:
        return None
    raw = row[0] if isinstance(row[0], bytes) else row[0].encode("utf-8")
    return json.loads(raw.decode("utf-8", "replace"))


def write_key(con: sqlite3.Connection, key: str, data) -> None:
    con.execute("update ItemTable set value=? where key=?",
                (json.dumps(data, ensure_ascii=False).encode("utf-8"), key))


def session_id(entry: dict):
    for k in ("sessionId", "id", "sessionIndex"):
        if k in entry:
            return entry[k]
    return json.dumps(entry.get("metadata"), sort_keys=True)[:80]


def migrate(apply: bool) -> None:
    print(f"mode: {'APPLY' if apply else 'DRY RUN'}")
    print(f"dead storage: {DEAD}\nlive storage: {LIVE}\n")
    if apply and code_running():
        print("ABORT: VS Code is running; close it first.")
        sys.exit(2)

    dead_con = sqlite3.connect(str(DEAD / "state.vscdb"))
    live_con = sqlite3.connect(str(LIVE / "state.vscdb"))
    wrote = False

    # 1 & 2. merge list-valued keys (session caches) into live lists
    for key in (CACHE_KEY, STATE_KEY):
        dead_val = read_key(dead_con, key)
        live_val = read_key(live_con, key)
        if not isinstance(dead_val, list):
            print(f"[{key}] nothing to merge")
            continue
        live_val = live_val if isinstance(live_val, list) else []
        existing = {session_id(e) for e in live_val if isinstance(e, dict)}
        added = 0
        for entry in dead_val:
            if not isinstance(entry, dict):
                continue
            entry = json.loads(fix_text(json.dumps(entry, ensure_ascii=False)))
            sid = session_id(entry)
            if sid in existing:
                continue
            existing.add(sid)
            live_val.append(entry)
            added += 1
        print(f"[{key}] {added} session(s) to merge")
        if apply and added:
            write_key(live_con, key, live_val)
            wrote = True

    # 3. merge the chat session index (dict keyed by session id)
    for key in (INDEX_KEY,):
        dead_val = read_key(dead_con, key)
        live_val = read_key(live_con, key) or {"version": 1, "entries": {}}
        if not isinstance(dead_val, dict) or not isinstance(dead_val.get("entries"), dict):
            print(f"[{key}] nothing to merge")
            continue
        entries = live_val.setdefault("entries", {})
        added = 0
        for sid, entry in dead_val["entries"].items():
            if not isinstance(entry, dict):
                continue
            entry = json.loads(fix_text(json.dumps(entry, ensure_ascii=False)))
            if sid in entries:
                continue
            entries[sid] = entry
            added += 1
        print(f"[{key}] {added} session(s) to merge")
        if apply and added:
            write_key(live_con, key, live_val)
            wrote = True

    # 4. merge chat history memento (dict: provider -> history list)
    dead_val = read_key(dead_con, MEMENTO_KEY)
    live_val = read_key(live_con, MEMENTO_KEY) or {}
    if isinstance(dead_val, dict):
        added = 0
        for provider, hist in dead_val.items():
            if not isinstance(hist, (list, dict)):
                continue
            target = live_val.setdefault(provider, [] if isinstance(hist, list) else {})
            if isinstance(hist, list):
                have = {json.dumps(h, sort_keys=True)[:120] for h in target if isinstance(h, dict)}
                for item in hist:
                    if not isinstance(item, dict):
                        continue
                    item = json.loads(fix_text(json.dumps(item, ensure_ascii=False)))
                    sig = json.dumps(item, sort_keys=True)[:120]
                    if sig in have:
                        continue
                    have.add(sig)
                    target.append(item)
                    added += 1
            else:  # dict keyed by something (e.g. session id)
                for hk, item in hist.items():
                    if hk in target:
                        continue
                    target[hk] = json.loads(fix_text(json.dumps(item, ensure_ascii=False)))
                    added += 1
        print(f"[{MEMENTO_KEY}] {added} history item(s) to merge")
        if apply and added:
            write_key(live_con, MEMENTO_KEY, live_val)
            wrote = True

    dead_con.close()
    if apply and wrote:
        live_con.commit()
    live_con.close()

    # 3. chatEditingSessions files
    src_root = DEAD / "chatEditingSessions"
    dst_root = LIVE / "chatEditingSessions"
    if src_root.exists():
        for session_dir in src_root.iterdir():
            if not session_dir.is_dir():
                continue
            dst = dst_root / session_dir.name
            print(f"[editing] {session_dir.name} -> live storage")
            if apply:
                if dst.exists():
                    shutil.copy2(session_dir / "state.json",
                                 dst / f"state.json.bak-migrated-{STAMP}")
                    shutil.copy2(session_dir / "state.json", dst / "state.json")
                else:
                    shutil.copytree(session_dir, dst)
                    state = dst / "state.json"
                    state.write_text(fix_text(state.read_text(encoding="utf-8",
                                  errors="replace")), encoding="utf-8")

    if apply:
        print("\nDONE - sessions migrated. Open the valoai-main folder and check the session list.")
    else:
        print("\nDRY RUN only. Re-run with --apply to write.")


if __name__ == "__main__":
    migrate("--apply" in sys.argv)