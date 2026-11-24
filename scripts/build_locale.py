"""Generate locale/<lang>/LC_MESSAGES/django.{po,mo} from scripts/translations.py (no gettext binary needed)."""
import sys
from pathlib import Path

import polib

sys.path.insert(0, str(Path(__file__).parent))
from extract_msgids import msgids  # noqa: E402
from translations import T  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LANGS = {"tet": None, "pt": 0, "en": 1, "id": 2}

ids = msgids()
missing = sorted(set(ids) - set(T))
unused = sorted(set(T) - set(ids))
if missing:
    sys.exit("Missing translations:\n" + "\n".join(missing))
if unused:
    print("Warning, unused translations:", *unused, sep="\n  ")

for lang, idx in LANGS.items():
    po = polib.POFile()
    po.metadata = {"Content-Type": "text/plain; charset=UTF-8", "Language": lang, "MIME-Version": "1.0"}
    for msgid in sorted(ids):
        po.append(polib.POEntry(msgid=msgid, msgstr="" if idx is None else T[msgid][idx], occurrences=[(ids[msgid], "")]))
    d = ROOT / "locale" / lang / "LC_MESSAGES"
    d.mkdir(parents=True, exist_ok=True)
    po.save(str(d / "django.po"))
    po.save_as_mofile(str(d / "django.mo"))
print("Built", ", ".join(LANGS))
