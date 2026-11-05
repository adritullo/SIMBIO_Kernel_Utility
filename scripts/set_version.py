"""Stamp the version of a release tag into simbio_utility/__init__.py.

    python scripts/set_version.py v0.6.2        -> __version__ = "0.6.2"
    python scripts/set_version.py v.0.6.1       -> __version__ = "0.6.1"   (stray dot after the 'v' is tolerated)
    python scripts/set_version.py refs/tags/v1.0.0-rc1

Prints the clean version on stdout.  Used by the GitHub workflow so that the app label, the .exe/.app metadata and the
names of the release downloads always follow the tag.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

INIT = Path(__file__).resolve().parent.parent / "simbio_utility" / "__init__.py"
_TAG = re.compile(r"^(?:refs/tags/)?[vV]?\.?(\d+(?:\.\d+){1,3}(?:[-+.]?[0-9A-Za-z.]+)?)$")


def parse_tag(tag: str) -> str:
    m = _TAG.match(tag.strip())
    if not m:
        raise ValueError(f"cannot read a version from tag {tag!r} (expected something like v0.6.2)")
    return m.group(1)


def stamp(version: str, init: Path = INIT) -> None:
    text = init.read_bytes().decode("utf-8")
    new, n = re.subn(r'(?m)^__version__\s*=\s*["\'][^"\']*["\']', f'__version__ = "{version}"', text)
    if n != 1:
        raise RuntimeError(f"__version__ line not found in {init}")
    init.write_bytes(new.encode("utf-8"))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    try:
        version = parse_tag(argv[1])
        stamp(version)
    except (ValueError, RuntimeError) as exc:
        print(f"set_version: {exc}", file=sys.stderr)
        return 1
    print(version)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
