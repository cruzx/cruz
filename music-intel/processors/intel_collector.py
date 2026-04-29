"""
processors/intel_collector.py · 产品/科技动向采集入库
"""
from rich import print as rprint

from collectors.tech_news import collect_tech_news
from storage import db


async def run_intel_collection(use_ai: bool = False) -> int:
    rprint("\n[bold cyan]═══ 开始采集产品动向 ═══[/bold cyan]")
    items = await collect_tech_news()
    saved = 0
    for item in items:
        record = {
            **item,
            "summary": item.get("raw_content", "")[:220],
            "category": "待总结",
            "impact": "",
            "raw_content": item.get("raw_content", ""),
        }
        rowid = await db.insert_feature(record)
        if rowid:
            saved += 1
    rprint(f"[bold green]✓ 产品动向采集完成：新增 {saved} 条[/bold green]\n")
    return saved
