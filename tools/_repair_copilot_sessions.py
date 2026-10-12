"""Repair old Copilot session folders after the project folder rename.

What keeps a session from opening
---------------------------------
A session records its folder in three independent places, and the session opens
only when the folder recorded there exists AND is trusted:

1. ``agent-host.db`` -> ``sessions_v2.payload`` JSON, key ``workingDirectories``.
2. ``github.copilot-chat/session-store.db`` -> ``sessions.cwd``.
3. ``agent-host-config.json`` -> ``workspaceTrust.trustedUris``.

(3) is the one that produced the stubborn error: the session's cwd was fixed, but
the renamed folder was never in the trust list, so VS Code rejected the session
with ``workingDirectoryMissing`` -- "its working directory no longer exists".

Writes are guarded: a timestamped backup is taken first, and nothing is written
while ``Code.exe`` is running (it holds the databases open).

Usage:
    python tools/_repair_copilot_sessions.py           # dry run
    python tools/_repair_copilot_sessions.py --apply   # write the repair
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

STALE = r"c:\Users\Administrator\Desktop\valoai-main\valoai-main"
TARGET = r"c:\Users\Administrator\Desktop\valoai-main\disabledassistanceV1"
STALE_URL = "valoai-main/valoai-main"
STALE_URL_ENC = "valoai-main%2Fvaloai-main"
TARGET_URL = "valoai-main/disabledassistanceV1"
STALE_WIN = "valoai-main\\valoai-main"
TARGET_WIN = "valoai-main\\disabledassistanceV1"

CODE_USER = Path(os.environ["APPDATA"]) / "Code" / "User"
COPILOT_DB = CODE_USER / "globalStorage" / "github.copilot-chat" / "session-store.db"
AGENT_DB = CODE_USER / "globalStorage" / "agent-host.db"
CONFIG_JSON = CODE_USER / "globalStorage" / "agent-host-config.json"
SESSION_JSONS = list((CODE_USER / "workspaceStorage").glob(
    "*/chatEditingSessions/*/state.json"))
WS_DBS = list((CODE_USER / "workspaceStorage").glob("*/state.vscdb"))
AGENTS_DB = CODE_USER / "profiles" / "builtin" / "agents" / "globalStorage" / "state.vscdb"
GLOBAL_DB = CODE_USER / "globalStorage" / "state.vscdb"
SESSION_CACHE_KEY = "agentSessions.model.cache"
SESSION_STATE_DIR = Path(os.path.expanduser("~")) / ".copilot" / "session-state"
STAMP = time.strftime("%Y%m%dT%H%M%S")


def code_running() -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Code.exe", "/NH"],
                             capture_output=True, text=True, check=False).stdout
    except OSError:
        return False
    return "Code.exe" in out


def backup(path: Path) -> Path:
    dest = path.with_name(path.name + ".bak-" + STAMP)
    shutil.copy2(path, dest)
    return dest


def _fix_text(s: str) -> str:
    return (s.replace(STALE, TARGET)
             .replace(STALE_URL_ENC, TARGET_URL)
             .replace(STALE_URL, TARGET_URL)
             .replace(STALE_WIN, TARGET_WIN))


def repair_agent_host(apply: bool) -> int:
    """Rewrite workingDirectories inside sessions_v2.payload."""
    if not AGENT_DB.exists():
        print(f"[agent-host] not found: {AGENT_DB}")
        return 0
    con = sqlite3.connect(str(AGENT_DB))
    rows = con.execute(
        "select session_uri, payload, payload_hash from sessions_v2").fetchall()
    fixes = []
    for uri, payload, _old_hash in rows:
        if not payload or (STALE_URL not in payload and STALE_WIN not in payload):
            continue
        try:
            json.loads(payload)
        except ValueError as exc:
            print(f"[agent-host] {uri}: payload not JSON, skipped ({exc})")
            continue
        new_payload = _fix_text(payload)
        if new_payload == payload:
            continue
        new_hash = hashlib.sha256(new_payload.encode("utf-8")).hexdigest()
        fixes.append((uri, new_payload, new_hash))

    for uri, _, _ in fixes:
        print(f"[agent-host] {uri.split('/')[-1][:8]}  workingDirectories -> {TARGET_URL}")
    if apply and fixes:
        for uri, new_payload, new_hash in fixes:
            con.execute(
                "update sessions_v2 set payload = ?, payload_hash = ? where session_uri = ?",
                (new_payload, new_hash, uri))
        con.commit()
        print(f"[agent-host] updated {con.total_changes} row(s)")
    con.close()
    return len(fixes)


def repair_trusted_uris(apply: bool) -> int:
    """Point workspace-trust entries at the renamed folder.

    A session will not open in an untrusted workspace, and the trust list still
    names the pre-rename folder. The old URI is replaced in place; if that would
    duplicate an entry that already exists, the stale one is dropped instead.
    """
    if not CONFIG_JSON.exists():
        print(f"[trust] not found: {CONFIG_JSON}")
        return 0
    data = json.loads(CONFIG_JSON.read_text(encoding="utf-8", errors="replace"))
    trust = data.get("workspaceTrust")
    if not isinstance(trust, dict):
        print("[trust] no workspaceTrust block")
        return 0
    uris = trust.get("trustedUris")
    if not isinstance(uris, list):
        print("[trust] no trustedUris list")
        return 0

    fixed, out, seen = 0, [], set()
    for uri in uris:
        new_uri = _fix_text(uri) if isinstance(uri, str) else uri
        if isinstance(uri, str) and new_uri != uri:
            fixed += 1
            print(f"[trust] {uri}\n     -> {new_uri}")
        if new_uri in seen:
            print(f"[trust] dropping duplicate {new_uri}")
            continue
        seen.add(new_uri)
        out.append(new_uri)

    if not fixed:
        print("[trust] already points at the renamed folder")
        return 0
    trust["trustedUris"] = out
    if apply:
        CONFIG_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"[trust] updated {fixed} entr(y/ies)")
    return fixed


def repair_copilot_db(apply: bool) -> int:
    if not COPILOT_DB.exists():
        return 0
    con = sqlite3.connect(str(COPILOT_DB))
    rows = con.execute("select id from sessions where cwd = ?", (STALE,)).fetchall()
    if apply and rows:
        con.execute("update sessions set cwd = ? where cwd = ?", (TARGET, STALE))
        con.commit()
        print(f"[session-store] updated {con.total_changes} row(s)")
    con.close()
    return len(rows)


def repair_jsons(apply: bool) -> int:
    total = 0
    for path in SESSION_JSONS:
        text = path.read_text(encoding="utf-8", errors="replace")
        new = _fix_text(text)
        if new != text:
            hits = text.count(STALE_WIN) + text.count(STALE_URL)
            print(f"[json] {path.name}: {hits} reference(s)")
            total += hits
            if apply:
                path.write_text(new, encoding="utf-8")
    return total


def repair_session_cache(apply: bool) -> int:
    """Rewrite workingDirectoryPath inside agentSessions.model.cache.

    This is the workspace-level state.vscdb ItemTable entry that the Chat
    Sessions view reads. Its metadata.workingDirectoryPath is what the
    "working directory no longer exists" error quotes, so if the project
    folder was renamed this must be repointed too.
    """
    fixed = 0
    dbs = [p for p in [*WS_DBS, AGENTS_DB, GLOBAL_DB] if p.exists()]
    for db in dbs:
        con = sqlite3.connect(str(db))
        try:
            row = con.execute(
                "select value from ItemTable where key=?", (SESSION_CACHE_KEY,)
            ).fetchone()
        except sqlite3.Error as exc:
            print(f"[cache] {db.parent.name}: read failed ({exc})")
            con.close()
            continue
        if not row:
            con.close()
            continue
        raw = row[0].decode() if isinstance(row[0], bytes) else row[0]
        if STALE_WIN not in raw and STALE_URL not in raw and STALE not in raw:
            con.close()
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            new_raw = _fix_text(raw)
            if new_raw == raw:
                con.close(); continue
            hits = raw.count(STALE_WIN) + raw.count(STALE_URL)
            if apply:
                con.execute("update ItemTable set value=? where key=?",
                            (new_raw, SESSION_CACHE_KEY))
                con.commit()
            print(f"[cache] {db.parent.name}: {hits} string reference(s)")
            fixed += hits
            con.close()
            continue
        hits = raw.count(STALE_WIN) + raw.count(STALE_URL)

        def walk(obj):
            n = 0
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k == "workingDirectoryPath" and isinstance(v, str):
                        nv = _fix_text(v)
                        if nv != v:
                            obj[k] = nv
                            n += 1
                    else:
                        n += walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    n += walk(v)
            elif isinstance(obj, str):
                nv = _fix_text(obj)
                if nv != obj:
                    # only count generic strings that actually contain the path
                    n += 1 if (STALE_WIN in obj or STALE_URL in obj) else 0
                    # mutate in place is not possible for str; handled via parent
            return n

        # strings other than workingDirectoryPath are replaced via re-serialization
        new_raw = _fix_text(json.dumps(data, ensure_ascii=False))
        if new_raw != raw:
            if apply:
                con.execute("update ItemTable set value=? where key=?",
                            (new_raw.encode("utf-8"), SESSION_CACHE_KEY))
                con.commit()
            print(f"[cache] {db.parent.name}: {hits} workingDirectoryPath reference(s)")
            fixed += hits
        con.close()
    return fixed


def repair_session_state_yamls(apply: bool) -> int:
    """Repoint workspace.yaml inside ~/.copilot/session-state/<session-id>.

    The Copilot agent-host stores each session's workspace root in a yaml file
    per session. This is the file the session loader checks, and it is NOT
    part of VS Code's storage, so it never gets flushed/overwritten by VS Code.
    """
    fixed = 0
    if not SESSION_STATE_DIR.exists():
        print(f"[yaml] not found: {SESSION_STATE_DIR}")
        return 0
    for ws in SESSION_STATE_DIR.iterdir():
        yaml_path = ws / "workspace.yaml"
        if not yaml_path.exists():
            continue
        text = yaml_path.read_text(encoding="utf-8", errors="replace")
        hits = text.count(STALE_WIN) + text.count(STALE)
        if not hits:
            continue
        new = _fix_text(text)
        print(f"[yaml] {ws.name}: {hits} reference(s)")
        fixed += hits
        if apply:
            backup(yaml_path)
            yaml_path.write_text(new, encoding="utf-8")
    return fixed


def repair_item_table(apply: bool) -> int:
    """Generic sweep: replace stale path strings in every ItemTable key.

    The sessions list is indexed from chat.ChatSessionStore.index in the
    workspace state.vscdb; the stale path also hides in memento/* keys.
    Patching only one key (agentSessions.model.cache) was not enough.
    """
    fixed = 0
    dbs = [p for p in [*WS_DBS, GLOBAL_DB, AGENTS_DB] if p.exists()]
    for db in dbs:
        con = sqlite3.connect(str(db))
        try:
            rows = con.execute("select key, value from ItemTable").fetchall()
        except sqlite3.Error as exc:
            print(f"[items] {db.parent.name}: read failed ({exc})")
            con.close()
            continue
        updates = []
        for key, val in rows:
            raw = val if isinstance(val, (bytes, bytearray)) else str(val).encode("utf-8", "ignore")
            if STALE.encode() not in raw and STALE_URL.encode() not in raw and STALE_WIN.encode() not in raw:
                continue
            text = raw.decode("utf-8", "replace")
            new = _fix_text(text)
            hits = text.count(STALE_WIN) + text.count(STALE_URL)
            if hits and new != text:
                updates.append((key, new.encode("utf-8"), hits))
                print(f"[items] {db.parent.name} | {key}: {hits} reference(s)")
                fixed += hits
        if apply and updates:
            for key, blob, _ in updates:
                con.execute("update ItemTable set value=? where key=?", (blob, key))
            con.commit()
        con.close()
    return fixed


def main() -> int:
    apply = "--apply" in sys.argv
    print(f"mode: {'APPLY' if apply else 'DRY RUN'}")
    print(f"stale:  {STALE}\ntarget: {TARGET}\n")
    if apply and code_running():
        print("ABORT: VS Code is running; close it so the write is not lost.")
        return 2

    if apply:
        for p in [AGENT_DB, CONFIG_JSON, COPILOT_DB, *SESSION_JSONS, *WS_DBS, AGENTS_DB, GLOBAL_DB]:
            if p.exists():
                print(f"[backup] {p.name} -> {backup(p).name}")

    changed = 0
    changed += repair_agent_host(apply)
    changed += repair_trusted_uris(apply)
    changed += repair_copilot_db(apply)
    changed += repair_jsons(apply)
    changed += repair_session_cache(apply)
    changed += repair_item_table(apply)
    changed += repair_session_state_yamls(apply)

    print()
    if apply:
        print(f"DONE - {changed} reference(s) repointed.")
    else:
        print(f"{changed} reference(s) would be repointed. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
