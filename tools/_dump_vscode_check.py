"""Show the session-load validation in VS Code's agentHost / sessions bundles.

Prints the code around the "working directory no longer exists" message and the
fields it reads, so we patch the right place instead of guessing.
"""
import os
import re
from pathlib import Path

app = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Microsoft VS Code"
bundles = [
    *app.glob("*/resources/app/out/vs/platform/agentHost/node/agentHostMain.js"),
    *app.glob("*/resources/app/out/vs/sessions/sessions.desktop.main.js"),
]

for b in bundles:
    print("=" * 100)
    print(b.name, b.stat().st_size, "bytes")
    text = b.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"working directory no longer exists", text):
        s = max(0, m.start() - 1200)
        e = min(len(text), m.end() + 400)
        print("-" * 100)
        print(text[s:e])
    # fields that look like the working dir source
    for m in re.finditer(r"workingDirectory\w*", text):
        pass
    names = sorted(set(re.findall(r"\bworkingDirectory\w*\b|\bworkingDirectories\b", text)))
    print("\nfield names seen:", names)
    print("mentions of 'worktree':", text.count("worktree"))
    print("mentions of 'existsSync' near working:", )
    for m in re.finditer(r".{200}(?:workingDirectory|workingDirectories).{300}", text):
        seg = m.group(0)
        if "exists" in seg or "stat" in seg or "no longer" in seg:
            print("  >>>", seg[:520].replace("\n", " "))
