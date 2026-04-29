#!/usr/bin/env python3
"""Launch the local Qishui Android emulator."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TOOLS_DIR = ROOT / "tools"
JDK_HOME = TOOLS_DIR / "jdk-17" / "Contents" / "Home"
SDK_DIR = TOOLS_DIR / "android-sdk"
AVD_NAME = "qishui_monitor"


def resolve_avd_home() -> Path:
    explicit = os.environ.get("ANDROID_AVD_HOME")
    if explicit:
        return Path(explicit).expanduser()
    local_home = TOOLS_DIR / "avd"
    if (local_home / f"{AVD_NAME}.ini").exists() or (local_home / f"{AVD_NAME}.avd").exists():
        return local_home
    return Path.home() / ".android" / "avd"


def main() -> int:
    emulator = SDK_DIR / "emulator" / "emulator"
    avd_home = resolve_avd_home()
    if not emulator.exists():
        raise SystemExit("未找到 Android Emulator。请先运行 python3 strategy_monitor/install_android_emulator.py")
    if not ((avd_home / f"{AVD_NAME}.ini").exists() or (avd_home / f"{AVD_NAME}.avd").exists()):
        raise SystemExit("未找到本地 AVD。请先运行 python3 strategy_monitor/install_android_emulator.py")

    env = os.environ.copy()
    env["JAVA_HOME"] = str(JDK_HOME)
    env["ANDROID_HOME"] = str(SDK_DIR)
    env["ANDROID_SDK_ROOT"] = str(SDK_DIR)
    env["ANDROID_AVD_HOME"] = str(avd_home)
    env["PATH"] = os.pathsep.join([
        str(JDK_HOME / "bin"),
        str(SDK_DIR / "platform-tools"),
        str(SDK_DIR / "emulator"),
        str(SDK_DIR / "cmdline-tools" / "latest" / "bin"),
        env.get("PATH", ""),
    ])

    command = [
        str(emulator),
        "-avd",
        AVD_NAME,
        "-netdelay",
        "none",
        "-netspeed",
        "full",
        "-no-metrics",
    ]
    print("+", " ".join(command))
    subprocess.Popen(command, env=env)
    print("模拟器正在启动，首次启动可能需要 1-3 分钟。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
