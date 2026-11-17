"""Card pools and limit lists supported by the local MR5 runner."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

from ygo_agent.arena.deck import AllowedCards, Banlist, _lflist_hash


POOLS = {
    "TCG": AllowedCards.TCG_ONLY,
    "OCG": AllowedCards.OCG_ONLY,
    "Vorschau": AllowedCards.WITH_PRERELEASE,
}
LIST_FILES = {"TCG": "0TCG.lflist.conf", "OCG": "OCG.lflist.conf"}


@dataclass(frozen=True)
class DuelFormat:
    name: str
    allowed: AllowedCards
    banlist: Banlist | None
    banlist_file: str | None = None
    banlist_sha256: str | None = None

    @property
    def label(self):
        limit = self.banlist.name if self.banlist else "ohne Banliste"
        return f"MR5 · {self.name} · {limit}"


def read_banlist(path):
    data = path.read_bytes()
    banlist = None
    for number, raw in enumerate(data.decode("utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!") and banlist is None and line[1:].strip():
            banlist = Banlist(line[1:].strip())
            continue
        if line == "$whitelist" and banlist is not None and not banlist.whitelist:
            banlist.whitelist = True
            continue
        match = re.fullmatch(r"([0-9]{1,10})\s+([0-3])(?:\s+(?:--|#).*)?", line)
        if banlist is not None and match:
            code, count = map(int, match.groups())
            if 0 < code <= 0xFFFFFFFF and code not in banlist.content:
                banlist.content[code] = count
                banlist.hash = _lflist_hash(banlist.hash, code, count)
                continue
        raise ValueError(f"{path.name}, Zeile {number}: ungültiger oder doppelter Banlisteneintrag.")
    if banlist is None:
        raise ValueError(f"{path.name}: Die Banliste braucht eine Kopfzeile mit !Name.")
    return banlist, sha256(data).hexdigest()


def select_format(source_dir, name, list_choice=None, custom_path=None):
    if custom_path is not None:
        path = custom_path
    else:
        choice = list_choice or (name if name in LIST_FILES else "Keine")
        if choice == "Keine":
            return DuelFormat(name, POOLS[name], None)
        path = source_dir / "LFLists" / LIST_FILES[choice]
    banlist, digest = read_banlist(path)
    return DuelFormat(name, POOLS[name], banlist, Path(path).name, digest)
