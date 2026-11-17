"""Create and verify a portable ZIP of the installed Windows app."""

import argparse
from datetime import datetime
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile


def files(folder):
    for path in sorted(folder.iterdir()):
        if path.is_symlink() or path.is_junction() or path.name in {".git", "__pycache__"}:
            continue
        if folder.name == "work" and path.name == "qwen-local":
            continue
        if folder.name == "card-images" and path.suffix == ".tmp":
            continue
        if path.is_dir():
            yield from files(path)
        elif path.is_file():
            yield path


def backup(source, destination):
    source, destination = source.resolve(), destination.resolve()
    if destination.is_relative_to(source):
        raise ValueError("Der Sicherungsordner muss außerhalb der App liegen.")
    if not (source / "YGO KI App.exe").is_file():
        raise ValueError("Der Quellordner enthält keine installierte YGO KI App.")
    destination.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(prefix="YGOKI-", suffix=".partial", dir=destination, delete=False) as output:
        temporary = Path(output.name)
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED, compresslevel=3) as archive:
            for path in files(source):
                archive.write(path, path.relative_to(source))
        with ZipFile(temporary) as archive:
            corrupt = archive.testzip()
            if corrupt:
                raise ValueError(f"Beschädigte Datei im Backup: {corrupt}")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        result = destination / f"YGOKI-{stamp}.zip"
        temporary.rename(result)
        return result
    finally:
        temporary.unlink(missing_ok=True)


def prune_automatic(destination, keep):
    existing = sorted(path for path in destination.iterdir()
                      if re.fullmatch(r"YGOKI-\d{8}-\d{6}-\d{6}\.zip", path.name) and path.is_file())
    for path in existing[:-keep]:
        path.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("destination", type=Path, nargs="?",
                        default=Path.home() / "Documents" / "Codex" / "YGOKI-Sicherungen")
    parser.add_argument("--automatisch", action="store_true")
    args = parser.parse_args()
    destination = args.destination / "Automatisch" if args.automatisch else args.destination
    print(f"Geprüfte Sicherung: {backup(args.app, destination)}")
    if args.automatisch:
        prune_automatic(destination, 4)
