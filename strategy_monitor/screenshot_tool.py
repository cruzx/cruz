#!/usr/bin/env python3
"""Screenshot collection core for music app competitive research."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import time
import xml.etree.ElementTree as ET
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
LIBRARY_DIR = ROOT / "screenshot_library"
IMAGE_DIR = LIBRARY_DIR / "images"
DB_PATH = LIBRARY_DIR / "screenshots.sqlite3"
CONFIG_PATH = ROOT / "screenshot_targets.json"
LOCAL_ADB = ROOT / "tools" / "platform-tools" / "adb"
SDK_ADB = ROOT / "tools" / "android-sdk" / "platform-tools" / "adb"
ADB = str(SDK_ADB) if SDK_ADB.exists() else (str(LOCAL_ADB) if LOCAL_ADB.exists() else "adb")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


DEFAULT_CONFIG: dict[str, Any] = {
    "platforms": [
        {
            "platform": "apple_music",
            "app_name": "Apple Music",
            "ios_bundle_id": "com.apple.Music",
            "android_package": "com.apple.android.music",
            "screens": [
                {"name": "首页推荐", "wait_seconds": 3, "steps": []},
                {"name": "播放页", "wait_seconds": 3, "steps": []},
                {"name": "搜索页", "wait_seconds": 3, "steps": []},
                {"name": "资料库", "wait_seconds": 3, "steps": []},
                {"name": "电台页", "wait_seconds": 3, "steps": []},
            ],
        },
        {
            "platform": "spotify",
            "app_name": "Spotify",
            "ios_bundle_id": "com.spotify.client",
            "android_package": "com.spotify.music",
            "screens": [
                {"name": "首页推荐", "wait_seconds": 3, "steps": []},
                {"name": "播放页", "wait_seconds": 3, "steps": []},
                {"name": "搜索页", "wait_seconds": 3, "steps": []},
                {"name": "歌单详情", "wait_seconds": 3, "steps": []},
                {"name": "个人主页", "wait_seconds": 3, "steps": []},
            ],
        },
        {
            "platform": "qishui",
            "app_name": "汽水音乐",
            "ios_bundle_id": "",
            "android_package": "com.luna.music",
            "screens": [
                {"name": "首页推荐", "wait_seconds": 3, "steps": []},
                {"name": "播放页", "wait_seconds": 3, "steps": []},
                {"name": "搜索页", "wait_seconds": 3, "steps": []},
                {"name": "会员页", "wait_seconds": 3, "steps": []},
                {"name": "活动页", "wait_seconds": 3, "steps": []},
            ],
        },
        {
            "platform": "netease_music",
            "app_name": "网易云音乐",
            "ios_bundle_id": "",
            "android_package": "com.netease.cloudmusic",
            "screens": [
                {"name": "首页推荐", "wait_seconds": 3, "steps": []},
                {"name": "播放页", "wait_seconds": 3, "steps": []},
                {"name": "搜索页", "wait_seconds": 3, "steps": []},
                {"name": "歌单详情", "wait_seconds": 3, "steps": []},
                {"name": "评论区", "wait_seconds": 3, "steps": []},
            ],
        },
        {
            "platform": "qq_music",
            "app_name": "QQ 音乐",
            "ios_bundle_id": "",
            "android_package": "com.tencent.qqmusic",
            "screens": [
                {"name": "首页推荐", "wait_seconds": 3, "steps": []},
                {"name": "播放页", "wait_seconds": 3, "steps": []},
                {"name": "搜索页", "wait_seconds": 3, "steps": []},
                {"name": "会员页", "wait_seconds": 3, "steps": []},
                {"name": "评论区", "wait_seconds": 3, "steps": []},
            ],
        },
        {
            "platform": "kugou",
            "app_name": "酷狗音乐",
            "ios_bundle_id": "",
            "android_package": "com.kugou.android",
            "screens": [
                {"name": "首页推荐", "wait_seconds": 3, "steps": []},
                {"name": "播放页", "wait_seconds": 3, "steps": []},
                {"name": "搜索页", "wait_seconds": 3, "steps": []},
                {"name": "会员页", "wait_seconds": 3, "steps": []},
                {"name": "个人主页", "wait_seconds": 3, "steps": []},
            ],
        },
    ],
    "capture_states": ["未登录态", "已登录普通用户", "已登录会员态", "灰度曝光态", "人工补录"],
    "device_types": ["android", "ios_simulator", "manual"],
}


@dataclass(frozen=True)
class ScreenshotInput:
    platform: str
    app_name: str
    screen_name: str
    device_type: str
    capture_state: str
    app_version: str
    source: str
    notes: str = ""
    captured_at: str | None = None


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def local_now_slug() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def slugify(value: str, fallback: str = "item") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned[:80] or fallback


def ensure_library() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    init_db()


def connect() -> sqlite3.Connection:
    ensure_dirs_only()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_dirs_only() -> None:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    ensure_dirs_only()
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS screenshots (
              id TEXT PRIMARY KEY,
              platform TEXT NOT NULL,
              app_name TEXT NOT NULL,
              screen_name TEXT NOT NULL,
              device_type TEXT NOT NULL,
              capture_state TEXT NOT NULL,
              app_version TEXT NOT NULL DEFAULT '',
              image_path TEXT NOT NULL,
              file_name TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              perceptual_hash TEXT NOT NULL,
              ocr_text TEXT NOT NULL DEFAULT '',
              ui_modules TEXT NOT NULL DEFAULT '[]',
              feature_tags TEXT NOT NULL DEFAULT '[]',
              visual_notes TEXT NOT NULL DEFAULT '',
              change_type TEXT NOT NULL DEFAULT '',
              source TEXT NOT NULL DEFAULT 'manual',
              notes TEXT NOT NULL DEFAULT '',
              captured_at TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_screenshots_lookup
              ON screenshots(platform, screen_name, device_type, capture_state, captured_at);
            CREATE INDEX IF NOT EXISTS idx_screenshots_hash
              ON screenshots(platform, screen_name, perceptual_hash);

            CREATE TABLE IF NOT EXISTS capture_runs (
              id TEXT PRIMARY KEY,
              platform TEXT NOT NULL,
              screen_name TEXT NOT NULL,
              device_type TEXT NOT NULL,
              status TEXT NOT NULL,
              message TEXT NOT NULL DEFAULT '',
              screenshot_id TEXT,
              created_at TEXT NOT NULL
            );
            """
        )


def load_config() -> dict[str, Any]:
    ensure_library()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = DEFAULT_CONFIG
    if not isinstance(data, dict) or "platforms" not in data:
        return DEFAULT_CONFIG
    changed = False
    for platform in data.get("platforms", []):
        if not isinstance(platform, dict):
            continue
        screens = platform.get("screens") or []
        normalized = [normalize_screen(screen) for screen in screens]
        if normalized != screens:
            platform["screens"] = normalized
            changed = True
    if changed:
        CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def save_config(raw_json: str) -> dict[str, Any]:
    data = json.loads(raw_json)
    if not isinstance(data, dict) or not isinstance(data.get("platforms"), list):
        raise ValueError("配置必须包含 platforms 数组。")
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def platform_options() -> list[dict[str, Any]]:
    return list(load_config().get("platforms", []))


def find_platform(platform: str) -> dict[str, Any]:
    for item in platform_options():
        if item.get("platform") == platform:
            return item
    options = platform_options()
    return options[0] if options else DEFAULT_CONFIG["platforms"][0]


def normalize_screen(screen: Any) -> dict[str, Any]:
    if isinstance(screen, dict):
        name = str(screen.get("name") or screen.get("screen_name") or "首页推荐")
        steps = screen.get("steps") if isinstance(screen.get("steps"), list) else []
        return {
            "name": name,
            "wait_seconds": float(screen.get("wait_seconds", 3) or 0),
            "steps": steps,
        }
    return {"name": str(screen), "wait_seconds": 3.0, "steps": []}


def screen_options(platform: str) -> list[dict[str, Any]]:
    item = find_platform(platform)
    screens = item.get("screens") or ["首页推荐"]
    return [normalize_screen(screen) for screen in screens]


def find_screen(platform: str, screen_name: str) -> dict[str, Any]:
    options = screen_options(platform)
    for screen in options:
        if screen["name"] == screen_name:
            return screen
    return options[0] if options else {"name": "首页推荐", "wait_seconds": 3.0, "steps": []}


def first_screen(platform: str) -> str:
    return find_screen(platform, "")["name"]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def visual_fingerprint(path: Path) -> str:
    data = path.read_bytes()
    suffix = path.suffix.lower().lstrip(".")
    header = data[:4096]
    tail = data[-4096:] if len(data) > 4096 else data
    sample_count = min(64, max(1, len(data)))
    step = max(1, len(data) // sample_count)
    sampled = bytes(data[index] for index in range(0, len(data), step)[:sample_count])
    return hashlib.sha1(suffix.encode("utf-8") + header + sampled + tail).hexdigest()


def unique_image_path(meta: ScreenshotInput, suffix: str) -> Path:
    date_part = dt.date.today().isoformat()
    directory = IMAGE_DIR / slugify(meta.platform) / date_part
    directory.mkdir(parents=True, exist_ok=True)
    base = "_".join(
        [
            slugify(meta.platform),
            slugify(meta.screen_name, "screen"),
            slugify(meta.device_type, "device"),
            slugify(meta.capture_state, "state"),
            slugify(meta.app_version, "version"),
            local_now_slug(),
        ]
    )
    candidate = directory / f"{base}{suffix.lower()}"
    for index in range(2, 1000):
        if not candidate.exists():
            return candidate
        candidate = directory / f"{base}_{index}{suffix.lower()}"
    raise RuntimeError("无法生成唯一文件名。")


def infer_modules(screen_name: str, notes: str) -> list[str]:
    text = f"{screen_name} {notes}"
    modules: list[str] = []
    rules = [
        ("首页", "推荐流"),
        ("推荐", "推荐流"),
        ("播放", "播放器"),
        ("搜索", "搜索框"),
        ("歌单", "歌单信息"),
        ("评论", "评论列表"),
        ("会员", "会员权益"),
        ("活动", "运营活动"),
        ("个人", "个人资料"),
    ]
    for keyword, module in rules:
        if keyword in text and module not in modules:
            modules.append(module)
    return modules or ["待人工确认"]


def infer_tags(screen_name: str, capture_state: str, notes: str) -> list[str]:
    text = f"{screen_name} {capture_state} {notes}"
    tags: list[str] = []
    rules = [
        ("AI", "AI 功能"),
        ("推荐", "推荐算法"),
        ("会员", "会员权益"),
        ("VIP", "会员权益"),
        ("评论", "社交互动"),
        ("个人", "社交互动"),
        ("活动", "活动运营"),
        ("搜索", "搜索体验"),
        ("播放", "播放体验"),
        ("歌单", "内容组织"),
    ]
    for keyword, tag in rules:
        if keyword.lower() in text.lower() and tag not in tags:
            tags.append(tag)
    return tags or ["待分类"]


def change_type_for(meta: ScreenshotInput, perceptual_hash: str) -> str:
    with connect() as conn:
        latest = conn.execute(
            """
            SELECT perceptual_hash
            FROM screenshots
            WHERE platform = ? AND screen_name = ? AND device_type = ? AND capture_state = ?
            ORDER BY captured_at DESC, created_at DESC
            LIMIT 1
            """,
            (meta.platform, meta.screen_name, meta.device_type, meta.capture_state),
        ).fetchone()
    if latest is None:
        return "首次采集"
    if latest["perceptual_hash"] == perceptual_hash:
        return "无明显变化"
    return "疑似页面变化"


def import_image(source_path: Path, meta: ScreenshotInput) -> tuple[str, bool]:
    ensure_library()
    if source_path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError("只支持 png/jpg/jpeg/webp 截图。")
    target = unique_image_path(meta, source_path.suffix)
    shutil.copy2(source_path, target)
    return register_image(target, meta)


def register_image(path: Path, meta: ScreenshotInput) -> tuple[str, bool]:
    ensure_library()
    content = file_hash(path)
    visual = visual_fingerprint(path)
    change_type = change_type_for(meta, visual)
    captured_at = meta.captured_at or utc_now()
    created_at = utc_now()
    screenshot_id = uuid.uuid4().hex
    modules = infer_modules(meta.screen_name, meta.notes)
    tags = infer_tags(meta.screen_name, meta.capture_state, meta.notes)
    visual_notes = meta.notes or f"{meta.app_name} / {meta.screen_name} / {meta.capture_state}"

    with connect() as conn:
        duplicate = conn.execute(
            """
            SELECT id
            FROM screenshots
            WHERE platform = ? AND screen_name = ? AND device_type = ?
              AND capture_state = ? AND perceptual_hash = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (meta.platform, meta.screen_name, meta.device_type, meta.capture_state, visual),
        ).fetchone()
        if duplicate:
            return str(duplicate["id"]), False
        conn.execute(
            """
            INSERT INTO screenshots (
              id, platform, app_name, screen_name, device_type, capture_state,
              app_version, image_path, file_name, content_hash, perceptual_hash,
              ocr_text, ui_modules, feature_tags, visual_notes, change_type,
              source, notes, captured_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                screenshot_id,
                meta.platform,
                meta.app_name,
                meta.screen_name,
                meta.device_type,
                meta.capture_state,
                meta.app_version,
                str(path),
                path.name,
                content,
                visual,
                "",
                json.dumps(modules, ensure_ascii=False),
                json.dumps(tags, ensure_ascii=False),
                visual_notes,
                change_type,
                meta.source,
                meta.notes,
                captured_at,
                created_at,
            ),
        )
    return screenshot_id, True


def list_screenshots(filters: dict[str, str] | None = None, limit: int = 300) -> list[sqlite3.Row]:
    filters = filters or {}
    clauses: list[str] = []
    params: list[Any] = []
    for column in ("platform", "screen_name", "device_type", "capture_state"):
        value = filters.get(column)
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    with connect() as conn:
        return list(
            conn.execute(
                f"""
                SELECT *
                FROM screenshots
                {where}
                ORDER BY captured_at DESC, created_at DESC
                LIMIT ?
                """,
                (*params, limit),
            )
        )


def get_screenshot(screenshot_id: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM screenshots WHERE id = ?", (screenshot_id,)).fetchone()


def delete_screenshot(screenshot_id: str) -> bool:
    row = get_screenshot(screenshot_id)
    if row is None:
        return False
    with connect() as conn:
        conn.execute("DELETE FROM screenshots WHERE id = ?", (screenshot_id,))
    path = Path(row["image_path"])
    if path.exists() and path.is_file():
        path.unlink()
    return True


def distinct_values(column: str) -> list[str]:
    if column not in {"platform", "screen_name", "device_type", "capture_state"}:
        return []
    with connect() as conn:
        rows = conn.execute(f"SELECT DISTINCT {column} AS value FROM screenshots ORDER BY value").fetchall()
    return [str(row["value"]) for row in rows if row["value"]]


def run(command: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def parse_bounds(bounds: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not match:
        return None
    left, top, right, bottom = [int(value) for value in match.groups()]
    if right <= left or bottom <= top:
        return None
    return ((left + right) // 2, (top + bottom) // 2)


def dump_android_ui() -> str:
    remote = "/sdcard/music_app_window.xml"
    result = run([ADB, "shell", "uiautomator", "dump", remote], timeout=20)
    if result.returncode != 0:
        raise RuntimeError(f"读取页面结构失败：{result.stderr.strip() or result.stdout.strip()}")
    pulled = run([ADB, "shell", "cat", remote], timeout=20)
    run([ADB, "shell", "rm", remote], timeout=10)
    if pulled.returncode != 0:
        raise RuntimeError(f"拉取页面结构失败：{pulled.stderr.strip() or pulled.stdout.strip()}")
    return pulled.stdout


def android_nodes() -> list[dict[str, str]]:
    xml_text = dump_android_ui()
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"页面结构解析失败：{exc}") from exc
    nodes: list[dict[str, str]] = []
    for node in root.iter("node"):
        label_parts = []
        for attr in ("text", "content-desc", "resource-id"):
            value = node.attrib.get(attr, "")
            if value:
                label_parts.append(value)
        label = "\n".join(label_parts)
        bounds = node.attrib.get("bounds", "")
        if label and bounds:
            nodes.append(
                {
                    "label": label,
                    "text": node.attrib.get("text", ""),
                    "content_desc": node.attrib.get("content-desc", ""),
                    "resource_id": node.attrib.get("resource-id", ""),
                    "bounds": bounds,
                    "clickable": node.attrib.get("clickable", "false"),
                    "enabled": node.attrib.get("enabled", "true"),
                }
            )
    return nodes


def find_android_node(query: str, *, exact: bool = False) -> dict[str, str] | None:
    needle = query.lower().strip()
    candidates: list[tuple[int, dict[str, str]]] = []
    for node in android_nodes():
        if node.get("enabled") == "false":
            continue
        label = node["label"]
        haystack = label.lower()
        matched = haystack == needle if exact else needle in haystack
        if not matched:
            continue
        score = 0
        if node.get("clickable") == "true":
            score += 5
        if node.get("text", "").lower() == needle:
            score += 4
        if node.get("content_desc", "").lower() == needle:
            score += 3
        if needle in node.get("resource_id", "").lower():
            score += 2
        candidates.append((score, node))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def tap_android_node(query: str, *, exact: bool = False) -> str:
    node = find_android_node(query, exact=exact)
    if not node:
        raise RuntimeError(f"没有找到可点击元素：{query}")
    center = parse_bounds(node["bounds"])
    if not center:
        raise RuntimeError(f"元素坐标无效：{query}")
    result = run([ADB, "shell", "input", "tap", str(center[0]), str(center[1])], timeout=20)
    if result.returncode != 0:
        raise RuntimeError(f"点击元素失败：{query}")
    return node["label"]


def wait_android_text(query: str, *, timeout_seconds: float = 8, exact: bool = False) -> str:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() <= deadline:
        try:
            node = find_android_node(query, exact=exact)
        except Exception as exc:
            last_error = str(exc)
            node = None
        if node:
            return node["label"]
        time.sleep(0.5)
    raise RuntimeError(f"等待文案超时：{query}{'；' + last_error if last_error else ''}")


def android_screenshot_to_library(meta: ScreenshotInput) -> tuple[str, bool]:
    target = unique_image_path(meta, ".png")
    remote = "/sdcard/music_app_screenshot.png"
    shot = run([ADB, "shell", "screencap", "-p", remote], timeout=30)
    if shot.returncode != 0:
        raise RuntimeError(f"Android 截图失败：{shot.stderr.strip() or shot.stdout.strip()}")
    pull = run([ADB, "pull", remote, str(target)], timeout=40)
    run([ADB, "shell", "rm", remote], timeout=20)
    if pull.returncode != 0 or not target.exists():
        raise RuntimeError(f"拉取截图失败：{pull.stderr.strip() or pull.stdout.strip()}")
    return register_image(target, meta)


def apply_android_steps(
    steps: list[dict[str, Any]] | None,
    *,
    screenshot_callback: "callable[[dict[str, Any]], None] | None" = None,
) -> None:
    for step in steps or []:
        action = step.get("action")
        if action == "sleep":
            time.sleep(float(step.get("seconds", 1)))
        elif action == "tap":
            run([ADB, "shell", "input", "tap", str(step.get("x", 0)), str(step.get("y", 0))], timeout=20)
        elif action == "text":
            value = str(step.get("value", "")).replace(" ", "%s")
            run([ADB, "shell", "input", "text", value], timeout=20)
        elif action == "keyevent":
            run([ADB, "shell", "input", "keyevent", str(step.get("code", "KEYCODE_ENTER"))], timeout=20)
        elif action == "swipe":
            run(
                [
                    ADB,
                    "shell",
                    "input",
                    "swipe",
                    str(step.get("x1", 500)),
                    str(step.get("y1", 1600)),
                    str(step.get("x2", 500)),
                    str(step.get("y2", 500)),
                    str(step.get("duration_ms", 400)),
                ],
                timeout=20,
            )
        elif action == "back":
            run([ADB, "shell", "input", "keyevent", "KEYCODE_BACK"], timeout=20)
        elif action in {"tap_text", "tap_contains"}:
            tap_android_node(str(step.get("text") or step.get("value") or ""), exact=False)
        elif action == "tap_exact":
            tap_android_node(str(step.get("text") or step.get("value") or ""), exact=True)
        elif action in {"wait_text", "wait_contains"}:
            wait_android_text(
                str(step.get("text") or step.get("value") or ""),
                timeout_seconds=float(step.get("timeout", 8)),
                exact=False,
            )
        elif action == "wait_exact":
            wait_android_text(
                str(step.get("text") or step.get("value") or ""),
                timeout_seconds=float(step.get("timeout", 8)),
                exact=True,
            )
        elif action == "screenshot" and screenshot_callback:
            screenshot_callback(step)


def capture_android(meta: ScreenshotInput, package_name: str = "", steps: list[dict[str, Any]] | None = None) -> tuple[str, bool]:
    ensure_library()
    result = run([ADB, "devices"], timeout=20)
    if result.returncode != 0 or "\tdevice" not in result.stdout:
        raise RuntimeError("未检测到可用 Android 设备，请先连接手机/模拟器并授权 adb。")
    if package_name:
        launch = run([ADB, "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"], timeout=30)
        if launch.returncode != 0:
            raise RuntimeError(f"启动 Android App 失败：{launch.stderr.strip() or launch.stdout.strip()}")
        time.sleep(2)
    screen = find_screen(meta.platform, meta.screen_name)
    apply_android_steps(steps if steps is not None else screen.get("steps", []))
    wait_seconds = float(screen.get("wait_seconds", 0) or 0)
    if wait_seconds > 0:
        time.sleep(wait_seconds)
    return android_screenshot_to_library(meta)


def run_android_flow(
    platform: str,
    flow_steps: list[dict[str, Any]],
    *,
    capture_state: str = "已登录普通用户",
    app_version: str = "",
    notes: str = "",
    launch_app: bool = True,
) -> list[dict[str, Any]]:
    ensure_library()
    info = find_platform(platform)
    package_name = str(info.get("android_package", ""))
    result = run([ADB, "devices"], timeout=20)
    if result.returncode != 0 or "\tdevice" not in result.stdout:
        raise RuntimeError("未检测到可用 Android 设备，请先连接手机/模拟器并授权 adb。")
    if launch_app and package_name:
        launch = run([ADB, "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"], timeout=30)
        if launch.returncode != 0:
            raise RuntimeError(f"启动 Android App 失败：{launch.stderr.strip() or launch.stdout.strip()}")
        time.sleep(2)

    captures: list[dict[str, Any]] = []

    def capture_from_step(step: dict[str, Any]) -> None:
        screen_name = str(step.get("screen_name") or step.get("name") or "流程截图")
        meta = ScreenshotInput(
            platform=platform,
            app_name=str(info.get("app_name", platform)),
            screen_name=screen_name,
            device_type="android",
            capture_state=capture_state,
            app_version=app_version,
            source="android_flow",
            notes=notes or str(step.get("notes") or "流程自动抓图"),
        )
        screenshot_id, is_new = android_screenshot_to_library(meta)
        message = "新增截图" if is_new else "重复截图"
        record_run(platform, screen_name, "android", "ok", message, screenshot_id)
        captures.append({"screen_name": screen_name, "ok": True, "message": message, "id": screenshot_id})

    try:
        apply_android_steps(flow_steps, screenshot_callback=capture_from_step)
    except Exception as exc:
        record_run(platform, "流程采集", "android", "failed", f"{type(exc).__name__}: {str(exc)[:240]}")
        raise
    if not captures:
        capture_from_step({"screen_name": "流程结束"})
    return captures


def auto_capture_android(
    platform: str,
    screen_names: list[str] | None = None,
    *,
    capture_state: str = "已登录普通用户",
    app_version: str = "",
    notes: str = "",
) -> list[dict[str, Any]]:
    info = find_platform(platform)
    package_name = str(info.get("android_package", ""))
    selected_screens = screen_names or [screen["name"] for screen in screen_options(platform)]
    results: list[dict[str, Any]] = []
    for screen_name in selected_screens:
        meta = ScreenshotInput(
            platform=platform,
            app_name=str(info.get("app_name", platform)),
            screen_name=screen_name,
            device_type="android",
            capture_state=capture_state,
            app_version=app_version,
            source="auto_android",
            notes=notes,
        )
        try:
            screen = find_screen(platform, screen_name)
            screenshot_id, is_new = capture_android(meta, package_name=package_name, steps=screen.get("steps", []))
            message = "新增截图" if is_new else "重复截图"
            record_run(platform, screen_name, "android", "ok", message, screenshot_id)
            results.append({"screen_name": screen_name, "ok": True, "message": message, "id": screenshot_id})
        except Exception as exc:
            message = f"{type(exc).__name__}: {str(exc)[:240]}"
            record_run(platform, screen_name, "android", "failed", message)
            results.append({"screen_name": screen_name, "ok": False, "message": message})
    return results


def capture_ios_simulator(meta: ScreenshotInput) -> tuple[str, bool]:
    ensure_library()
    target = unique_image_path(meta, ".png")
    result = run(["xcrun", "simctl", "io", "booted", "screenshot", str(target)], timeout=40)
    if result.returncode != 0 or not target.exists():
        raise RuntimeError(f"iOS 模拟器截图失败：{result.stderr.strip() or result.stdout.strip()}")
    return register_image(target, meta)


def record_run(platform: str, screen_name: str, device_type: str, status: str, message: str, screenshot_id: str | None = None) -> None:
    ensure_library()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO capture_runs (id, platform, screen_name, device_type, status, message, screenshot_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uuid.uuid4().hex, platform, screen_name, device_type, status, message, screenshot_id, utc_now()),
        )


def recent_runs(limit: int = 20) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(conn.execute("SELECT * FROM capture_runs ORDER BY created_at DESC LIMIT ?", (limit,)))
