#!/usr/bin/env python3
"""Local web app for uploading screenshots, collecting Qishui screenshots, and generating reports."""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, PlainTextResponse


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
PROJECT_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
PYTHON = str(PROJECT_PYTHON) if PROJECT_PYTHON.exists() else sys.executable
REFERENCE_DIR = ROOT / "references"
QISHUI_DIR = ROOT / "qishui_daily"
QQ_MUSIC_DIR = ROOT / "qqmusic_daily"
REPORT_DIR = ROOT / "reports"
SETTINGS_PATH = ROOT / "local_settings.json"
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".md", ".txt", ".json", ".xml"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
APP_CONFIG = {
    "qishui": {
        "name": "汽水音乐",
        "short": "汽水",
        "package": "com.luna.music",
        "dir": QISHUI_DIR,
        "report_prefix": "qishui",
        "trigger_keywords": ["免费模式", "免费听", "看视频", "看广告", "会员歌", "VIP", "会员", "畅听", "播放"],
    },
    "qqmusic": {
        "name": "QQ 音乐",
        "short": "QQ",
        "package": "com.tencent.qqmusic",
        "dir": QQ_MUSIC_DIR,
        "report_prefix": "qqmusic",
        "trigger_keywords": ["免费听", "免费模式", "看视频", "看广告", "会员歌", "VIP", "会员", "试听", "播放"],
    },
}

app = FastAPI(title="免费听策略监控")
TASKS: dict[str, dict[str, object]] = {}
TASK_LOCK = threading.Lock()


def today() -> str:
    return dt.date.today().isoformat()


def safe_date(value: str | None) -> str:
    value = value or today()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return today()
    return value


def safe_app(value: str | None) -> str:
    return value if value in APP_CONFIG else "qishui"


def load_settings() -> dict[str, str]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {str(key): str(value) for key, value in data.items() if value}


def save_settings(settings: dict[str, str]) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def report_env() -> dict[str, str]:
    env = os.environ.copy()
    settings = load_settings()
    for key in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL"):
        if settings.get(key):
            env[key] = settings[key]
    return env


def update_task(task_id: str, **changes: object) -> None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is not None:
            task.update(changes)


def complete_task(task_id: str, message: str, redirect_url: str, ok: bool = True) -> None:
    update_task(
        task_id,
        status="completed" if ok else "failed",
        progress=100,
        message=message,
        redirect_url=redirect_url,
    )


def start_task(label: str, redirect_url: str, worker: "callable[[str], None]") -> JSONResponse:
    task_id = uuid.uuid4().hex
    with TASK_LOCK:
        TASKS[task_id] = {
            "id": task_id,
            "label": label,
            "status": "running",
            "progress": 1,
            "message": "准备开始...",
            "redirect_url": redirect_url,
        }
    thread = threading.Thread(target=worker, args=(task_id,), daemon=True)
    thread.start()
    return JSONResponse({"task_id": task_id})


def run_command_with_progress(
    task_id: str,
    command: list[str],
    progress_start: int,
    progress_end: int,
    message: str,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    update_task(task_id, progress=progress_start, message=message)
    process = subprocess.Popen(
        command,
        cwd=ROOT.parent,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    progress = progress_start
    while process.poll() is None:
        progress = min(progress + 2, progress_end)
        update_task(task_id, progress=progress)
        time.sleep(0.8)
    stdout, stderr = process.communicate()
    update_task(task_id, progress=progress_end)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def safe_name(name: str) -> str:
    stem = Path(name).stem or "upload"
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        suffix = ".png"
    clean_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "upload"
    return clean_stem[:80] + suffix


def unique_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(2, 1000):
        next_candidate = directory / f"{stem}_{index}{suffix}"
        if not next_candidate.exists():
            return next_candidate
    raise RuntimeError("Too many duplicate filenames.")


def list_names(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted(path.name for path in directory.iterdir() if path.is_file())


def is_image(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_SUFFIXES


def target_dir(kind: str, date: str, app_key: str = "qishui") -> Path:
    if kind == "reference":
        return REFERENCE_DIR
    if kind == "competitor":
        return APP_CONFIG[safe_app(app_key)]["dir"] / date
    raise HTTPException(status_code=404, detail="Unknown file group.")


def safe_existing_file(kind: str, date: str, filename: str, app_key: str = "qishui") -> Path:
    name = safe_name(filename)
    path = target_dir(kind, date, app_key) / name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return path


def gallery(kind: str, title: str, description: str, date: str, names: list[str], app_key: str) -> str:
    cards = []
    for name in names:
        escaped = html.escape(name)
        url = f"/asset/{kind}/{html.escape(app_key)}/{html.escape(date)}/{escaped}"
        if is_image(name):
            preview = f'<button class="thumb" type="button" data-preview="{url}" data-name="{escaped}"><img src="{url}" alt="{escaped}" /></button>'
        else:
            preview = f'<a class="doc" href="{url}" target="_blank" rel="noreferrer">{escaped}</a>'
        cards.append(
            f"""
            <article class="asset-card">
              {preview}
              <div class="asset-meta">
                <span title="{escaped}">{escaped}</span>
                <form method="post" action="/delete">
                  <input type="hidden" name="date" value="{html.escape(date)}" />
                  <input type="hidden" name="kind" value="{kind}" />
                  <input type="hidden" name="app_key" value="{html.escape(app_key)}" />
                  <input type="hidden" name="filename" value="{escaped}" />
                  <button class="danger" type="submit">删除</button>
                </form>
              </div>
            </article>
            """
        )
    card_html = "".join(cards) or '<div class="empty">还没有素材，拖拽图片到这里即可上传。</div>'
    return f"""
    <section class="upload-panel">
      <div class="panel-head">
        <div>
          <h2>{html.escape(title)}</h2>
          <p>{html.escape(description)}</p>
        </div>
      </div>
      <form class="dropzone" method="post" action="/upload" enctype="multipart/form-data">
        <input type="hidden" name="date" value="{html.escape(date)}" />
        <input type="hidden" name="kind" value="{kind}" />
        <input type="hidden" name="app_key" value="{html.escape(app_key)}" />
        <input class="file-input" type="file" name="files" multiple accept=".png,.jpg,.jpeg,.webp,.md,.txt,.json" />
        <strong>拖拽到这里上传</strong>
        <span>或点击选择图片/笔记</span>
      </form>
      <div class="asset-grid">{card_html}</div>
    </section>
    """


def report_text(date: str, app_key: str) -> str | None:
    app_key = safe_app(app_key)
    path = REPORT_DIR / f"{APP_CONFIG[app_key]['report_prefix']}_{date}.md"
    if not path.exists() and app_key == "qishui":
        path = REPORT_DIR / f"{date}.md"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def render_page(date: str, app_key: str = "qishui", message: str = "") -> str:
    app_key = safe_app(app_key)
    app_info = APP_CONFIG[app_key]
    refs = list_names(REFERENCE_DIR)
    competitor = list_names(app_info["dir"] / date)
    report = report_text(date, app_key)
    settings = load_settings()
    api_status = "已配置" if settings.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY") else "未配置"
    model_value = settings.get("OPENAI_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-4.1-mini"
    base_url_value = settings.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or ""
    local_adb = ROOT / "tools" / "platform-tools" / "adb"
    sdk_adb = ROOT / "tools" / "android-sdk" / "platform-tools" / "adb"
    adb_status = "已安装 SDK adb" if sdk_adb.exists() else ("已安装本地 adb" if local_adb.exists() else "未安装 adb")
    escaped_report = html.escape(report) if report else "还没有生成报告。"
    message_html = f'<div class="message">{html.escape(message)}</div>' if message else ""
    app_options = "".join(
        f'<option value="{key}" {"selected" if key == app_key else ""}>{html.escape(value["name"])}</option>'
        for key, value in APP_CONFIG.items()
    )
    reference_gallery = gallery("reference", "我们的参考图", "用于和竞品策略做对比的自家弹窗、方案图或笔记。", date, refs, app_key)
    competitor_gallery = gallery(
        "competitor",
        f"{app_info['short']}免费模式图",
        f"只放{app_info['name']}中关于免费模式、看视频免费听、会员歌权益的截图。",
        date,
        competitor,
        app_key,
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>免费听策略监控</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f7fb;
      --panel: #ffffff;
      --text: #18202f;
      --muted: #657083;
      --line: #dce3ee;
      --blue: #0aa8f5;
      --blue-dark: #087cc0;
      --ink: #101828;
      --red: #d92d20;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 20px;
      padding: 24px clamp(18px, 4vw, 32px);
      background: var(--ink);
      color: white;
    }}
    h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
    header p {{ margin: 0; color: #cbd5e1; }}
    .header-actions {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex: 0 0 auto;
    }}
    .header-actions form {{ margin: 0; }}
    .header-actions button, .header-actions .button {{
      margin: 0;
      min-width: 150px;
      background: #0aa8f5;
      box-shadow: 0 10px 24px rgba(10, 168, 245, 0.24);
    }}
    .header-actions .secondary {{
      min-width: 118px;
      background: rgba(255, 255, 255, 0.12);
      color: white;
      box-shadow: none;
    }}
    .header-actions .secondary:hover {{ background: rgba(255, 255, 255, 0.18); }}
    .top-controls {{
      grid-column: 1 / -1;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      box-shadow: 0 10px 24px rgba(16, 24, 40, 0.05);
    }}
    .top-controls form {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      margin: 0;
    }}
    .top-controls label {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin: 0;
      color: var(--muted);
      font-size: 14px;
      white-space: nowrap;
    }}
    .top-controls input, .top-controls select {{
      width: auto;
      min-width: 150px;
      padding: 8px 10px;
      font-size: 14px;
    }}
    .top-controls select {{ min-width: 132px; }}
    main {{
      display: grid;
      grid-template-columns: minmax(280px, 380px) minmax(0, 1fr);
      gap: 20px;
      align-items: start;
      padding: 24px clamp(18px, 4vw, 32px) 36px;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      box-shadow: 0 12px 30px rgba(16, 24, 40, 0.06);
    }}
    h2 {{ margin: 0 0 14px; font-size: 18px; }}
    p {{ margin: 0; }}
    label {{ display: block; margin: 12px 0 6px; color: var(--muted); font-size: 14px; }}
    input, select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 11px;
      font-size: 15px;
      background: #fff;
    }}
    button, .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 0;
      border-radius: 8px;
      min-height: 40px;
      padding: 0 14px;
      margin-top: 12px;
      background: var(--blue);
      color: white;
      font-weight: 700;
      text-decoration: none;
      cursor: pointer;
    }}
    button:hover, .button:hover {{ background: var(--blue-dark); }}
    .secondary {{ background: #eef2f7; color: #1f2937; }}
    .secondary:hover {{ background: #e2e8f0; }}
    .stack {{ display: grid; gap: 16px; min-width: 0; }}
    .upload-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: 16px; }}
    .upload-panel {{ min-width: 0; }}
    .panel-head p {{ color: var(--muted); font-size: 14px; line-height: 1.45; margin-top: -4px; }}
    .dropzone {{
      margin-top: 14px;
      border: 1.5px dashed #a9b7ca;
      border-radius: 8px;
      min-height: 112px;
      display: grid;
      place-items: center;
      gap: 4px;
      text-align: center;
      color: var(--muted);
      background: #f8fbff;
      cursor: pointer;
      padding: 18px;
    }}
    .dropzone strong {{ color: var(--text); }}
    .dropzone.dragging {{ border-color: var(--blue); background: #eef9ff; }}
    .file-input {{ display: none; }}
    .asset-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(128px, 1fr)); gap: 12px; margin-top: 14px; }}
    .asset-card {{ border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: #fff; }}
    .thumb {{ display: block; width: 100%; height: 120px; margin: 0; padding: 0; border: 0; border-radius: 0; background: #eef2f7; }}
    .thumb:hover {{ background: #e2e8f0; }}
    .thumb img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
    .doc {{ display: flex; height: 120px; align-items: center; justify-content: center; padding: 10px; color: var(--text); background: #f8fafc; text-decoration: none; word-break: break-word; }}
    .asset-meta {{ display: grid; gap: 8px; padding: 9px; }}
    .asset-meta span {{ color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .danger {{ min-height: 30px; margin: 0; width: 100%; background: #fff1f0; color: var(--red); }}
    .danger:hover {{ background: #ffe4e0; }}
    .empty {{ grid-column: 1 / -1; color: var(--muted); background: #f8fafc; border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .message {{
      grid-column: 1 / -1;
      background: #e8f7ff;
      border: 1px solid #b9e8ff;
      color: #075985;
      border-radius: 8px;
      padding: 12px 14px;
    }}
    .progress-panel {{
      grid-column: 1 / -1;
      background: #ffffff;
      border: 1px solid #b9e8ff;
      border-radius: 8px;
      padding: 12px 14px;
      box-shadow: 0 10px 24px rgba(16, 24, 40, 0.05);
    }}
    .progress-panel[hidden] {{ display: none; }}
    .progress-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 9px;
      color: #075985;
      font-weight: 700;
    }}
    .progress-track {{
      height: 9px;
      overflow: hidden;
      border-radius: 999px;
      background: #e2edf7;
    }}
    .progress-bar {{
      width: 0%;
      height: 100%;
      border-radius: inherit;
      background: var(--blue);
      transition: width 0.25s ease;
    }}
    .progress-message {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
    }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0;
      font: 14px/1.6 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }}
    .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .hint {{ color: var(--muted); font-size: 14px; line-height: 1.5; margin: 8px 0 4px; }}
    dialog {{ border: 0; border-radius: 8px; padding: 0; width: min(920px, 92vw); background: #111827; }}
    dialog::backdrop {{ background: rgba(15, 23, 42, 0.72); }}
    .preview-head {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; color: white; padding: 10px 12px; }}
    .preview-head button {{ margin: 0; background: #374151; }}
    .preview-body {{ padding: 0 12px 12px; }}
    .preview-body img {{ width: 100%; max-height: 78vh; object-fit: contain; display: block; background: #030712; }}
    @media (max-width: 900px) {{
      main {{ grid-template-columns: 1fr; padding: 18px; }}
      header {{ flex-direction: column; padding: 22px 18px 16px; }}
      .header-actions {{ width: 100%; }}
      .header-actions form, .header-actions .button {{ flex: 1; }}
      .header-actions button, .header-actions .button {{ width: 100%; min-width: 0; }}
      .top-controls {{ align-items: stretch; }}
      .top-controls form {{ width: 100%; }}
      .top-controls label {{ flex: 1; }}
      .top-controls input, .top-controls select {{ width: 100%; min-width: 0; }}
      .row {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 520px) {{
      h1 {{ font-size: 24px; }}
      .header-actions {{ flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>免费听策略监控</h1>
      <p>上传参考图和竞品音乐截图，或通过 Android adb 自动采集，然后生成对比结论。</p>
    </div>
    <div class="header-actions">
      <form method="post" action="/generate" data-progress="生成报告">
        <input type="hidden" name="date" value="{html.escape(date)}" />
        <input type="hidden" name="app_key" value="{html.escape(app_key)}" />
        <button type="submit">生成/刷新对比结论</button>
      </form>
      <a class="button secondary" href="/report/{html.escape(app_key)}/{html.escape(date)}">纯文本报告</a>
    </div>
  </header>
  <main>
    {message_html}
    <div id="progress-panel" class="progress-panel" hidden>
      <div class="progress-head">
        <span id="progress-title">任务进行中</span>
        <span id="progress-percent">0%</span>
      </div>
      <div class="progress-track"><div id="progress-bar" class="progress-bar"></div></div>
      <p id="progress-message" class="progress-message">准备开始...</p>
    </div>
    <div class="top-controls">
      <form id="scope-form" method="get" action="/">
        <label>报告日期 <input id="date-picker" name="date" type="date" value="{html.escape(date)}" /></label>
        <label>采集 App <select id="app-picker" name="app_key">{app_options}</select></label>
      </form>
    </div>
    <div class="stack">
      <section>
        <h2>自动采集{html.escape(app_info['short'])}截图</h2>
        <p style="margin:0 0 10px;color:var(--muted);font-size:14px;">adb 状态：{html.escape(adb_status)}；请使用已连接并授权 USB 调试的安卓真机。</p>
        <form method="post" action="/install-adb" data-progress="安装/检测 adb">
          <input type="hidden" name="date" value="{html.escape(date)}" />
          <input type="hidden" name="app_key" value="{html.escape(app_key)}" />
          <button class="secondary" type="submit">安装/检测本地 adb</button>
        </form>
        <form method="post" action="/collect" data-progress="采集截图">
          <input type="hidden" name="date" value="{html.escape(date)}" />
          <input type="hidden" name="app_key" value="{html.escape(app_key)}" />
          <div class="row">
            <div>
              <label>包名</label>
              <input name="package" value="{html.escape(app_info['package'])}" />
            </div>
            <div>
              <label>截图数量</label>
              <input name="count" type="number" min="1" max="20" value="3" />
            </div>
          </div>
          <label>间隔秒数</label>
          <input name="interval" type="number" min="1" max="30" value="3" />
          <label>检测关键词</label>
          <input name="keywords" value="免费模式,免费听,会员歌,会员歌曲,看视频,看广告,畅听,VIP,广告" />
          <p class="hint">系统会先启动{html.escape(app_info['name'])}，自动尝试点击免费听、会员歌、VIP、看视频等入口；命中免费模式关键词后才保存截图。</p>
          <button type="submit">自动打开免费模式并截图</button>
          <button class="secondary" type="submit" formaction="/collect-all">自动采集汽水和 QQ</button>
        </form>
      </section>
      <section>
        <h2>视觉模型设置</h2>
        <p class="hint">视觉模型状态：{html.escape(api_status)}</p>
        <form method="post" action="/settings">
          <input type="hidden" name="date" value="{html.escape(date)}" />
          <input type="hidden" name="app_key" value="{html.escape(app_key)}" />
          <label>API Key</label>
          <input id="api-key-input" name="openai_api_key" type="password" autocomplete="off" placeholder="粘贴 key 后保存；同一浏览器会话内会保留" />
          <label>模型</label>
          <input name="openai_model" value="{html.escape(model_value)}" />
          <label>Base URL，可选</label>
          <input name="openai_base_url" value="{html.escape(base_url_value)}" placeholder="https://api.openai.com/v1" />
          <button class="secondary" type="submit">保存视觉模型设置</button>
        </form>
      </section>
    </div>
    <div class="stack">
      <div class="upload-grid">
        {reference_gallery}
        {competitor_gallery}
      </div>
      <section>
        <h2>报告预览</h2>
        <pre>{escaped_report}</pre>
      </section>
    </div>
  </main>
  <dialog id="previewDialog">
    <div class="preview-head">
      <strong id="previewTitle">图片预览</strong>
      <button type="button" id="closePreview">关闭</button>
    </div>
    <div class="preview-body"><img id="previewImage" alt="图片预览" /></div>
  </dialog>
  <script>
    document.querySelectorAll(".dropzone").forEach((zone) => {{
      const input = zone.querySelector(".file-input");
      zone.addEventListener("click", () => input.click());
      zone.addEventListener("dragover", (event) => {{
        event.preventDefault();
        zone.classList.add("dragging");
      }});
      zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
      zone.addEventListener("drop", (event) => {{
        event.preventDefault();
        zone.classList.remove("dragging");
        input.files = event.dataTransfer.files;
        zone.submit();
      }});
      input.addEventListener("change", () => {{
        if (input.files.length) zone.submit();
      }});
    }});
    const dialog = document.getElementById("previewDialog");
    const image = document.getElementById("previewImage");
    const title = document.getElementById("previewTitle");
    document.querySelectorAll("[data-preview]").forEach((button) => {{
      button.addEventListener("click", () => {{
        image.src = button.dataset.preview;
        title.textContent = button.dataset.name || "图片预览";
        dialog.showModal();
      }});
    }});
    document.getElementById("closePreview").addEventListener("click", () => dialog.close());
    document.querySelectorAll("#scope-form input, #scope-form select").forEach((control) => {{
      control.addEventListener("change", () => control.form.submit());
    }});
    const apiKeyInput = document.getElementById("api-key-input");
    const apiKeyStorageKey = "strategy-monitor-api-key";
    if (apiKeyInput) {{
      const savedApiKey = sessionStorage.getItem(apiKeyStorageKey);
      if (savedApiKey && !apiKeyInput.value) apiKeyInput.value = savedApiKey;
      apiKeyInput.addEventListener("input", () => {{
        if (apiKeyInput.value) {{
          sessionStorage.setItem(apiKeyStorageKey, apiKeyInput.value);
        }} else {{
          sessionStorage.removeItem(apiKeyStorageKey);
        }}
      }});
      apiKeyInput.form?.addEventListener("submit", () => {{
        if (apiKeyInput.value) sessionStorage.setItem(apiKeyStorageKey, apiKeyInput.value);
      }});
    }}
    const progressPanel = document.getElementById("progress-panel");
    const progressTitle = document.getElementById("progress-title");
    const progressPercent = document.getElementById("progress-percent");
    const progressBar = document.getElementById("progress-bar");
    const progressMessage = document.getElementById("progress-message");

    function renderProgress(task) {{
      const progress = Math.max(0, Math.min(100, Number(task.progress || 0)));
      progressPanel.hidden = false;
      progressTitle.textContent = task.label || "任务进行中";
      progressPercent.textContent = `${{progress}}%`;
      progressBar.style.width = `${{progress}}%`;
      progressMessage.textContent = task.message || "处理中...";
    }}

    async function pollTask(taskId) {{
      const response = await fetch(`/tasks/${{taskId}}`);
      const task = await response.json();
      renderProgress(task);
      if (task.status === "completed" || task.status === "failed") {{
        setTimeout(() => {{
          if (task.redirect_url) {{
            window.location.href = task.redirect_url;
          }}
        }}, task.status === "failed" ? 1200 : 500);
        return;
      }}
      setTimeout(() => pollTask(taskId), 900);
    }}

    document.querySelectorAll("form[data-progress]").forEach((form) => {{
      form.addEventListener("submit", async (event) => {{
        event.preventDefault();
        const submitter = event.submitter;
        const action = submitter?.getAttribute("formaction") || form.action;
        const formData = new FormData(form);
        renderProgress({{
          label: submitter?.textContent?.trim() || form.dataset.progress || "任务进行中",
          progress: 1,
          message: "已提交，正在排队..."
        }});
        form.querySelectorAll("button").forEach((button) => button.disabled = true);
        try {{
          const response = await fetch(action, {{ method: "POST", body: formData }});
          const payload = await response.json();
          if (payload.task_id) {{
            pollTask(payload.task_id);
          }} else {{
            throw new Error("未收到任务 ID");
          }}
        }} catch (error) {{
          renderProgress({{
            label: "任务提交失败",
            progress: 100,
            message: error instanceof Error ? error.message : "提交失败"
          }});
          form.querySelectorAll("button").forEach((button) => button.disabled = false);
        }}
      }});
    }});
  </script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def home(date: str | None = None, app_key: str | None = None, message: str = "") -> str:
    return render_page(safe_date(date), safe_app(app_key), message)


@app.get("/tasks/{task_id}")
def task_status(task_id: str) -> JSONResponse:
    with TASK_LOCK:
        task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return JSONResponse(task)


@app.post("/upload")
async def upload(
    date: str = Form(...),
    kind: str = Form(...),
    app_key: str = Form("qishui"),
    files: list[UploadFile] = File(...),
) -> RedirectResponse:
    report_date = safe_date(date)
    app_key = safe_app(app_key)
    upload_dir = target_dir(kind, report_date, app_key)
    saved = 0
    for uploaded in files:
        if not uploaded.filename:
            continue
        destination = unique_path(upload_dir, safe_name(uploaded.filename))
        destination.write_bytes(await uploaded.read())
        saved += 1
    return RedirectResponse(f"/?date={report_date}&app_key={app_key}&message=已上传 {saved} 个文件", status_code=303)


@app.post("/collect")
def collect(
    date: str = Form(...),
    app_key: str = Form("qishui"),
    package: str = Form("com.luna.music"),
    count: int = Form(3),
    interval: int = Form(3),
    keywords: str = Form(""),
) -> JSONResponse:
    report_date = safe_date(date)
    app_key = safe_app(app_key)
    command = build_collect_command(
        report_date=report_date,
        app_key=app_key,
        package=package.strip() or APP_CONFIG[app_key]["package"],
        count=count,
        interval=interval,
        keywords=keywords,
    )
    redirect_url = f"/?date={report_date}&app_key={app_key}"

    def worker(task_id: str) -> None:
        result = run_command_with_progress(task_id, command, 10, 92, f"正在启动{APP_CONFIG[app_key]['name']}并尝试打开免费模式...")
        if result.returncode == 0:
            complete_task(task_id, "采集完成，正在刷新页面...", f"{redirect_url}&message=采集完成")
        else:
            detail = (result.stderr or result.stdout).strip()[:180]
            complete_task(task_id, f"采集失败：{detail}", f"{redirect_url}&message={html.escape('采集失败：' + detail)}", ok=False)

    return start_task(f"采集{APP_CONFIG[app_key]['short']}截图", redirect_url, worker)


def build_collect_command(report_date: str, app_key: str, package: str, count: int, interval: int, keywords: str) -> list[str]:
    keyword_args = []
    for keyword in [item.strip() for item in keywords.split(",") if item.strip()]:
        keyword_args.extend(["--keyword", keyword])
    trigger_args = []
    for keyword in APP_CONFIG[app_key].get("trigger_keywords", []):
        trigger_args.extend(["--trigger-keyword", str(keyword)])
    command = [
        PYTHON,
        str(ROOT / "collect_qishui_adb.py"),
        "--date",
        report_date,
        "--package",
        package,
        "--count",
        str(max(1, min(count, 20))),
        "--interval",
        str(max(1, min(interval, 30))),
        "--attempts",
        str(max(8, min(count * 4, 24))),
        "--auto-open-free-mode",
        "--file-prefix",
        app_key,
        "--out-dir",
        str(APP_CONFIG[app_key]["dir"] / report_date),
        *keyword_args,
        *trigger_args,
    ]
    return command


@app.post("/collect-all")
def collect_all(
    date: str = Form(...),
    app_key: str = Form("qishui"),
    count: int = Form(3),
    interval: int = Form(3),
    keywords: str = Form(""),
) -> JSONResponse:
    report_date = safe_date(date)
    selected_app = safe_app(app_key)
    redirect_url = f"/?date={report_date}&app_key={selected_app}"

    def worker(task_id: str) -> None:
        messages = []
        total = len(APP_CONFIG)
        for index, (key, info) in enumerate(APP_CONFIG.items(), start=1):
            start = 5 + int((index - 1) / total * 86)
            end = 5 + int(index / total * 86)
            command = build_collect_command(
                report_date=report_date,
                app_key=key,
                package=str(info["package"]),
                count=count,
                interval=interval,
                keywords=keywords,
            )
            result = run_command_with_progress(task_id, command, start, end, f"正在采集{info['name']}免费模式截图...")
            if result.returncode == 0:
                messages.append(f"{info['short']}采集完成")
            else:
                detail = (result.stderr or result.stdout).strip()[:100]
                messages.append(f"{info['short']}采集失败：{detail}")
        message = "；".join(messages)
        ok = all("失败" not in item for item in messages)
        complete_task(task_id, message, f"{redirect_url}&message={html.escape(message)}", ok=ok)

    return start_task("自动采集汽水和 QQ", redirect_url, worker)


@app.post("/delete")
def delete_asset(
    date: str = Form(...),
    kind: str = Form(...),
    app_key: str = Form("qishui"),
    filename: str = Form(...),
) -> RedirectResponse:
    report_date = safe_date(date)
    app_key = safe_app(app_key)
    path = safe_existing_file(kind, report_date, filename, app_key)
    path.unlink()
    return RedirectResponse(f"/?date={report_date}&app_key={app_key}&message=已删除 {html.escape(path.name)}", status_code=303)


@app.get("/asset/{kind}/{app_key}/{date}/{filename}")
def asset(kind: str, app_key: str, date: str, filename: str) -> FileResponse:
    report_date = safe_date(date)
    path = safe_existing_file(kind, report_date, filename, safe_app(app_key))
    return FileResponse(path)


@app.post("/install-adb")
def install_adb(date: str = Form(...), app_key: str = Form("qishui")) -> JSONResponse:
    report_date = safe_date(date)
    app_key = safe_app(app_key)
    command = [PYTHON, str(ROOT / "install_adb.py")]
    redirect_url = f"/?date={report_date}&app_key={app_key}"

    def worker(task_id: str) -> None:
        result = run_command_with_progress(task_id, command, 8, 92, "正在安装/检测 adb...")
        output = (result.stdout or result.stderr).strip()
        message = "adb 已安装/检测完成" if result.returncode == 0 else f"adb 安装失败：{output[:160]}"
        complete_task(task_id, message, f"{redirect_url}&message={html.escape(message)}", ok=result.returncode == 0)

    return start_task("安装/检测 adb", redirect_url, worker)


@app.post("/settings")
def settings(
    date: str = Form(...),
    app_key: str = Form("qishui"),
    openai_api_key: str = Form(""),
    openai_model: str = Form("gpt-4.1-mini"),
    openai_base_url: str = Form(""),
) -> RedirectResponse:
    report_date = safe_date(date)
    app_key = safe_app(app_key)
    current = load_settings()
    if openai_api_key.strip():
        current["OPENAI_API_KEY"] = openai_api_key.strip()
    if openai_model.strip():
        current["OPENAI_MODEL"] = openai_model.strip()
    if openai_base_url.strip():
        current["OPENAI_BASE_URL"] = openai_base_url.strip()
    elif "OPENAI_BASE_URL" in current:
        current.pop("OPENAI_BASE_URL")
    save_settings(current)
    return RedirectResponse(f"/?date={report_date}&app_key={app_key}&message=视觉模型设置已保存", status_code=303)


@app.post("/install-emulator")
def install_emulator(date: str = Form(...)) -> JSONResponse:
    report_date = safe_date(date)
    command = [PYTHON, str(ROOT / "install_android_emulator.py")]
    redirect_url = f"/?date={report_date}"

    def worker(task_id: str) -> None:
        result = run_command_with_progress(task_id, command, 8, 92, "正在安装/检测安卓模拟器...")
        output = (result.stdout or result.stderr).strip()
        message = "安卓模拟器已安装/检测完成" if result.returncode == 0 else f"安卓模拟器安装失败：{output[-180:]}"
        complete_task(task_id, message, f"{redirect_url}&message={html.escape(message)}", ok=result.returncode == 0)

    return start_task("安装/检测安卓模拟器", redirect_url, worker)


@app.post("/launch-emulator")
def launch_emulator(date: str = Form(...)) -> JSONResponse:
    report_date = safe_date(date)
    command = [PYTHON, str(ROOT / "launch_android_emulator.py")]
    redirect_url = f"/?date={report_date}"

    def worker(task_id: str) -> None:
        result = run_command_with_progress(task_id, command, 8, 92, "正在启动安卓模拟器...")
        output = (result.stdout or result.stderr).strip()
        message = "模拟器正在启动，首次启动可能需要 1-3 分钟" if result.returncode == 0 else f"模拟器启动失败：{output[-180:]}"
        complete_task(task_id, message, f"{redirect_url}&message={html.escape(message)}", ok=result.returncode == 0)

    return start_task("启动安卓模拟器", redirect_url, worker)


@app.post("/generate")
def generate(date: str = Form(...), app_key: str = Form("qishui")) -> JSONResponse:
    report_date = safe_date(date)
    app_key = safe_app(app_key)
    command = [PYTHON, str(ROOT / "monitor.py"), "--date", report_date, "--app", app_key]
    redirect_url = f"/?date={report_date}&app_key={app_key}"

    def worker(task_id: str) -> None:
        result = run_command_with_progress(
            task_id,
            command,
            10,
            94,
            f"正在生成{APP_CONFIG[app_key]['name']}对比报告...",
            env=report_env(),
        )
        message = "报告已生成" if result.returncode == 0 else f"报告生成失败：{(result.stderr or result.stdout).strip()[:160]}"
        complete_task(task_id, message, f"{redirect_url}&message={html.escape(message)}", ok=result.returncode == 0)

    return start_task("生成/刷新对比结论", redirect_url, worker)


@app.get("/report/{app_key}/{date}", response_class=PlainTextResponse)
def get_report(app_key: str, date: str) -> str:
    report_date = safe_date(date)
    text = report_text(report_date, safe_app(app_key))
    return text or "还没有生成报告。"
