"""One-off probe: show how a chat session records its working directory."""
import json
import os
import re

code_user = os.path.join(os.environ["APPDATA"], "Code", "User")
files = [
    os.path.join(code_user, "workspaceStorage", "a3e5d196b7d36499eaaad1cb36d65d47",
                 "chatEditingSessions", "2c80d897-18f3-43a9-9f13-84742346acc9", "state.json"),
    os.path.join(code_user, "globalStorage", "emptyWindowChatSessions",
                 "da9db344-f987-412a-baa8-c8c60e322630.jsonl"),
]

for f in files:
    if not os.path.exists(f):
        print("MISSING:", f)
        continue
    print("\n====", os.path.basename(f), "("
          + os.path.basename(os.path.dirname(f)) + ") ====")
    text = open(f, encoding="utf-8", errors="replace").read()
    for m in re.finditer(r".{90}(?:valoai-main|disabledassistanceV[12]|cwd|working).{90}",
                         text, re.IGNORECASE):
        print("  ...", m.group(0).replace("\n", "\\n"))

    if f.endswith(".json"):
        try:
            data = json.loads(text)
            print("  top-level keys:", list(data)[:20] if isinstance(data, dict) else type(data))
        except ValueError as exc:
            print("  (not plain JSON:", exc, ")")
