"""One-off probe: locate every Copilot chat session and the cwd it records."""
import glob
import json
import os

code_user = os.path.join(os.environ["APPDATA"], "Code", "User")

patterns = [
    os.path.join(code_user, "globalStorage", "emptyWindowChatSessions", "*.jsonl"),
    os.path.join(code_user, "workspaceStorage", "*", "chatSessions", "**", "*"),
    os.path.join(code_user, "workspaceStorage", "*", "chatEditingSessions", "**", "*.json"),
]

for pat in patterns:
    hits = glob.glob(pat, recursive=True)
    print("\nPATTERN:", pat, "->", len(hits), "file(s)")
    for h in hits[:20]:
        if os.path.isdir(h):
            continue
        try:
            txt = open(h, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            print("   !", h, exc)
            continue
        paths = sorted({p for p in [
            "valoai-main\\\\valoai-main", "valoai-main\\valoai-main",
            "valoai-main", "disabledassistanceV1", "disabledassistanceV2",
        ] if p in txt})
        print("   ", os.path.relpath(h, code_user), "| size", os.path.getsize(h),
              "| mentions:", paths)
