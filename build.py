"""Build yt2tiktok with PyInstaller."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
VERSION = "1.0.0"


def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "yt2tiktok",
        "--onedir",
        "--windowed",
        "--add-data", f"{ROOT / 'fonts'};fonts",
        "--add-data", f"{ROOT / 'assets'};assets",
        "--hidden-import", "customtkinter",
        "--hidden-import", "PIL",
        "--collect-all", "customtkinter",
    ]

    icon = ROOT / "assets" / "icon.ico"
    if icon.exists():
        cmd.extend(["--icon", str(icon)])

    cmd.append(str(ROOT / "main.py"))

    print(f"Building yt2tiktok v{VERSION}...")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode == 0:
        print(f"\nBuild successful! Output in: {ROOT / 'dist' / 'yt2tiktok'}")
    else:
        print(f"\nBuild failed with exit code {result.returncode}")
        sys.exit(1)


if __name__ == "__main__":
    build()
