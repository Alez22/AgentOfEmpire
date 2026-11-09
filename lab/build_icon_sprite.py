"""@brief Build the game's icon sprite from the vendored game-icons.

Usage: python3 lab/build_icon_sprite.py

Reads lab/assets/game_icons/*.svg (CC BY 3.0, authors in AUTHORS.txt) and
writes server/ui/static/icons/sprite.svg: one <symbol id="i-NAME"> per
icon, paths without their black background square and without fill, so
the page colours them from CSS (fill on the <use>). AUTHORS.txt is copied
next to it: the credits page reads it. Run again after adding an icon.

Resources: about 26 KB for the 16 icons; the browser fetches the sprite
once and caches it.
"""

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = ROOT / "lab" / "assets" / "game_icons"
OUT_DIR = ROOT / "server" / "ui" / "static" / "icons"
BACKGROUND = "M0 0h512v512H0z"  # every game-icons file starts with a full square


def icon_paths(path: Path) -> list[str]:
    return [d for d in re.findall(r'<path[^>]*\sd="([^"]+)"', path.read_text()) if d != BACKGROUND]


def main() -> None:
    symbols = []
    for path in sorted(ICONS_DIR.glob("*.svg")):
        paths = "".join(f'<path d="{d}"/>' for d in icon_paths(path))
        symbols.append(f'<symbol id="i-{path.stem}" viewBox="0 0 512 512">{paths}</symbol>')
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sprite = ('<svg xmlns="http://www.w3.org/2000/svg">\n<!-- game-icons.net, CC BY 3.0: authors in AUTHORS.txt;'
              ' built by lab/build_icon_sprite.py -->\n' + "\n".join(symbols) + "\n</svg>\n")
    (OUT_DIR / "sprite.svg").write_text(sprite)
    shutil.copy(ICONS_DIR / "AUTHORS.txt", OUT_DIR / "AUTHORS.txt")
    print(f"{len(symbols)} icons, {len(sprite)} bytes -> {OUT_DIR / 'sprite.svg'}")


if __name__ == "__main__":
    main()
