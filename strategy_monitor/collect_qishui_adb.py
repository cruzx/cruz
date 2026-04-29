#!/usr/bin/env python3
"""Collect Qishui Music screenshots from an Android device via adb."""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_PACKAGE = "com.luna.music"
REMOTE_SCREENSHOT = "/sdcard/qishui_strategy_screen.png"
LOCAL_ADB = ROOT / "tools" / "platform-tools" / "adb"
SDK_ADB = ROOT / "tools" / "android-sdk" / "platform-tools" / "adb"
ADB = str(SDK_ADB) if SDK_ADB.exists() else (str(LOCAL_ADB) if LOCAL_ADB.exists() else "adb")
DEFAULT_KEYWORDS = ["免费模式", "免费听", "会员歌", "会员歌曲", "看视频", "看广告", "畅听", "VIP", "广告"]
DEFAULT_TRIGGER_KEYWORDS = [
    "免费模式",
    "免费听",
    "看视频",
    "看广告",
    "会员歌",
    "会员歌曲",
    "畅听",
    "VIP",
    "会员",
    "试听",
    "播放",
]
DISMISS_KEYWORDS = ["跳过", "以后再说", "暂不", "关闭", "取消", "我知道了", "同意", "允许"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture Qishui Music screenshots into the daily monitor folder.")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="Capture date, e.g. 2026-04-20.")
    parser.add_argument("--package", default=DEFAULT_PACKAGE, help="Android package name for Qishui Music.")
    parser.add_argument("--count", type=int, default=1, help="Number of screenshots to capture.")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between screenshots.")
    parser.add_argument("--attempts", type=int, default=6, help="How many times to check for a free-mode screen.")
    parser.add_argument("--keyword", action="append", default=[], help="Keyword that must appear in the UI dump.")
    parser.add_argument("--trigger-keyword", action="append", default=[], help="Keyword to tap while trying to open free mode.")
    parser.add_argument("--auto-open-free-mode", action="store_true", help="Try to open a free-mode popup before capture.")
    parser.add_argument("--allow-any-screen", action="store_true", help="Capture even when free-mode keywords are not found.")
    parser.add_argument("--no-launch", action="store_true", help="Do not launch Qishui Music before capture.")
    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory.")
    parser.add_argument("--file-prefix", default="qishui", help="Screenshot filename prefix.")
    return parser.parse_args()


def run_adb(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ADB, *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def require_adb() -> None:
    if SDK_ADB.exists():
        return
    if LOCAL_ADB.exists():
        return
    if not shutil.which("adb"):
        raise SystemExit("未找到 adb。请先在网页 App 点击“安装本地 adb”，或运行 python3 strategy_monitor/install_adb.py。")


def require_device() -> None:
    result = run_adb(["devices"])
    lines = [line for line in result.stdout.splitlines()[1:] if line.strip()]
    ready = [line for line in lines if "\tdevice" in line]
    if not ready:
        raise SystemExit("未检测到可用 Android 设备。请连接手机/模拟器，并执行 adb devices 确认授权。")


def launch_package(package: str) -> None:
    result = run_adb(["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"], check=False)
    if result.returncode != 0:
        raise SystemExit(f"启动 App 失败，package={package}。可用 --package 指定真实包名。\n{result.stderr}")


def capture(out_dir: Path, index: int, file_prefix: str) -> Path:
    run_adb(["shell", "screencap", "-p", REMOTE_SCREENSHOT])
    out_path = out_dir / f"{file_prefix}_{index:02d}.png"
    run_adb(["pull", REMOTE_SCREENSHOT, str(out_path)])
    run_adb(["shell", "rm", REMOTE_SCREENSHOT], check=False)
    return out_path


def dump_ui(out_dir: Path, name: str = "window_dump.xml") -> Path | None:
    remote_xml = "/sdcard/window_dump.xml"
    result = run_adb(["shell", "uiautomator", "dump", remote_xml], check=False)
    if result.returncode != 0:
        return None
    out_path = out_dir / name
    run_adb(["pull", remote_xml, str(out_path)], check=False)
    run_adb(["shell", "rm", remote_xml], check=False)
    return out_path if out_path.exists() else None


def ui_text(xml_path: Path | None) -> str:
    if not xml_path or not xml_path.exists():
        return ""
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return xml_path.read_text(encoding="utf-8", errors="replace")
    values = []
    for node in root.iter():
        for attr in ("text", "content-desc", "resource-id"):
            value = node.attrib.get(attr)
            if value:
                values.append(value)
    return "\n".join(values)


def parse_bounds(bounds: str) -> tuple[int, int] | None:
    match = None
    import re

    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not match:
        return None
    left, top, right, bottom = [int(value) for value in match.groups()]
    if right <= left or bottom <= top:
        return None
    return ((left + right) // 2, (top + bottom) // 2)


def ui_nodes(xml_path: Path | None) -> list[dict[str, str]]:
    if not xml_path or not xml_path.exists():
        return []
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return []
    nodes = []
    for node in root.iter():
        values = []
        for attr in ("text", "content-desc", "resource-id"):
            value = node.attrib.get(attr)
            if value:
                values.append(value)
        label = "\n".join(values)
        bounds = node.attrib.get("bounds", "")
        if label and bounds:
            nodes.append(
                {
                    "label": label,
                    "bounds": bounds,
                    "clickable": node.attrib.get("clickable", "false"),
                    "enabled": node.attrib.get("enabled", "true"),
                }
            )
    return nodes


def matches_free_mode(text: str, keywords: list[str]) -> bool:
    normalized = text.lower()
    return any(keyword.lower() in normalized for keyword in keywords)


def tap(bounds: str) -> bool:
    center = parse_bounds(bounds)
    if not center:
        return False
    run_adb(["shell", "input", "tap", str(center[0]), str(center[1])], check=False)
    return True


def tap_first_match(xml_path: Path | None, keywords: list[str]) -> str | None:
    lowered_keywords = [keyword.lower() for keyword in keywords]
    candidates = []
    for node in ui_nodes(xml_path):
        if node.get("enabled") == "false":
            continue
        label = node["label"]
        normalized = label.lower()
        if not any(keyword in normalized for keyword in lowered_keywords):
            continue
        center = parse_bounds(node["bounds"])
        if not center:
            continue
        score = 0
        if node.get("clickable") == "true":
            score += 4
        score += sum(1 for keyword in lowered_keywords if keyword in normalized)
        candidates.append((score, label, node["bounds"]))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    _, label, bounds = candidates[0]
    return label if tap(bounds) else None


def try_open_free_mode(out_dir: Path, keywords: list[str], trigger_keywords: list[str], attempts: int, interval: float) -> Path | None:
    for attempt in range(1, max(1, attempts) + 1):
        probe_xml = dump_ui(out_dir, f"auto_probe_{attempt:02d}.xml")
        text = ui_text(probe_xml)
        if matches_free_mode(text, keywords):
            return probe_xml

        dismissed = tap_first_match(probe_xml, DISMISS_KEYWORDS)
        if dismissed:
            time.sleep(1)
            continue

        tapped = tap_first_match(probe_xml, trigger_keywords)
        if tapped:
            time.sleep(interval)
            continue

        if probe_xml and probe_xml.exists():
            probe_xml.unlink()
        time.sleep(interval)
    return None


def main() -> int:
    args = parse_args()
    require_adb()
    require_device()

    out_dir = args.out_dir or (ROOT / "qishui_daily" / args.date)
    out_dir.mkdir(parents=True, exist_ok=True)

    keywords = args.keyword or DEFAULT_KEYWORDS
    trigger_keywords = args.trigger_keyword or DEFAULT_TRIGGER_KEYWORDS

    if not args.no_launch:
        launch_package(args.package)
        time.sleep(3)

    matched_xml = None
    if args.auto_open_free_mode:
        matched_xml = try_open_free_mode(
            out_dir,
            keywords=keywords,
            trigger_keywords=trigger_keywords,
            attempts=max(args.attempts, 8),
            interval=max(args.interval, 1),
        )

    if not args.allow_any_screen:
        if not matched_xml:
            for attempt in range(1, max(1, args.attempts) + 1):
                probe_xml = dump_ui(out_dir, f"probe_{attempt:02d}.xml")
                text = ui_text(probe_xml)
                if matches_free_mode(text, keywords):
                    matched_xml = probe_xml
                    break
                if probe_xml and probe_xml.exists():
                    probe_xml.unlink()
                if attempt < args.attempts:
                    time.sleep(args.interval)
        if not matched_xml:
            terms = "、".join(keywords)
            raise SystemExit(
                "未检测到免费模式相关页面，已取消截图保存。"
                f"已尝试自动点击入口，但没有打开免费模式/看视频免费听弹窗。检测关键词：{terms}"
            )

    captured = []
    for index in range(1, args.count + 1):
        captured.append(capture(out_dir, index, args.file_prefix))
        if index < args.count:
            time.sleep(args.interval)

    xml_path = matched_xml or dump_ui(out_dir)
    print("已采集：")
    for path in captured:
        print(path)
    if xml_path:
        print(xml_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
