"""
server.py · FastAPI 本地服务
提供：API 接口 + 静态文件 + 看板 HTML
"""
import os
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
import uvicorn

from storage import db, image_store
from storage import config_store
from processors.collector import run_collection
from processors.intel_collector import run_intel_collection
from processors.summary import generate_overall_summary

DATA_DIR: Path = None
COLLECT_INTERVAL_HOURS: int = 24
_collection_task = None
_collect_lock = asyncio.Lock()
_collect_status = {
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_saved": 0,
    "last_error": None,
}
_intel_status = {
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_saved": 0,
    "last_error": None,
}
_summary_status = {
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_error": None,
}
_platform_login_status = {
    "dribbble": {"running": False, "logged_in": False, "last_error": None},
    "behance": {"running": False, "logged_in": False, "last_error": None},
    "pinterest": {"running": False, "logged_in": False, "last_error": None},
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化
    await db.init_db(DATA_DIR)
    image_store.init_image_store(DATA_DIR)
    # 启动后台定时采集
    global _collection_task
    _collection_task = asyncio.create_task(_scheduler())
    yield
    if _collection_task:
        _collection_task.cancel()


app = FastAPI(title="音乐情报雷达", lifespan=lifespan)


# ── 静态文件 ──────────────────────────────────────────
def setup_static(data_dir: Path):
    # 挂载 data/images 目录，供看板直接访问图片
    app.mount("/images", StaticFiles(directory=str(data_dir / "images")), name="images")


# ── API 路由 ──────────────────────────────────────────

@app.get("/api/images")
async def api_images(
    source: str = Query("all"),
    reference: str = Query("all"),
    limit: int = Query(100, le=300),
    offset: int = Query(0),
):
    items = await db.query_images(source=source, reference=reference, limit=limit, offset=offset)
    # 把本地路径转成 HTTP URL
    for item in items:
        from storage.image_store import path_to_url; item["url"] = path_to_url(item["local_path"])
    return {"items": items, "count": len(items)}


@app.get("/api/stats")
async def api_stats():
    stats = await db.get_stats()
    return stats


@app.get("/api/config")
async def api_get_config():
    return config_store.public_config()


@app.post("/api/config")
async def api_save_config(request: Request):
    payload = await request.json()
    config_store.save_config(payload)
    image_store.init_image_store(DATA_DIR)
    return {"status": "saved", "config": config_store.public_config()}


@app.post("/api/platform-login/{platform}")
async def api_platform_login(platform: str):
    if platform not in _platform_login_status:
        return JSONResponse({"error": "unsupported platform"}, status_code=404)
    if _platform_login_status[platform]["running"]:
        return {"status": "running", "message": f"{platform} 登录窗口已打开"}
    asyncio.create_task(_run_platform_login(platform))
    return {"status": "started", "message": f"已打开 {platform} 登录窗口"}


@app.get("/api/platform-login/{platform}")
async def api_platform_login_status(platform: str):
    if platform not in _platform_login_status:
        return JSONResponse({"error": "unsupported platform"}, status_code=404)
    from collectors.browser_login import has_profile
    _platform_login_status[platform]["logged_in"] = has_profile(DATA_DIR, platform)
    return _platform_login_status[platform]


@app.post("/api/collect")
async def api_collect(no_ai: bool = Query(False)):
    """手动触发一次采集"""
    if _collect_status["running"]:
        return {"status": "running", "message": "采集正在进行中"}
    asyncio.create_task(_run_collection_job(use_ai=False))
    return {"status": "started", "message": "采集已在后台启动，稍后刷新页面查看结果"}


@app.post("/api/collect-intel")
async def api_collect_intel(no_ai: bool = Query(False)):
    if _intel_status["running"]:
        return {"status": "running", "message": "产品动向采集正在进行中"}
    asyncio.create_task(_run_intel_job(use_ai=False))
    return {"status": "started", "message": "产品动向采集已启动"}


@app.post("/api/summary")
async def api_generate_summary():
    if _summary_status["running"]:
        return {"status": "running", "message": "总体总结正在生成中"}
    asyncio.create_task(_run_summary_job())
    return {"status": "started", "message": "总体总结生成已启动"}


@app.get("/api/summary")
async def api_latest_summary():
    report = await db.latest_report("overall")
    return {"report": report}


@app.get("/api/intel")
async def api_intel(limit: int = Query(80, le=200), offset: int = Query(0)):
    items = await db.query_features(limit=limit, offset=offset)
    return {"items": items, "count": len(items)}


@app.get("/api/status")
async def api_status():
    stats = await db.get_stats()
    return {
        "status": "collecting" if _collect_status["running"] else "idle",
        "collection": _collect_status,
        "intel": _intel_status,
        "summary": _summary_status,
        "total_images": stats["total"],
        "total_intel": stats.get("feature_total", 0),
        "by_source": stats["by_source"],
        "server_time": datetime.now().isoformat(),
    }


# ── 看板 HTML ─────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML


@app.get("/settings", response_class=HTMLResponse)
async def settings_page():
    return SETTINGS_HTML


@app.get("/intel", response_class=HTMLResponse)
async def intel_page():
    return INTEL_HTML


# ── 定时采集 ─────────────────────────────────────────

async def _scheduler():
    interval = COLLECT_INTERVAL_HOURS * 3600
    while True:
        await asyncio.sleep(interval)
        try:
            await _run_collection_job(use_ai=False)
        except Exception as e:
            print(f"[Scheduler] 采集失败: {e}")


async def _run_collection_job(use_ai: bool = True):
    if _collect_lock.locked():
        return 0
    async with _collect_lock:
        _collect_status.update({
            "running": True,
            "last_started_at": datetime.now().isoformat(),
            "last_finished_at": None,
            "last_saved": 0,
            "last_error": None,
        })
        try:
            saved = await run_collection(DATA_DIR, use_ai=use_ai)
            _collect_status["last_saved"] = saved
            return saved
        except Exception as e:
            _collect_status["last_error"] = str(e)
            raise
        finally:
            _collect_status["running"] = False
            _collect_status["last_finished_at"] = datetime.now().isoformat()


async def _run_intel_job(use_ai: bool = True):
    if _intel_status["running"]:
        return 0
    _intel_status.update({
        "running": True,
        "last_started_at": datetime.now().isoformat(),
        "last_finished_at": None,
        "last_saved": 0,
        "last_error": None,
    })
    try:
        saved = await run_intel_collection(use_ai=use_ai)
        _intel_status["last_saved"] = saved
        return saved
    except Exception as e:
        _intel_status["last_error"] = str(e)
        raise
    finally:
            _intel_status["running"] = False
            _intel_status["last_finished_at"] = datetime.now().isoformat()


async def _run_summary_job():
    _summary_status.update({
        "running": True,
        "last_started_at": datetime.now().isoformat(),
        "last_finished_at": None,
        "last_error": None,
    })
    try:
        await generate_overall_summary()
    except Exception as e:
        _summary_status["last_error"] = str(e)
    finally:
        _summary_status["running"] = False
        _summary_status["last_finished_at"] = datetime.now().isoformat()


async def _run_platform_login(platform: str):
    from collectors.browser_login import login_with_browser, has_profile
    login_urls = {
        "dribbble": "https://dribbble.com/session/new",
        "behance": "https://www.behance.net/login",
        "pinterest": "https://www.pinterest.com/login/",
    }
    state = _platform_login_status[platform]
    state.update({"running": True, "last_error": None, "logged_in": False})
    try:
        ok = await login_with_browser(DATA_DIR, platform, login_urls[platform])
        state["logged_in"] = bool(ok or has_profile(DATA_DIR, platform))
    except Exception as e:
        state["last_error"] = str(e)
    finally:
        state["running"] = False


# ── 启动入口 ─────────────────────────────────────────

def start_server(data_dir: Path, port: int = 8765, interval_hours: int = 24):
    global DATA_DIR, COLLECT_INTERVAL_HOURS
    DATA_DIR = data_dir
    COLLECT_INTERVAL_HOURS = interval_hours
    setup_static(data_dir)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


# ── 看板 HTML（内嵌，避免额外文件依赖）────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>音乐情报雷达</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&family=JetBrains+Mono:wght@400;600&display=swap');
:root{
  --bg:#0c0c10;--s1:#13131a;--s2:#1c1c26;--b:#2a2a3d;
  --t:#dddde8;--td:#8888a8;--tf:#4a4a68;
  --ac:#5b5ef4;--ac2:#f45b8e;--ac3:#5bf4c8;
  --font:'Noto Sans SC',sans-serif;
  --mono:'JetBrains Mono',monospace;
}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--t);font-family:var(--font);font-size:14px;min-height:100vh}
/* grid bg */
body::before{content:'';position:fixed;inset:0;
  background-image:linear-gradient(rgba(91,94,244,.04) 1px,transparent 1px),
  linear-gradient(90deg,rgba(91,94,244,.04) 1px,transparent 1px);
  background-size:48px 48px;pointer-events:none;z-index:0}

/* ─ header ─ */
header{
  position:sticky;top:0;z-index:100;
  background:rgba(12,12,16,.92);
  backdrop-filter:blur(12px);
  border-bottom:1px solid var(--b);
  padding:0 28px;
  display:flex;align-items:center;gap:16px;height:56px;
}
.logo{font-family:var(--mono);font-size:13px;font-weight:600;color:var(--ac);letter-spacing:.05em}
.logo span{color:var(--ac2)}
.stats-bar{display:flex;gap:20px;margin-left:auto}
.stat{font-family:var(--mono);font-size:11px;color:var(--td);display:flex;align-items:center;gap:5px}
.stat b{color:var(--t);font-size:13px}
.btn{
  font-family:var(--mono);font-size:11px;padding:6px 14px;
  background:transparent;border:1px solid var(--b);color:var(--td);
  cursor:pointer;border-radius:2px;letter-spacing:.05em;transition:all .15s;
}
.btn:hover{border-color:var(--ac);color:var(--ac);background:rgba(91,94,244,.08)}
.btn.primary{background:var(--ac);color:#fff;border-color:var(--ac)}
.btn.primary:hover{background:#7072f6}
.btn:disabled{opacity:.4;cursor:not-allowed}

/* ─ toolbar ─ */
.toolbar{
  padding:16px 28px;
  display:flex;gap:10px;align-items:center;flex-wrap:wrap;
  position:relative;z-index:1;
}
.filter-group{display:flex;gap:2px}
.chip{
  font-family:var(--mono);font-size:11px;padding:5px 12px;
  background:var(--s1);border:1px solid var(--b);color:var(--td);
  cursor:pointer;transition:all .15s;letter-spacing:.03em;
}
.chip:first-child{border-radius:2px 0 0 2px}
.chip:last-child{border-radius:0 2px 2px 0}
.chip.active{background:var(--ac);border-color:var(--ac);color:#fff}
.chip:not(:first-child){border-left:none}

.sep{width:1px;height:24px;background:var(--b);margin:0 4px}

/* ─ grid ─ */
#grid{
  padding:0 28px 40px;
  columns:5;column-gap:12px;
  position:relative;z-index:1;
}
@media(max-width:1400px){#grid{columns:4}}
@media(max-width:1000px){#grid{columns:3}}
@media(max-width:700px){#grid{columns:2}}

/* ─ card ─ */
.card{
  break-inside:avoid;
  margin-bottom:12px;
  background:var(--s1);border:1px solid var(--b);
  overflow:hidden;cursor:pointer;
  transition:transform .18s,border-color .18s,box-shadow .18s;
  animation:fadeIn .3s ease both;
}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.card:hover{transform:translateY(-3px);border-color:var(--ac);box-shadow:0 8px 32px rgba(91,94,244,.15)}
.card img{width:100%;display:block;background:var(--s2)}
.card-body{padding:10px 12px}
.card-source{
  font-family:var(--mono);font-size:9px;letter-spacing:.12em;
  text-transform:uppercase;padding:2px 6px;display:inline-block;
  margin-bottom:6px;border-radius:1px;
}
.src-dribbble{background:rgba(244,91,142,.15);color:#f45b8e;border:1px solid rgba(244,91,142,.25)}
.src-behance{background:rgba(91,94,244,.15);color:#7b80ff;border:1px solid rgba(91,94,244,.25)}
.card-title{font-size:12px;color:var(--t);line-height:1.4;margin-bottom:6px;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.card-tags{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px}
.tag{font-family:var(--mono);font-size:9px;padding:2px 6px;
  background:var(--s2);color:var(--td);border-radius:1px}
.card-meta{display:flex;align-items:center;justify-content:space-between}
.card-likes{font-family:var(--mono);font-size:10px;color:var(--tf)}
.ref-badge{font-family:var(--mono);font-size:9px;padding:2px 6px;border-radius:1px}
.ref-high{background:rgba(91,244,200,.15);color:var(--ac3);border:1px solid rgba(91,244,200,.25)}
.ref-mid{background:rgba(255,180,50,.1);color:#ffb432;border:1px solid rgba(255,180,50,.2)}
.ref-low{background:var(--s2);color:var(--tf);border:1px solid var(--b)}
.card-colors{display:flex;gap:3px;margin-top:6px}
.swatch{width:14px;height:14px;border-radius:2px;flex-shrink:0}

/* ─ empty ─ */
#empty{
  display:none;flex-direction:column;align-items:center;justify-content:center;
  padding:80px 20px;color:var(--td);text-align:center;
}
#empty .icon{font-size:48px;margin-bottom:16px;opacity:.4}
#empty p{font-size:14px;line-height:1.8}
#empty .hint{font-family:var(--mono);font-size:11px;color:var(--tf);margin-top:8px}

/* ─ toast ─ */
#toast{
  position:fixed;bottom:28px;left:50%;transform:translateX(-50%) translateY(20px);
  background:var(--ac);color:#fff;padding:10px 22px;
  font-family:var(--mono);font-size:12px;border-radius:2px;
  opacity:0;transition:all .25s;pointer-events:none;z-index:999;
}
#toast.show{opacity:1;transform:translateX(-50%) translateY(0)}

/* ─ modal ─ */
#modal{
  position:fixed;inset:0;z-index:200;
  background:rgba(0,0,0,.85);backdrop-filter:blur(4px);
  display:none;align-items:center;justify-content:center;
  padding:24px;
}
#modal.open{display:flex}
.modal-inner{
  background:var(--s1);border:1px solid var(--b);
  max-width:900px;width:100%;max-height:90vh;overflow-y:auto;
  display:grid;grid-template-columns:1fr 1fr;
}
@media(max-width:700px){.modal-inner{grid-template-columns:1fr}}
.modal-img{background:var(--s2)}
.modal-img img{width:100%;display:block;max-height:70vh;object-fit:contain}
.modal-info{padding:28px;overflow-y:auto}
.modal-close{
  position:absolute;top:20px;right:24px;
  background:none;border:none;color:var(--td);font-size:24px;
  cursor:pointer;z-index:1;
}
.modal-close:hover{color:var(--t)}
.m-label{font-family:var(--mono);font-size:10px;color:var(--tf);
  letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px;margin-top:16px}
.m-label:first-child{margin-top:0}
.m-val{font-size:13px;color:var(--t);line-height:1.7}
.m-tags{display:flex;flex-wrap:wrap;gap:4px}
.m-colors{display:flex;gap:6px;flex-wrap:wrap}
.m-swatch{
  width:28px;height:28px;border-radius:3px;
  border:1px solid rgba(255,255,255,.1);
  title:attr(data-color);
}
.m-link{color:var(--ac);font-family:var(--mono);font-size:11px;text-decoration:none}
.m-link:hover{text-decoration:underline}
.m-notes{
  background:var(--s2);border-left:3px solid var(--ac3);
  padding:10px 14px;font-size:13px;color:var(--t);
  line-height:1.7;margin-top:4px;
}
</style>
</head>
<body>

<header>
  <div class="logo">MUSIC<span>RADAR</span> ·</div>
  <div class="stats-bar">
    <div class="stat">总计 <b id="s-total">-</b> 张</div>
    <div class="stat">Dribbble <b id="s-drb">-</b></div>
    <div class="stat">Behance <b id="s-beh">-</b></div>
    <div class="stat">Pinterest <b id="s-pin">-</b></div>
    <div class="stat">动向 <b id="s-intel">-</b></div>
  </div>
  <button class="btn" onclick="location.href='/intel'">产品动向</button>
  <button class="btn" onclick="location.href='/settings'">配置</button>
  <button class="btn primary" id="collect-btn" onclick="triggerCollect()">▶ 立即采集</button>
</header>

<div class="toolbar">
  <div class="filter-group" id="source-filter">
    <div class="chip active" data-v="all">全部来源</div>
    <div class="chip" data-v="dribbble">Dribbble</div>
    <div class="chip" data-v="behance">Behance</div>
    <div class="chip" data-v="pinterest">Pinterest</div>
  </div>
  <div class="sep"></div>
  <div class="filter-group" id="ref-filter">
    <div class="chip active" data-v="all">全部价值</div>
    <div class="chip" data-v="high">高参考</div>
    <div class="chip" data-v="mid">中参考</div>
    <div class="chip" data-v="low">低参考</div>
  </div>
</div>

<div id="grid"></div>
<div id="empty">
  <div class="icon">📭</div>
  <p>还没有数据</p>
  <p class="hint">点击右上角「立即采集」开始获取内容</p>
</div>

<div id="toast"></div>

<div id="modal" onclick="if(event.target===this)closeModal()">
  <button class="modal-close" onclick="closeModal()">×</button>
  <div class="modal-inner">
    <div class="modal-img"><img id="m-img" src="" alt=""></div>
    <div class="modal-info" id="m-info"></div>
  </div>
</div>

<script>
let currentSource = 'all', currentRef = 'all';
let allItems = [];

// ─ 筛选器 ─
document.querySelectorAll('#source-filter .chip').forEach(el => {
  el.onclick = () => {
    document.querySelectorAll('#source-filter .chip').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
    currentSource = el.dataset.v;
    renderGrid();
  };
});
document.querySelectorAll('#ref-filter .chip').forEach(el => {
  el.onclick = () => {
    document.querySelectorAll('#ref-filter .chip').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
    currentRef = el.dataset.v;
    renderGrid();
  };
});

// ─ 加载数据 ─
async function loadData() {
  const params = new URLSearchParams({ source: currentSource, reference: currentRef, limit: 300 });
  const res = await fetch('/api/images?' + params);
  const data = await res.json();
  allItems = data.items || [];
  renderGrid();
}

async function loadStats() {
  const res = await fetch('/api/stats');
  const d = await res.json();
  document.getElementById('s-total').textContent = d.total || 0;
  document.getElementById('s-drb').textContent = (d.by_source || {}).dribbble || 0;
  document.getElementById('s-beh').textContent = (d.by_source || {}).behance || 0;
  document.getElementById('s-pin').textContent = (d.by_source || {}).pinterest || 0;
  document.getElementById('s-intel').textContent = d.feature_total || 0;
}

// ─ 渲染 ─
function renderGrid() {
  const grid = document.getElementById('grid');
  const empty = document.getElementById('empty');
  const items = allItems;

  if (!items.length) {
    grid.innerHTML = '';
    empty.style.display = 'flex';
    return;
  }
  empty.style.display = 'none';

  grid.innerHTML = items.map((item, i) => `
    <div class="card" style="animation-delay:${Math.min(i*0.03, 0.6)}s" onclick="openModal(${i})">
      <img src="${item.url}" loading="lazy" alt="${esc(item.title)}"
           onerror="this.style.display='none'">
      <div class="card-body">
        <span class="card-source src-${item.source}">${item.source}</span>
        <div class="card-title">${esc(item.title || '无标题')}</div>
        ${item.ai_style_tags?.length ? `
          <div class="card-tags">
            ${item.ai_style_tags.slice(0,3).map(t => `<span class="tag">${esc(t)}</span>`).join('')}
          </div>` : ''}
        <div class="card-meta">
          <span class="card-likes">♥ ${item.likes || 0}</span>
          ${item.ai_reference ? `<span class="ref-badge ref-${item.ai_reference}">${
            item.ai_reference==='high'?'高参考':item.ai_reference==='mid'?'中参考':'低参考'
          }</span>` : ''}
        </div>
        ${item.ai_color_palette?.length ? `
          <div class="card-colors">
            ${item.ai_color_palette.slice(0,5).map(c =>
              `<div class="swatch" style="background:${c}" title="${c}"></div>`
            ).join('')}
          </div>` : ''}
      </div>
    </div>
  `).join('');
}

// ─ 详情 Modal ─
function openModal(idx) {
  const item = allItems[idx];
  if (!item) return;
  document.getElementById('m-img').src = item.url;

  const info = document.getElementById('m-info');
  info.innerHTML = `
    <div class="m-label">来源</div>
    <div class="m-val"><span class="card-source src-${item.source}">${item.source}</span></div>

    <div class="m-label">标题</div>
    <div class="m-val">${esc(item.title || '—')}</div>

    ${item.author ? `<div class="m-label">作者</div><div class="m-val">${esc(item.author)}</div>` : ''}

    ${item.ai_layout ? `
      <div class="m-label">布局模式</div>
      <div class="m-val">${esc(item.ai_layout)}</div>` : ''}

    ${item.ai_style_tags?.length ? `
      <div class="m-label">设计风格</div>
      <div class="m-tags">${item.ai_style_tags.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>` : ''}

    ${item.ai_color_palette?.length ? `
      <div class="m-label">主色调</div>
      <div class="m-colors">
        ${item.ai_color_palette.map(c=>`
          <div class="m-swatch" style="background:${c}" title="${c}"></div>
        `).join('')}
      </div>` : ''}

    ${item.ai_key_elements?.length ? `
      <div class="m-label">值得参考的要素</div>
      <div class="m-tags">${item.ai_key_elements.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>` : ''}

    ${item.ai_notes ? `
      <div class="m-label">给酷狗概念版的建议</div>
      <div class="m-notes">${esc(item.ai_notes)}</div>` : ''}

    <div class="m-label">互动数据</div>
    <div class="m-val">♥ ${item.likes || 0} &nbsp; 👁 ${item.views || 0}</div>

    ${item.source_url ? `
      <div class="m-label">原始链接</div>
      <a class="m-link" href="${item.source_url}" target="_blank">→ 查看原作品</a>` : ''}

    <div class="m-label">采集时间</div>
    <div class="m-val" style="font-family:var(--mono);font-size:11px;color:var(--td)">${
      item.collected_at ? item.collected_at.replace('T',' ').slice(0,16) : '—'
    }</div>
  `;

  document.getElementById('modal').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  document.getElementById('modal').classList.remove('open');
  document.body.style.overflow = '';
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});

// ─ 采集触发 ─
async function triggerCollect() {
  const btn = document.getElementById('collect-btn');
  btn.disabled = true;
  btn.textContent = '⏳ 采集中...';
  showToast('采集已启动，完成后自动刷新');

  try {
    const before = await (await fetch('/api/stats')).json();
    const started = await (await fetch('/api/collect', { method: 'POST' })).json();
    if (started.status === 'running') showToast('已有采集任务在运行');

    const check = setInterval(async () => {
      const status = await (await fetch('/api/status')).json();
      if (status.status !== 'collecting') {
        clearInterval(check);
        btn.disabled = false;
        btn.textContent = '▶ 立即采集';
        const added = Math.max((status.total_images || 0) - (before.total || 0), 0);
        showToast(status.collection?.last_error ? '采集失败，请检查终端日志' : `✓ 新增 ${added} 张图片`);
        loadStats();
        loadData();
      }
    }, 3000);

    // 超时保护 5 分钟
    setTimeout(() => {
      clearInterval(check);
      btn.disabled = false;
      btn.textContent = '▶ 立即采集';
      loadStats();
      loadData();
    }, 300000);
  } catch(e) {
    btn.disabled = false;
    btn.textContent = '▶ 立即采集';
    showToast('启动失败，请检查终端日志');
  }
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ─ 初始化 ─
loadStats();
loadData();
setInterval(() => { loadStats(); }, 30000);
</script>
</body>
</html>
"""


INTEL_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>音乐情报雷达 · 产品动向</title>
<style>
:root{--bg:#0c0c10;--panel:#14141d;--panel2:#1b1b26;--b:#2d2d3d;--t:#eeeeF6;--muted:#9b9bb2;--faint:#63647a;--ac:#5b5ef4;--ok:#5bf4c8;--font:-apple-system,BlinkMacSystemFont,"Noto Sans SC","PingFang SC",sans-serif;--mono:"SFMono-Regular",Menlo,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t);font-family:var(--font);font-size:14px}
header{height:58px;border-bottom:1px solid var(--b);display:flex;align-items:center;gap:14px;padding:0 28px;position:sticky;top:0;background:rgba(12,12,16,.94);backdrop-filter:blur(12px);z-index:10}
.logo{font-family:var(--mono);font-size:13px;color:var(--ac);font-weight:700}.logo span{color:#f45b8e}.spacer{flex:1}
.btn{border:1px solid var(--b);background:transparent;color:var(--t);height:32px;padding:0 14px;border-radius:4px;cursor:pointer;font-family:var(--mono);font-size:12px}.btn:hover{border-color:var(--ac)}.btn.primary{background:var(--ac);border-color:var(--ac)}.btn.good{background:rgba(91,244,200,.14);border-color:rgba(91,244,200,.4);color:var(--ok)}
main{max-width:1200px;margin:0 auto;padding:28px}.panel{background:var(--panel);border:1px solid var(--b);border-radius:6px;padding:18px;margin-bottom:18px}.panel h2{font-size:15px;margin:0 0 14px}.hint{font-size:12px;color:var(--faint);line-height:1.7}
.source-row{display:flex;gap:8px;flex-wrap:wrap}.pill{font:11px var(--mono);padding:5px 9px;border-radius:999px;background:var(--panel2);border:1px solid var(--b);color:var(--muted)}
.feed-list{display:grid;gap:10px}.intel-card{background:var(--panel);border:1px solid var(--b);border-radius:6px;padding:14px}.intel-meta{font:11px var(--mono);color:var(--faint);margin-bottom:8px}.intel-title{font-size:15px;line-height:1.5;margin-bottom:8px}.intel-summary{color:var(--muted);line-height:1.7}.intel-impact{margin-top:10px;border-left:3px solid var(--ok);padding-left:10px;line-height:1.7}.intel-card a{color:#aaa8ff;text-decoration:none}.intel-card a:hover{text-decoration:underline}
#summary-box{line-height:1.75;color:var(--muted)}#summary-box h2,#summary-box h3{color:var(--t);margin:14px 0 8px}.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--ac);color:#fff;padding:10px 18px;border-radius:4px;font:12px var(--mono);display:none}.toast.show{display:block}
</style>
</head>
<body>
<header>
  <div class="logo">MUSIC<span>RADAR</span> · INTEL</div>
  <button class="btn" onclick="location.href='/'">图片墙</button>
  <button class="btn" onclick="location.href='/settings'">配置</button>
  <div class="spacer"></div>
  <button class="btn good" onclick="collectIntel()">采集产品动向</button>
  <button class="btn primary" onclick="generateSummary()">生成总体总结</button>
</header>
<main>
  <section class="panel">
    <h2>产品/科技动向源</h2>
    <div class="source-row" id="source-row"></div>
    <div class="hint" style="margin-top:12px">采集只入库，不逐条调用模型；点击「生成总体总结」时才会调用一次视觉模型。</div>
  </section>
  <section class="panel">
    <h2>总体总结</h2>
    <div class="hint" id="summary-box">还没有总结。</div>
  </section>
  <section><div class="feed-list" id="intel-list"></div></section>
</main>
<div class="toast" id="toast"></div>
<script>
async function loadSources(){
  const cfg = await (await fetch('/api/config')).json();
  const feeds = String(cfg.TECH_FEEDS || '').split(',').map(x=>x.trim()).filter(Boolean);
  document.getElementById('source-row').innerHTML = feeds.map(f => `<span class="pill">${esc(f.split('|')[0] || f)}</span>`).join('');
}
async function collectIntel(){
  await fetch('/api/collect-intel', {method:'POST'});
  toast('产品动向采集已启动');
  const timer = setInterval(async () => {
    const s = await (await fetch('/api/status')).json();
    if (!s.intel?.running) {
      clearInterval(timer);
      toast(`产品动向新增 ${s.intel?.last_saved || 0} 条`);
      loadIntel();
    }
  }, 3000);
}
async function generateSummary(){
  await fetch('/api/summary', {method:'POST'});
  toast('总体总结生成已启动');
  const timer = setInterval(async () => {
    const s = await (await fetch('/api/status')).json();
    if (!s.summary?.running) {
      clearInterval(timer);
      if (s.summary?.last_error) toast('总结生成失败，请检查 API 配置');
      else toast('总体总结已生成');
      loadSummary();
    }
  }, 3000);
}
async function loadSummary(){
  const data = await (await fetch('/api/summary')).json();
  const box = document.getElementById('summary-box');
  if (!data.report) { box.textContent = '还没有总结。'; return; }
  box.innerHTML = md(data.report.content || '');
}
async function loadIntel(){
  const data = await (await fetch('/api/intel?limit=120')).json();
  const list = document.getElementById('intel-list');
  if (!data.items?.length) {
    list.innerHTML = '<div class="panel"><div class="hint">还没有产品动向，点击右上角「采集产品动向」。</div></div>';
    return;
  }
  list.innerHTML = data.items.map(item => `
    <article class="intel-card">
      <div class="intel-meta">${esc(item.platform || '')} · ${esc(item.category || '未分析')} · ${esc((item.published_at || item.created_at || '').slice(0,16))}</div>
      <div class="intel-title"><a href="${escAttr(item.source_url || '#')}" target="_blank">${esc(item.title || '无标题')}</a></div>
      <div class="intel-summary">${esc(item.summary || '')}</div>
      ${item.impact ? `<div class="intel-impact">${esc(item.impact)}</div>` : ''}
    </article>
  `).join('');
}
function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3000)}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function escAttr(s){return esc(s).replace(/"/g,'&quot;')}
function md(s){return esc(s).replace(/^### (.*)$/gm,'<h3>$1</h3>').replace(/^## (.*)$/gm,'<h2>$1</h2>').replace(/^# (.*)$/gm,'<h2>$1</h2>').replace(/^- (.*)$/gm,'<div>• $1</div>').replace(/\\n/g,'<br>')}
loadSources();loadSummary();loadIntel();
</script>
</body>
</html>
"""


SETTINGS_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>音乐情报雷达 · 配置</title>
<style>
:root{
  --bg:#0c0c10;--panel:#14141d;--panel2:#1b1b26;--b:#2d2d3d;
  --t:#eeeeF6;--muted:#9191aa;--faint:#5f6076;--ac:#5b5ef4;--ok:#5bf4c8;--bad:#ff6b7a;
  --font:-apple-system,BlinkMacSystemFont,"Noto Sans SC","PingFang SC",sans-serif;
  --mono:"SFMono-Regular",Menlo,monospace;
}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--t);font-family:var(--font);font-size:14px}
header{height:58px;border-bottom:1px solid var(--b);display:flex;align-items:center;gap:14px;padding:0 28px;position:sticky;top:0;background:rgba(12,12,16,.94);backdrop-filter:blur(12px);z-index:10}
.logo{font-family:var(--mono);font-size:13px;color:var(--ac);font-weight:700}.logo span{color:#f45b8e}
.spacer{flex:1}.btn{border:1px solid var(--b);background:transparent;color:var(--t);height:32px;padding:0 14px;border-radius:4px;cursor:pointer;font-family:var(--mono);font-size:12px}
.btn:hover{border-color:var(--ac);color:#fff}.btn.primary{background:var(--ac);border-color:var(--ac)}.btn.good{background:rgba(91,244,200,.14);border-color:rgba(91,244,200,.4);color:var(--ok)}
main{max-width:760px;margin:0 auto;padding:28px}
@media(max-width:900px){main{padding:16px}}
.panel{background:var(--panel);border:1px solid var(--b);border-radius:6px;padding:18px}.panel h2{font-size:15px;margin:0 0 14px}.panel h3{font-size:13px;margin:20px 0 10px;color:var(--muted);font-family:var(--mono)}
.field{margin-bottom:12px}.field label{display:block;font-size:12px;color:var(--muted);margin-bottom:6px}.field input,.field textarea,.field select{width:100%;background:var(--panel2);border:1px solid var(--b);border-radius:4px;color:var(--t);padding:9px 10px;font:13px var(--mono);outline:none}.field textarea{min-height:78px;resize:vertical}.field input:focus,.field textarea:focus{border-color:var(--ac)}
.hint{font-size:12px;color:var(--faint);line-height:1.6}.status{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.pill{font:11px var(--mono);padding:4px 8px;border-radius:999px;background:var(--panel2);color:var(--muted);border:1px solid var(--b)}.pill.ok{color:var(--ok);border-color:rgba(91,244,200,.35)}.pill.bad{color:var(--bad);border-color:rgba(255,107,122,.35)}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.save-row{border-top:1px solid var(--b);margin-top:22px;padding-top:18px;display:flex;justify-content:flex-end}.save-row .btn{height:42px;padding:0 22px;font-size:13px}.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--ac);color:#fff;padding:10px 18px;border-radius:4px;font:12px var(--mono);display:none}.toast.show{display:block}
</style>
</head>
<body>
<header>
  <div class="logo">MUSIC<span>RADAR</span> · CONFIG</div>
  <button class="btn" onclick="location.href='/'">图片墙</button>
  <div class="spacer"></div>
  <button class="btn primary" onclick="saveConfig()">保存配置</button>
</header>
<main>
  <section class="panel">
    <h2>平台与分析配置</h2>
    <div class="status" id="status-pills"></div>

    <h3>视觉模型设置</h3>
    <div class="field">
      <label>API Key</label>
      <input id="VISION_API_KEY" type="password" placeholder="粘贴 key 后保存；同一浏览器会话内会保留">
      <div class="hint">支持 OpenAI-compatible API，不限定服务商。</div>
    </div>
    <div class="field"><label>模型</label><input id="VISION_MODEL" placeholder="gpt-5.4-mini"></div>
    <div class="field">
      <label>Base URL，可选</label>
      <input id="VISION_BASE_URL" placeholder="https://api.openai.com/v1">
      <div class="hint">例如：https://api.joyzhi.com/v1。需要兼容 /chat/completions。</div>
    </div>

    <h3>Dribbble / Behance / Pinterest 登录</h3>
    <div class="hint">不再填写 token。点击登录后会打开 Chromium，请用账号登录；采集时复用同一浏览器会话。</div>
    <div class="actions">
      <button class="btn good" id="login-dribbble" onclick="startPlatformLogin('dribbble')">Dribbble 未登录</button>
      <button class="btn good" id="login-behance" onclick="startPlatformLogin('behance')">Behance 未登录</button>
      <button class="btn good" id="login-pinterest" onclick="startPlatformLogin('pinterest')">Pinterest 未登录</button>
    </div>

    <h3 id="intel">产品/科技动向源</h3>
    <div class="field">
      <label>RSS 源，一行一个或逗号分隔；格式：名称|URL</label>
      <textarea id="TECH_FEEDS"></textarea>
      <div class="hint">默认包含爱范儿、少数派、36氪。公众号内容可接入支持 RSS/镜像的链接。</div>
    </div>

    <div class="save-row">
      <button class="btn primary" onclick="saveConfig()">保存配置</button>
    </div>
  </section>
</main>
<div class="toast" id="toast"></div>
<script>
let cfg = {};

async function loadConfig(){
  cfg = await (await fetch('/api/config')).json();
  for (const id of ['VISION_MODEL','VISION_BASE_URL','TECH_FEEDS']) {
    const el = document.getElementById(id);
    if (el) el.value = id === 'TECH_FEEDS' ? formatFeeds(cfg[id] || '') : (cfg[id] || '');
  }
  renderStatus();
}

function renderStatus(){
  const rows = [
    ['视觉模型', cfg.VISION_API_KEY_SET],
    ['Dribbble', cfg.DRIBBBLE_LOGGED_IN],
    ['Behance', cfg.BEHANCE_LOGGED_IN],
    ['Pinterest', cfg.PINTEREST_LOGGED_IN],
  ];
  document.getElementById('status-pills').innerHTML = rows.map(([k, ok]) =>
    `<span class="pill ${ok?'ok':'bad'}">${k}: ${ok?'已配置':'未配置'}</span>`
  ).join('');
  renderLoginButtons();
}

function renderLoginButtons(){
  const platforms = [
    ['dribbble', 'Dribbble', cfg.DRIBBBLE_LOGGED_IN],
    ['behance', 'Behance', cfg.BEHANCE_LOGGED_IN],
    ['pinterest', 'Pinterest', cfg.PINTEREST_LOGGED_IN],
  ];
  for (const [id, label, ok] of platforms) {
    const btn = document.getElementById(`login-${id}`);
    if (!btn) continue;
    btn.textContent = ok ? `${label} 已登录` : `${label} 未登录`;
    btn.classList.toggle('primary', !!ok);
    btn.classList.toggle('good', !ok);
  }
}

async function saveConfig(){
  const payload = {};
  for (const id of ['VISION_API_KEY','VISION_MODEL','VISION_BASE_URL','TECH_FEEDS']) {
    payload[id] = document.getElementById(id).value;
  }
  const res = await fetch('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  const data = await res.json();
  cfg = data.config || cfg;
  for (const id of ['VISION_API_KEY']) document.getElementById(id).value = '';
  renderStatus();
  toast('配置已保存');
}

async function startPlatformLogin(platform){
  await fetch(`/api/platform-login/${platform}`, {method:'POST'});
  toast(`已打开 ${platform} 登录窗口`);
  const timer = setInterval(async () => {
    const s = await (await fetch(`/api/platform-login/${platform}`)).json();
    if (!s.running) {
      clearInterval(timer);
      toast(s.logged_in ? `${platform} 登录已保存` : `${platform} 登录未完成`);
      await loadConfig();
    }
  }, 3000);
}

async function triggerImageCollect(){
  await saveConfig();
  await fetch('/api/collect', {method:'POST'});
  toast('截图采集已启动，回图片墙查看进度');
}

async function collectIntel(){
  await saveConfig();
  await fetch('/api/collect-intel', {method:'POST'});
  toast('产品动向采集已启动');
  const timer = setInterval(async () => {
    const s = await (await fetch('/api/status')).json();
    if (!s.intel?.running) {
      clearInterval(timer);
      toast(`产品动向新增 ${s.intel?.last_saved || 0} 条`);
      loadIntel();
    }
  }, 3000);
}

async function generateSummary(){
  await saveConfig();
  await fetch('/api/summary', {method:'POST'});
  toast('总体总结生成已启动');
  const timer = setInterval(async () => {
    const s = await (await fetch('/api/status')).json();
    if (!s.summary?.running) {
      clearInterval(timer);
      if (s.summary?.last_error) toast('总结生成失败，请检查 API 配置');
      else toast('总体总结已生成');
      loadSummary();
    }
  }, 3000);
}

async function loadSummary(){
  const data = await (await fetch('/api/summary')).json();
  const box = document.getElementById('summary-box');
  if (!data.report) {
    box.textContent = '还没有总结。';
    return;
  }
  box.innerHTML = md(data.report.content || '');
}

async function loadIntel(){
  const data = await (await fetch('/api/intel?limit=80')).json();
  const list = document.getElementById('intel-list');
  if (!data.items?.length) {
    list.innerHTML = '<div class="panel"><div class="hint">还没有产品动向，点击左侧「采集产品动向」。</div></div>';
    return;
  }
  list.innerHTML = data.items.map(item => `
    <article class="intel-card">
      <div class="intel-meta">${esc(item.platform || '')} · ${esc(item.category || '未分类')} · ${esc((item.published_at || item.created_at || '').slice(0,16))}</div>
      <div class="intel-title"><a href="${escAttr(item.source_url || '#')}" target="_blank">${esc(item.title || '无标题')}</a></div>
      <div class="intel-summary">${esc(item.summary || '')}</div>
      ${item.impact ? `<div class="intel-impact">${esc(item.impact)}</div>` : ''}
    </article>
  `).join('');
}

function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3000)}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function escAttr(s){return esc(s).replace(/"/g,'&quot;')}
function formatFeeds(s){return String(s||'').split(',').map(x=>x.trim()).filter(Boolean).join('\\n')}
function md(s){
  return esc(s)
    .replace(/^### (.*)$/gm, '<h3>$1</h3>')
    .replace(/^## (.*)$/gm, '<h2>$1</h2>')
    .replace(/^# (.*)$/gm, '<h2>$1</h2>')
    .replace(/^- (.*)$/gm, '<div>• $1</div>')
    .replace(/\\n/g, '<br>');
}

loadConfig();
</script>
</body>
</html>
"""
