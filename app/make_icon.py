"""Generate the .icns app icon from the drawn Qt icon."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication

from app.icon import pixmap

MAP = {
    16: "icon_16x16.png",
    32: "icon_16x16@2x.png",
    64: "icon_32x32@2x.png",
    128: "icon_128x128.png",
    256: "icon_128x128@2x.png",
    512: "icon_256x256@2x.png",
    1024: "icon_512x512@2x.png",
}
ALSO = {
    32: "icon_32x32.png",
    256: "icon_256x256.png",
    512: "icon_512x512.png",
}


def main() -> None:
    app = QGuiApplication(sys.argv)
    base = Path(__file__).resolve().parent
    iconset = base / "icons" / "MemoryMachine.iconset"
    iconset.mkdir(parents=True, exist_ok=True)

    for size, name in MAP.items():
        pixmap(size).save(str(iconset / name), "PNG")
    for size, name in ALSO.items():
        pixmap(size).save(str(iconset / name), "PNG")

    icns = base / "icons" / "MemoryMachine.icns"
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
        check=True,
    )
    print(f"wrote {icns}")


if __name__ == "__main__":
    main()
