"""Show the stale entries in agent-host-config.json and storage.json."""
import json
import re
from pathlib import Path

d = Path(__file__).parent / "_statecopy"
STALE = re.compile(r"valoai-main[\\/]valoai-main")


def walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")
    elif isinstance(node, str) and STALE.search(node):
        yield path, node


for name in ["agent-host-config.json", "storage.json"]:
    p = d / name
    print("=" * 90)
    print(name)
    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except ValueError as exc:
        print("  not JSON:", exc)
        raw = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r".{120}valoai-main[\\/]valoai-main.{120}", raw):
            print("   raw ...", m.group(0))
        continue
    print("  top-level:", list(data) if isinstance(data, dict) else type(data))
    found = list(walk(data))
    print(f"  {len(found)} stale value(s):")
    for path, val in found:
        print(f"    {path} = {val!r}")
