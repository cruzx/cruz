#!/usr/bin/env python3
"""Local web UI for the music app screenshot collection tool."""

from __future__ import annotations

import html
import json
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from . import screenshot_tool as tool


app = FastAPI(title="音乐 APP 截图收集工具")


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def parse_json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def selected(value: str, current: str) -> str:
    return "selected" if value == current else ""


def platform_select(name: str, current: str = "") -> str:
    options = []
    for item in tool.platform_options():
        platform = str(item.get("platform", ""))
        label = f"{item.get('app_name', platform)} ({platform})"
        options.append(f'<option value="{esc(platform)}" {selected(platform, current)}>{esc(label)}</option>')
    return f'<select name="{esc(name)}">{"".join(options)}</select>'


def screen_select(platform: str, current: str = "") -> str:
    screens = [str(screen["name"]) for screen in tool.screen_options(platform)] or ["首页推荐"]
    options = [f'<option value="{esc(screen)}" {selected(screen, current)}>{esc(screen)}</option>' for screen in screens]
    return f'<select name="screen_name">{"".join(options)}</select>'


def option_select(name: str, values: list[str], current: str = "") -> str:
    options = [f'<option value="{esc(value)}" {selected(value, current)}>{esc(value)}</option>' for value in values]
    return f'<select name="{esc(name)}">{"".join(options)}</select>'


def filter_options(column: str, current: str) -> str:
    values = tool.distinct_values(column)
    options = [f'<option value="">全部</option>']
    options.extend(f'<option value="{esc(value)}" {selected(value, current)}>{esc(value)}</option>' for value in values)
    return "".join(options)


def screenshot_card(row) -> str:
    modules = " / ".join(parse_json_list(row["ui_modules"]))
    tags = " / ".join(parse_json_list(row["feature_tags"]))
    return f"""
    <article class="shot-card">
      <a class="shot-thumb" href="/detail/{esc(row['id'])}">
        <img src="/image/{esc(row['id'])}" alt="{esc(row['app_name'])} {esc(row['screen_name'])}" />
      </a>
      <div class="shot-body">
        <div class="shot-title">{esc(row['app_name'])} · {esc(row['screen_name'])}</div>
        <div class="shot-meta">{esc(row['device_type'])} · {esc(row['capture_state'])}</div>
        <div class="chip-row">
          <span>{esc(row['change_type'])}</span>
          <span>{esc(tags or '待分类')}</span>
        </div>
        <p>{esc(modules or row['visual_notes'])}</p>
        <div class="shot-actions">
          <a class="button secondary" href="/detail/{esc(row['id'])}">查看</a>
          <form method="post" action="/delete/{esc(row['id'])}">
            <button class="danger" type="submit">删除</button>
          </form>
        </div>
      </div>
    </article>
    """


def render_runs() -> str:
    rows = tool.recent_runs()
    if not rows:
        return '<div class="empty">还没有采集记录。</div>'
    items = []
    for row in rows:
        status_class = "ok" if row["status"] == "ok" else "fail"
        link = f'<a href="/detail/{esc(row["screenshot_id"])}">查看截图</a>' if row["screenshot_id"] else ""
        items.append(
            f"""
            <li>
              <span class="{status_class}">{esc(row['status'])}</span>
              <strong>{esc(row['platform'])} · {esc(row['screen_name'])}</strong>
              <em>{esc(row['device_type'])}</em>
              <small>{esc(row['message'])} {link}</small>
            </li>
            """
        )
    return f'<ul class="run-list">{"".join(items)}</ul>'


def render_page(
    *,
    platform: str = "",
    screen_name: str = "",
    device_type: str = "",
    capture_state: str = "",
    message: str = "",
) -> str:
    tool.ensure_library()
    rows = tool.list_screenshots(
        {
            "platform": platform,
            "screen_name": screen_name,
            "device_type": device_type,
            "capture_state": capture_state,
        }
    )
    default_platform = platform or str(tool.platform_options()[0].get("platform", "qishui"))
    default_screen = screen_name or tool.first_screen(default_platform)
    config_json = json.dumps(tool.load_config(), ensure_ascii=False, indent=2)
    flow_example = json.dumps(
        [
            {"action": "sleep", "seconds": 2},
            {"action": "screenshot", "screen_name": "首页推荐"},
            {"action": "tap_text", "text": "搜索"},
            {"action": "wait_text", "text": "搜索", "timeout": 8},
            {"action": "text", "value": "周杰伦"},
            {"action": "keyevent", "code": "KEYCODE_ENTER"},
            {"action": "sleep", "seconds": 2},
            {"action": "screenshot", "screen_name": "搜索结果"},
        ],
        ensure_ascii=False,
        indent=2,
    )
    cards = "".join(screenshot_card(row) for row in rows) or '<div class="empty">还没有截图。先上传一张，或者连接 Android 设备后点击采集。</div>'
    notice = f'<div class="notice">{esc(message)}</div>' if message else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>音乐 APP 截图收集工具</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --panel: #ffffff;
      --ink: #121826;
      --muted: #667085;
      --line: #d9e2ee;
      --brand: #1267ff;
      --brand-dark: #0d4fc4;
      --ok: #067647;
      --bad: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      padding: 26px clamp(18px, 4vw, 36px);
      background: #101828;
      color: white;
    }}
    h1 {{ margin: 0 0 6px; font-size: 28px; letter-spacing: 0; }}
    header p {{ margin: 0; color: #cbd5e1; max-width: 760px; line-height: 1.55; }}
    main {{
      display: grid;
      grid-template-columns: minmax(300px, 390px) minmax(0, 1fr);
      gap: 18px;
      padding: 22px clamp(18px, 4vw, 36px) 40px;
    }}
    aside, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 12px 32px rgba(16, 24, 40, 0.06);
    }}
    aside {{ display: grid; gap: 14px; background: transparent; border: 0; box-shadow: none; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }}
    .content {{ padding: 16px; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    h3 {{ margin: 0 0 10px; font-size: 15px; color: #344054; }}
    label {{ display: block; margin: 10px 0 5px; color: var(--muted); font-size: 13px; }}
    input, select, textarea {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 9px 10px;
      font: inherit;
      background: white;
    }}
    textarea {{ min-height: 240px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }}
    button, .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 38px;
      border: 0;
      border-radius: 8px;
      padding: 0 13px;
      margin-top: 12px;
      background: var(--brand);
      color: white;
      font-weight: 700;
      text-decoration: none;
      cursor: pointer;
    }}
    button:hover, .button:hover {{ background: var(--brand-dark); }}
    .secondary {{ background: #eef2f6; color: #1d2939; }}
    .secondary:hover {{ background: #e4e7ec; }}
    .danger {{ background: #fff1f0; color: var(--bad); margin: 0; width: 100%; }}
    .danger:hover {{ background: #ffe4e0; }}
    .notice {{
      grid-column: 1 / -1;
      padding: 12px 14px;
      border: 1px solid #b9e6fe;
      border-radius: 8px;
      background: #f0f9ff;
      color: #075985;
    }}
    .filters {{
      display: grid;
      grid-template-columns: repeat(5, minmax(120px, 1fr));
      gap: 10px;
      align-items: end;
      padding: 16px;
      border-bottom: 1px solid var(--line);
    }}
    .gallery {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 14px;
    }}
    .shot-card {{
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: white;
    }}
    .shot-thumb {{
      display: block;
      height: 240px;
      background: #eef2f6;
    }}
    .shot-thumb img {{
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: block;
    }}
    .shot-body {{ display: grid; gap: 8px; padding: 12px; }}
    .shot-title {{ font-weight: 800; }}
    .shot-meta, .shot-body p {{ color: var(--muted); font-size: 13px; margin: 0; line-height: 1.45; }}
    .chip-row {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .chip-row span {{
      display: inline-flex;
      min-height: 24px;
      align-items: center;
      border-radius: 999px;
      padding: 0 9px;
      background: #f2f4f7;
      color: #344054;
      font-size: 12px;
    }}
    .shot-actions {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; align-items: center; }}
    .shot-actions .button {{ margin: 0; }}
    .shot-actions form {{ margin: 0; }}
    .empty {{ color: var(--muted); border: 1px dashed var(--line); border-radius: 8px; padding: 16px; background: #f8fafc; }}
    .run-list {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }}
    .run-list li {{ display: grid; gap: 3px; padding: 10px; border: 1px solid var(--line); border-radius: 8px; }}
    .run-list span {{ font-weight: 800; }}
    .run-list .ok {{ color: var(--ok); }}
    .run-list .fail {{ color: var(--bad); }}
    .run-list em, .run-list small {{ color: var(--muted); font-style: normal; }}
    .two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    @media (max-width: 980px) {{
      header {{ display: block; }}
      main {{ grid-template-columns: 1fr; padding: 18px; }}
      .filters {{ grid-template-columns: 1fr 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>音乐 APP 截图收集工具</h1>
      <p>把 Apple Music、Spotify、汽水音乐、网易云音乐、QQ 音乐、酷狗音乐的页面截图集中归档，支持上传补录、ADB/iOS 模拟器采集、去重、标签化、筛选和查看详情。</p>
    </div>
  </header>
  <main>
    {notice}
    <aside>
      <div class="panel">
        <h2>上传截图</h2>
        <form method="post" action="/upload" enctype="multipart/form-data">
          <label>平台</label>
          {platform_select("platform", default_platform)}
          <label>页面</label>
          <input name="screen_name" value="{esc(default_screen)}" />
          <div class="two">
            <div>
              <label>设备</label>
              {option_select("device_type", tool.load_config().get("device_types", []), "manual")}
            </div>
            <div>
              <label>状态</label>
              {option_select("capture_state", tool.load_config().get("capture_states", []), "人工补录")}
            </div>
          </div>
          <label>版本号</label>
          <input name="app_version" placeholder="例如 13.8.0" />
          <label>观察备注</label>
          <input name="notes" placeholder="例如：会员入口文案发生变化" />
          <label>图片</label>
          <input type="file" name="files" multiple accept=".png,.jpg,.jpeg,.webp" required />
          <button type="submit">上传并入库</button>
        </form>
      </div>

      <div class="panel">
        <h2>自动采集</h2>
        <form method="post" action="/capture">
          <label>平台</label>
          {platform_select("platform", default_platform)}
          <label>页面</label>
          <input name="screen_name" value="{esc(default_screen)}" />
          <div class="two">
            <div>
              <label>后端</label>
              <select name="backend">
                <option value="android">Android adb</option>
                <option value="ios_simulator">iOS Simulator</option>
              </select>
            </div>
            <div>
              <label>状态</label>
              {option_select("capture_state", tool.load_config().get("capture_states", []), "已登录普通用户")}
            </div>
          </div>
          <label>版本号</label>
          <input name="app_version" placeholder="可留空" />
          <label>备注</label>
          <input name="notes" placeholder="采集前请把目标页打开；Android 可自动启动 App" />
          <button type="submit">执行一次截图采集</button>
        </form>
        <form method="post" action="/auto-capture" style="margin-top:14px;border-top:1px solid var(--line);padding-top:14px">
          <h3>一键自动抓当前平台</h3>
          <label>平台</label>
          {platform_select("platform", default_platform)}
          <div class="two">
            <div>
              <label>状态</label>
              {option_select("capture_state", tool.load_config().get("capture_states", []), "已登录普通用户")}
            </div>
            <div>
              <label>版本号</label>
              <input name="app_version" placeholder="可留空" />
            </div>
          </div>
          <label>备注</label>
          <input name="notes" value="自动批量抓图" />
          <button type="submit">自动抓取所有配置页面</button>
        </form>
      </div>

      <div class="panel">
        <h2>流程抓图</h2>
        <form method="post" action="/flow-capture">
          <label>平台</label>
          {platform_select("platform", default_platform)}
          <div class="two">
            <div>
              <label>状态</label>
              {option_select("capture_state", tool.load_config().get("capture_states", []), "已登录普通用户")}
            </div>
            <div>
              <label>版本号</label>
              <input name="app_version" placeholder="可留空" />
            </div>
          </div>
          <label>流程步骤 JSON</label>
          <textarea name="flow_json">{esc(flow_example)}</textarea>
          <label>备注</label>
          <input name="notes" value="流程自动抓图" />
          <button type="submit">按流程自动抓图</button>
          <a class="button secondary" href="/device-ui" target="_blank" rel="noreferrer">读取当前页面元素</a>
        </form>
      </div>

      <div class="panel">
        <h2>最近采集记录</h2>
        {render_runs()}
      </div>

      <div class="panel">
        <h2>平台配置</h2>
        <form method="post" action="/config">
          <textarea name="config_json">{esc(config_json)}</textarea>
          <button type="submit">保存配置</button>
        </form>
      </div>
    </aside>

    <section>
      <form class="filters" method="get" action="/">
        <div>
          <label>平台</label>
          <select name="platform">{filter_options("platform", platform)}</select>
        </div>
        <div>
          <label>页面</label>
          <select name="screen_name">{filter_options("screen_name", screen_name)}</select>
        </div>
        <div>
          <label>设备</label>
          <select name="device_type">{filter_options("device_type", device_type)}</select>
        </div>
        <div>
          <label>状态</label>
          <select name="capture_state">{filter_options("capture_state", capture_state)}</select>
        </div>
        <button type="submit">筛选</button>
      </form>
      <div class="content">
        <h2>截图库</h2>
        <div class="gallery">{cards}</div>
      </div>
    </section>
  </main>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index(
    platform: str = "",
    screen_name: str = "",
    device_type: str = "",
    capture_state: str = "",
    message: str = "",
) -> str:
    return render_page(
        platform=platform,
        screen_name=screen_name,
        device_type=device_type,
        capture_state=capture_state,
        message=message,
    )


@app.post("/upload")
async def upload(
    platform: str = Form(...),
    screen_name: str = Form(...),
    device_type: str = Form("manual"),
    capture_state: str = Form("人工补录"),
    app_version: str = Form(""),
    notes: str = Form(""),
    files: list[UploadFile] = File(...),
):
    info = tool.find_platform(platform)
    meta = tool.ScreenshotInput(
        platform=platform,
        app_name=str(info.get("app_name", platform)),
        screen_name=screen_name.strip() or tool.first_screen(platform),
        device_type=device_type,
        capture_state=capture_state,
        app_version=app_version.strip(),
        source="manual_upload",
        notes=notes.strip(),
    )
    created = 0
    duplicates = 0
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        for upload_file in files:
            suffix = Path(upload_file.filename or "upload.png").suffix.lower()
            if suffix not in tool.IMAGE_SUFFIXES:
                continue
            source = temp / f"{tool.slugify(Path(upload_file.filename or 'upload').stem)}{suffix}"
            with source.open("wb") as handle:
                shutil.copyfileobj(upload_file.file, handle)
            _, is_new = tool.import_image(source, meta)
            if is_new:
                created += 1
            else:
                duplicates += 1
    return RedirectResponse(
        f"/?platform={esc(platform)}&message={esc(f'上传完成：新增 {created} 张，重复 {duplicates} 张。')}",
        status_code=303,
    )


@app.post("/capture")
def capture(
    platform: str = Form(...),
    screen_name: str = Form(...),
    backend: str = Form("android"),
    capture_state: str = Form("已登录普通用户"),
    app_version: str = Form(""),
    notes: str = Form(""),
):
    info = tool.find_platform(platform)
    meta = tool.ScreenshotInput(
        platform=platform,
        app_name=str(info.get("app_name", platform)),
        screen_name=screen_name.strip() or tool.first_screen(platform),
        device_type=backend,
        capture_state=capture_state,
        app_version=app_version.strip(),
        source=f"capture_{backend}",
        notes=notes.strip(),
    )
    try:
        screen = tool.find_screen(platform, meta.screen_name)
        if backend == "android":
            screenshot_id, is_new = tool.capture_android(
                meta,
                package_name=str(info.get("android_package", "")),
                steps=screen.get("steps", []),
            )
        elif backend == "ios_simulator":
            screenshot_id, is_new = tool.capture_ios_simulator(meta)
        else:
            raise ValueError("未知采集后端。")
        message = "新增截图" if is_new else "截图重复，已沿用已有记录"
        tool.record_run(platform, meta.screen_name, backend, "ok", message, screenshot_id)
        return RedirectResponse(f"/detail/{screenshot_id}?message={esc(message)}", status_code=303)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {str(exc)[:300]}"
        tool.record_run(platform, meta.screen_name, backend, "failed", detail)
        return RedirectResponse(f"/?platform={esc(platform)}&message={esc('采集失败：' + detail)}", status_code=303)


@app.post("/auto-capture")
def auto_capture(
    platform: str = Form(...),
    capture_state: str = Form("已登录普通用户"),
    app_version: str = Form(""),
    notes: str = Form("自动批量抓图"),
):
    results = tool.auto_capture_android(
        platform,
        capture_state=capture_state,
        app_version=app_version.strip(),
        notes=notes.strip(),
    )
    ok_count = sum(1 for item in results if item.get("ok"))
    fail_count = len(results) - ok_count
    detail = "；".join(f"{item['screen_name']}:{item['message']}" for item in results[:4])
    message = f"自动抓取完成：成功 {ok_count} 个，失败 {fail_count} 个。{detail}"
    return RedirectResponse(f"/?platform={esc(platform)}&message={esc(message)}", status_code=303)


@app.post("/flow-capture")
def flow_capture(
    platform: str = Form(...),
    capture_state: str = Form("已登录普通用户"),
    app_version: str = Form(""),
    flow_json: str = Form(...),
    notes: str = Form("流程自动抓图"),
):
    try:
        steps = json.loads(flow_json)
        if not isinstance(steps, list):
            raise ValueError("流程 JSON 必须是数组。")
        results = tool.run_android_flow(
            platform,
            steps,
            capture_state=capture_state,
            app_version=app_version.strip(),
            notes=notes.strip(),
        )
        detail = "；".join(f"{item['screen_name']}:{item['message']}" for item in results[:5])
        message = f"流程抓图完成：产出 {len(results)} 张。{detail}"
    except Exception as exc:
        message = f"流程抓图失败：{type(exc).__name__}: {str(exc)[:300]}"
    return RedirectResponse(f"/?platform={esc(platform)}&message={esc(message)}", status_code=303)


@app.get("/device-ui", response_class=HTMLResponse)
def device_ui() -> str:
    try:
        nodes = tool.android_nodes()
        rows = "".join(
            f"""
            <tr>
              <td>{esc(node.get('text'))}</td>
              <td>{esc(node.get('content_desc'))}</td>
              <td>{esc(node.get('resource_id'))}</td>
              <td>{esc(node.get('clickable'))}</td>
              <td>{esc(node.get('bounds'))}</td>
            </tr>
            """
            for node in nodes
        )
        body = rows or '<tr><td colspan="5">当前页面没有读到可用元素。</td></tr>'
    except Exception as exc:
        body = f'<tr><td colspan="5">读取失败：{esc(type(exc).__name__)}: {esc(str(exc))}</td></tr>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>当前 Android 页面元素</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f7fb; color: #121826; }}
    header {{ padding: 18px 24px; background: #101828; color: white; }}
    h1 {{ margin: 0; font-size: 22px; }}
    main {{ padding: 20px 24px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #d9e2ee; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #d9e2ee; text-align: left; vertical-align: top; font-size: 13px; }}
    th {{ background: #f2f4f7; color: #344054; }}
    td {{ word-break: break-word; }}
  </style>
</head>
<body>
  <header><h1>当前 Android 页面元素</h1></header>
  <main>
    <table>
      <thead><tr><th>text</th><th>content-desc</th><th>resource-id</th><th>clickable</th><th>bounds</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
  </main>
</body>
</html>"""


@app.get("/image/{screenshot_id}")
def image(screenshot_id: str):
    row = tool.get_screenshot(screenshot_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Screenshot not found.")
    path = Path(row["image_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file missing.")
    return FileResponse(path)


@app.get("/detail/{screenshot_id}", response_class=HTMLResponse)
def detail(screenshot_id: str, message: str = Query("")) -> str:
    row = tool.get_screenshot(screenshot_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Screenshot not found.")
    tags = parse_json_list(row["feature_tags"])
    modules = parse_json_list(row["ui_modules"])
    notice = f'<div class="notice">{esc(message)}</div>' if message else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(row['app_name'])} · {esc(row['screen_name'])}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f7fb; color: #121826; }}
    header {{ padding: 20px clamp(18px, 4vw, 36px); background: #101828; color: white; }}
    h1 {{ margin: 0; font-size: 24px; }}
    main {{ display: grid; grid-template-columns: minmax(280px, 420px) 1fr; gap: 18px; padding: 22px clamp(18px, 4vw, 36px); }}
    section {{ background: white; border: 1px solid #d9e2ee; border-radius: 8px; padding: 16px; }}
    img {{ width: 100%; max-height: 82vh; object-fit: contain; background: #eef2f6; border-radius: 8px; }}
    dl {{ display: grid; grid-template-columns: 110px 1fr; gap: 10px; }}
    dt {{ color: #667085; }}
    dd {{ margin: 0; word-break: break-word; }}
    .button {{ display: inline-flex; align-items: center; justify-content: center; min-height: 38px; border-radius: 8px; padding: 0 13px; background: #1267ff; color: white; font-weight: 700; text-decoration: none; }}
    .notice {{ margin: 0 0 12px; padding: 12px 14px; border: 1px solid #b9e6fe; border-radius: 8px; background: #f0f9ff; color: #075985; }}
    @media (max-width: 900px) {{ main {{ grid-template-columns: 1fr; padding: 18px; }} }}
  </style>
</head>
<body>
  <header><h1>{esc(row['app_name'])} · {esc(row['screen_name'])}</h1></header>
  <main>
    <section>
      {notice}
      <a class="button" href="/">返回截图库</a>
      <dl>
        <dt>平台</dt><dd>{esc(row['platform'])}</dd>
        <dt>设备</dt><dd>{esc(row['device_type'])}</dd>
        <dt>状态</dt><dd>{esc(row['capture_state'])}</dd>
        <dt>版本</dt><dd>{esc(row['app_version'] or '未填写')}</dd>
        <dt>变化</dt><dd>{esc(row['change_type'])}</dd>
        <dt>模块</dt><dd>{esc(' / '.join(modules))}</dd>
        <dt>标签</dt><dd>{esc(' / '.join(tags))}</dd>
        <dt>备注</dt><dd>{esc(row['visual_notes'])}</dd>
        <dt>采集时间</dt><dd>{esc(row['captured_at'])}</dd>
        <dt>指纹</dt><dd>{esc(row['perceptual_hash'])}</dd>
      </dl>
    </section>
    <section><img src="/image/{esc(row['id'])}" alt="{esc(row['file_name'])}" /></section>
  </main>
</body>
</html>"""


@app.post("/delete/{screenshot_id}")
def delete(screenshot_id: str):
    ok = tool.delete_screenshot(screenshot_id)
    message = "已删除截图。" if ok else "截图不存在。"
    return RedirectResponse(f"/?message={esc(message)}", status_code=303)


@app.post("/config")
def save_config(config_json: str = Form(...)):
    try:
        tool.save_config(config_json)
        message = "平台配置已保存。"
    except Exception as exc:
        message = f"配置保存失败：{type(exc).__name__}: {str(exc)[:200]}"
    return RedirectResponse(f"/?message={esc(message)}", status_code=303)


@app.get("/api/screenshots")
def api_screenshots():
    return [dict(row) for row in tool.list_screenshots(limit=1000)]
