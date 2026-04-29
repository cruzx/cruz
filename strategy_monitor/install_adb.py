#!/usr/bin/env python3
"""Install Android Platform Tools locally for the strategy monitor."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TOOLS_DIR = ROOT / "tools"
PLATFORM_TOOLS_DIR = TOOLS_DIR / "platform-tools"
ADB_PATH = PLATFORM_TOOLS_DIR / "adb"
DOWNLOAD_URL = "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip"


def main() -> int:
    if ADB_PATH.exists():
        print(f"adb 已存在：{ADB_PATH}")
        subprocess.run([str(ADB_PATH), "version"], check=False)
        return 0

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "platform-tools-latest-darwin.zip"
        print("正在下载 Android SDK Platform-Tools...")
        download(zip_path)

        extract_dir = Path(tmp) / "extract"
        extract_dir.mkdir()
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extract_dir)

        extracted = extract_dir / "platform-tools"
        if not (extracted / "adb").exists():
            raise SystemExit("下载包里没有找到 adb。")

        if PLATFORM_TOOLS_DIR.exists():
            shutil.rmtree(PLATFORM_TOOLS_DIR)
        shutil.move(str(extracted), str(PLATFORM_TOOLS_DIR))

    ADB_PATH.chmod(0o755)
    print(f"安装完成：{ADB_PATH}")
    subprocess.run([str(ADB_PATH), "version"], check=False)
    return 0


def download(zip_path: Path) -> None:
    if shutil.which("curl"):
        subprocess.run(
            ["curl", "-L", "--fail", DOWNLOAD_URL, "-o", str(zip_path)],
            check=True,
        )
        return

    import urllib.request

    urllib.request.urlretrieve(DOWNLOAD_URL, zip_path)


if __name__ == "__main__":
    raise SystemExit(main())
