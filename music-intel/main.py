#!/usr/bin/env python3
"""
main.py · 音乐情报雷达 · 入口
用法:
  python main.py          → 启动服务 + 打开浏览器
  python main.py collect  → 只跑一次采集
"""
import sys, os, asyncio, subprocess, time
from pathlib import Path
from dotenv import load_dotenv
from rich import print as rprint
from rich.panel import Panel
from rich.console import Console

load_dotenv(Path(__file__).parent / ".env")

console = Console()

DATA_DIR  = Path(os.getenv("DATA_DIR", "./data")).expanduser().resolve()
PORT      = int(os.getenv("PORT", "8765"))
INTERVAL  = int(os.getenv("COLLECT_INTERVAL_HOURS", "24"))
HAS_AI_KEY = bool(os.getenv("VISION_API_KEY", "").strip())


def ensure_dirs():
    for sub in ("images/dribbble", "images/behance", "images/pinterest"):
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)


def print_banner():
    mode = os.getenv("STORAGE_MODE", "local")
    mode_label = "[cyan]本地文件夹[/cyan]" if mode == "local" else "[magenta]Supabase 云端[/magenta]"
    rprint(Panel(
        f"[bold white]音乐情报雷达[/bold white]\n"
        f"[dim]数据目录: {DATA_DIR}[/dim]\n"
        f"[dim]存储模式: {mode_label}[/dim]\n"
        f"[dim]看板地址: http://localhost:{PORT}[/dim]",
        title="[cyan]MUSIC RADAR[/cyan]",
        expand=False,
    ))


def check_env() -> list:
    warnings = []
    if not os.getenv("VISION_API_KEY", "").strip():
        warnings.append("⚠  视觉模型 API Key 未设置，AI 分析不可用")
    if not (DATA_DIR / "dribbble_profile").exists():
        warnings.append("ℹ  Dribbble 尚未网页登录，跳过 Dribbble")
    if not (DATA_DIR / "behance_profile").exists():
        warnings.append("ℹ  Behance 尚未网页登录，跳过 Behance")
    if not (DATA_DIR / "pinterest_profile").exists():
        warnings.append("ℹ  Pinterest 尚未网页登录，跳过 Pinterest")
    return warnings

# ── 纯采集 ─────────────────────────────────────────────

async def do_collect():
    from storage import db, image_store
    from processors.collector import run_collection

    ensure_dirs()
    await db.init_db(DATA_DIR)
    image_store.init_image_store(DATA_DIR)
    await run_collection(DATA_DIR, use_ai=False)


def cmd_collect():
    print_banner()
    for w in check_env():
        rprint(f"[yellow]{w}[/yellow]")
    asyncio.run(do_collect())


# ── 服务器模式 ──────────────────────────────────────────

def cmd_serve():
    print_banner()

    warnings = check_env()
    for w in warnings:
        rprint(f"[yellow]{w}[/yellow]")

    ensure_dirs()

    # 延迟打开浏览器
    import threading
    def open_browser():
        time.sleep(1.8)
        subprocess.Popen(["open", f"http://localhost:{PORT}"])
    threading.Thread(target=open_browser, daemon=True).start()

    rprint(f"\n[green]✓ 启动中，浏览器即将自动打开...[/green]")
    rprint(f"[dim]按 Ctrl+C 停止[/dim]\n")

    from server import start_server
    start_server(DATA_DIR, port=PORT, interval_hours=INTERVAL)


# ── 入口 ───────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    {"serve": cmd_serve, "collect": cmd_collect}.get(cmd, cmd_serve)()
