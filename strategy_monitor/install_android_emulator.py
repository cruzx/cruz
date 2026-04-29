#!/usr/bin/env python3
"""Install a local Android Emulator + AVD for Qishui screenshot capture."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TOOLS_DIR = ROOT / "tools"
JDK_DIR = TOOLS_DIR / "jdk-17"
SDK_DIR = TOOLS_DIR / "android-sdk"
CMDLINE_TOOLS_DIR = SDK_DIR / "cmdline-tools" / "latest"
DEFAULT_AVD_HOME = Path.home() / ".android" / "avd"
AVD_NAME = "qishui_monitor"

CMDLINE_TOOLS_URL = "https://dl.google.com/android/repository/commandlinetools-mac-14742923_latest.zip"
PACKAGES = [
    "platform-tools",
    "emulator",
    "platforms;android-35",
]


def host_arch() -> str:
    arch = os.uname().machine.lower()
    return "arm64" if arch in {"arm64", "aarch64"} else "x86_64"


def jdk_url_for_host() -> str:
    if host_arch() == "arm64":
        return "https://aka.ms/download-jdk/microsoft-jdk-17.0.18-macos-aarch64.tar.gz"
    return "https://aka.ms/download-jdk/microsoft-jdk-17.0.18-macos-x64.tar.gz"


def system_image_for_host() -> str:
    if host_arch() == "arm64":
        return "system-images;android-35;google_apis;arm64-v8a"
    return "system-images;android-35;google_apis;x86_64"


def avd_home() -> Path:
    value = os.environ.get("ANDROID_AVD_HOME")
    return Path(value).expanduser() if value else DEFAULT_AVD_HOME


def binary_matches_host(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        result = subprocess.run(
            ["file", str(path)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception:
        return True
    output = result.stdout.lower()
    target = host_arch()
    return target in output


def remove_if_wrong_arch(path: Path) -> None:
    if path.exists() and not binary_matches_host(path):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def run(command: list[str], *, env: dict[str, str] | None = None, input_text: str | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True, env=env, input=input_text, text=True)


def run_allow_fail(command: list[str], *, env: dict[str, str] | None = None, input_text: str | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=False, env=env, input=input_text, text=True)


def download(url: str, out_path: Path) -> None:
    try:
        run(["curl", "-L", "--fail", url, "-o", str(out_path)])
        return
    except subprocess.CalledProcessError:
        print("curl 下载失败，改用 Python 内置下载器重试...")
    with urllib.request.urlopen(url) as response, out_path.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def install_jdk() -> Path:
    java = JDK_DIR / "Contents" / "Home" / "bin" / "java"
    if java.exists() and binary_matches_host(java):
        return JDK_DIR / "Contents" / "Home"

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    if JDK_DIR.exists():
        shutil.rmtree(JDK_DIR)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "jdk.tar.gz"
        extract_dir = Path(tmp) / "jdk"
        extract_dir.mkdir()
        print("正在下载 Microsoft OpenJDK 17...")
        download(jdk_url_for_host(), archive)
        run(["tar", "-xzf", str(archive), "-C", str(extract_dir)])
        candidates = sorted(extract_dir.glob("*.jdk"))
        if not candidates:
            candidates = sorted(
                path
                for path in extract_dir.iterdir()
                if (path / "bin" / "java").exists() or (path / "Contents" / "Home" / "bin" / "java").exists()
            )
        if not candidates:
            raise SystemExit("JDK 压缩包中没有找到可用的 java。")
        shutil.move(str(candidates[0]), str(JDK_DIR))
    return JDK_DIR / "Contents" / "Home"


def install_cmdline_tools() -> None:
    sdkmanager = CMDLINE_TOOLS_DIR / "bin" / "sdkmanager"
    if sdkmanager.exists():
        make_executable(CMDLINE_TOOLS_DIR / "bin" / "sdkmanager")
        make_executable(CMDLINE_TOOLS_DIR / "bin" / "avdmanager")
        return

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "cmdline-tools.zip"
        extract_dir = Path(tmp) / "extract"
        extract_dir.mkdir()
        print("正在下载 Android Command Line Tools...")
        download(CMDLINE_TOOLS_URL, archive)
        with zipfile.ZipFile(archive) as zip_file:
            zip_file.extractall(extract_dir)
        source = extract_dir / "cmdline-tools"
        if not (source / "bin" / "sdkmanager").exists():
            raise SystemExit("Command Line Tools 压缩包中没有找到 sdkmanager。")
        if CMDLINE_TOOLS_DIR.exists():
            shutil.rmtree(CMDLINE_TOOLS_DIR)
        CMDLINE_TOOLS_DIR.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(CMDLINE_TOOLS_DIR))
    make_executable(CMDLINE_TOOLS_DIR / "bin" / "sdkmanager")
    make_executable(CMDLINE_TOOLS_DIR / "bin" / "avdmanager")


def make_executable(path: Path) -> None:
    if path.exists():
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def sdk_env(java_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["JAVA_HOME"] = str(java_home)
    env["ANDROID_HOME"] = str(SDK_DIR)
    env["ANDROID_SDK_ROOT"] = str(SDK_DIR)
    env["ANDROID_AVD_HOME"] = str(avd_home())
    env["PATH"] = os.pathsep.join([
        str(java_home / "bin"),
        str(CMDLINE_TOOLS_DIR / "bin"),
        str(SDK_DIR / "platform-tools"),
        str(SDK_DIR / "emulator"),
        env.get("PATH", ""),
    ])
    return env


def install_sdk_packages(env: dict[str, str]) -> None:
    sdkmanager = CMDLINE_TOOLS_DIR / "bin" / "sdkmanager"
    remove_if_wrong_arch(SDK_DIR / "emulator")
    run_allow_fail([str(sdkmanager), "--sdk_root=" + str(SDK_DIR), "--licenses"], env=env, input_text=("y\n" * 100))
    run([str(sdkmanager), "--sdk_root=" + str(SDK_DIR), *PACKAGES, system_image_for_host()], env=env)


def create_avd(env: dict[str, str]) -> None:
    avdmanager = CMDLINE_TOOLS_DIR / "bin" / "avdmanager"
    home = avd_home()
    avd_ini = home / f"{AVD_NAME}.ini"
    if avd_ini.exists():
        print(f"AVD 已存在：{AVD_NAME}")
        return
    home.mkdir(parents=True, exist_ok=True)
    run(
        [
            str(avdmanager),
            "create",
            "avd",
            "-n",
            AVD_NAME,
            "-k",
            system_image_for_host(),
            "--force",
        ],
        env=env,
        input_text="no\n",
    )


def write_env_file(java_home: Path) -> None:
    env_file = ROOT / "android_env.sh"
    env_file.write_text(
        "\n".join(
            [
                f'export JAVA_HOME="{java_home}"',
                f'export ANDROID_HOME="{SDK_DIR}"',
                f'export ANDROID_SDK_ROOT="{SDK_DIR}"',
                f'export ANDROID_AVD_HOME="{avd_home()}"',
                f'export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"环境变量文件已写入：{env_file}")


def main() -> int:
    java_home = install_jdk()
    install_cmdline_tools()
    env = sdk_env(java_home)
    install_sdk_packages(env)
    create_avd(env)
    write_env_file(java_home)
    run([str(SDK_DIR / "emulator" / "emulator"), "-list-avds"], env=env)
    print("Android 模拟器安装完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
