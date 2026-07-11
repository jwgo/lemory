"""Fetch the Obsidian Help vault (obsidianmd/obsidian-help, English) into
work/help_vault. Content is NOT committed to this repo (no explicit license in
upstream); this script re-fetches it deterministically at bench time, like
prep_squad.py does for SQuAD.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import WORK

REPO = "https://github.com/obsidianmd/obsidian-help.git"
DEST = WORK / "help_vault"


def main() -> None:
    tmp = WORK / "obsidian-help-src"
    if not tmp.exists():
        subprocess.run(["git", "clone", "--depth", "1", REPO, str(tmp)], check=True)
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    n = 0
    for f in (tmp / "en").rglob("*.md"):
        rel = f.relative_to(tmp / "en")
        target = DEST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        n += 1
    print(f"help vault ready: {n} notes -> {DEST}")


if __name__ == "__main__":
    main()
