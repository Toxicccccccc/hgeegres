"""Check which VS Code state files still reference the pre-rename path."""
import os
import re
from pathlib import Path

CU = Path(os.environ["APPDATA"]) / "Code" / "User"
STALE = re.compile(r"valoai-main[\\/]valoai-main")

targets = [
    CU / "globalStorage" / "storage.json",
    CU / "globalStorage" / "agent-host-config.json",
    CU / "globalStorage" / "agent-host-storage.json",
    CU / "globalStorage" / "agent-host.db",
    CU / "globalStorage" / "github.copilot-chat" / "session-store.db",
    CU / "workspaceStorage" / "1b8155ff42aa18956fbefba1aa169db8" / "workspace.json",
    CU / "workspaceStorage" / "a3e5d196b7d36499eaaad1cb36d65d47" / "workspace.json",
]
targets += list((CU / "workspaceStorage").glob("*/state.vscdb"))

for p in targets:
    if not p.exists():
        print(f"MISSING  {p.name}")
        continue
    data = p.read_bytes()
    txt = data.decode("utf-8", "replace")
    stale = len(STALE.findall(txt))
    v1 = txt.count("disabledassistanceV1")
    flag = "  <== STILL STALE" if stale else ""
    print(f"stale={stale:<3} v1={v1:<3} {p.relative_to(CU)}{flag}")
    if stale:
        for m in list(re.finditer(r".{90}valoai-main[\\/]valoai-main.{90}", txt))[:4]:
            print("      ...", m.group(0)[:220].replace("\n", " "))
