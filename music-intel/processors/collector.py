"""
processors/collector.py · 采集主调度器
统一调用各平台 collector，存图 + 写库
"""
import asyncio
from pathlib import Path
from rich import print as rprint
from rich.progress import Progress, SpinnerColumn, TextColumn

from storage import db, image_store
from collectors import dribbble, behance, pinterest


async def run_collection(data_dir: Path, use_ai: bool = False):
    """执行一次完整采集"""
    rprint("\n[bold cyan]═══ 开始采集 ═══[/bold cyan]")

    # 并发限制：最多同时 4 个下载任务
    sem = asyncio.Semaphore(4)

    # 并发运行三个平台
    platform_results = await asyncio.gather(
        dribbble.collect(sem),
        behance.collect(sem),
        pinterest.collect(sem),
        return_exceptions=True,
    )

    all_items = []
    for r in platform_results:
        if isinstance(r, Exception):
            rprint(f"[red]平台采集异常: {r}[/red]")
        else:
            all_items.extend(r)

    rprint(f"\n[cyan]共获取 {len(all_items)} 条原始数据，开始存储...[/cyan]")

    saved = 0
    skipped = 0

    for item in all_items:
        img_bytes = item.pop("image_bytes", None)
        if not img_bytes or len(img_bytes) < 1000:
            skipped += 1
            continue

        # 存图（自动去重）
        img_hash, local_path = image_store.save_image(img_bytes, item["source"])

        # 检查数据库是否已有
        if await db.image_exists(img_hash):
            skipped += 1
            continue

        record = {
            **item,
            "local_path": local_path,
            "img_hash": img_hash,
            "ai_style_tags": [],
            "ai_color_palette": [],
            "ai_layout": "",
            "ai_key_elements": [],
            "ai_reference": "",
            "ai_notes": "",
        }

        await db.insert_image(record)
        saved += 1

    rprint(f"\n[bold green]✓ 采集完成：新增 {saved} 张，跳过(已存在) {skipped} 条[/bold green]\n")
    return saved
