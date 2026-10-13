"""List translatable strings found in templates and python sources (no gettext binary needed)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAT_PY = re.compile(r'\b_\(\s*(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')\s*\)')
PAT_TPL = re.compile(r'{%\s*trans\s+(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')')


def msgids():
    found = {}
    for path in ROOT.rglob("*"):
        if ".venv" in path.parts or "migrations" in path.parts or "scripts" in path.parts:
            continue
        if path.suffix == ".py":
            pat = PAT_PY
        elif path.suffix == ".html":
            pat = PAT_TPL
        else:
            continue
        for m in pat.finditer(path.read_text(encoding="utf-8")):
            s = m.group(1) if m.group(1) is not None else m.group(2)
            found.setdefault(s, path.relative_to(ROOT).as_posix())
    return found


if __name__ == "__main__":
    for s, where in sorted(msgids().items()):
        print(f"{where}: {s}")
