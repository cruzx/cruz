"""
collectors/behance.py · Behance 登录态网页采集
"""
import asyncio
import os
import re
from pathlib import Path
from urllib.parse import quote

from rich import print as rprint


SEARCH_QUERIES = ["music app", "music player", "audio streaming", "music ui"]


def _data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "./data")).expanduser().resolve()


async def _screenshot_cards(page) -> list[bytes]:
    selectors = [
        "[class*='ProjectCover']",
        "[data-id]",
        "a[href*='/gallery/']",
        "img[src*='behance']",
    ]
    cards = []
    for sel in selectors:
        cards = await page.query_selector_all(sel)
        if cards:
            break
    shots = []
    seen_boxes = set()
    for card in cards[:16]:
        try:
            box = await card.bounding_box()
            if not box or box["width"] < 120 or box["height"] < 90:
                continue
            key = (round(box["x"]), round(box["y"]), round(box["width"]), round(box["height"]))
            if key in seen_boxes:
                continue
            seen_boxes.add(key)
            await card.scroll_into_view_if_needed()
            await page.wait_for_timeout(250)
            shot = await card.screenshot(type="png")
            if len(shot) > 5000:
                shots.append(shot)
        except Exception:
            continue
    return shots


async def collect(sem: asyncio.Semaphore) -> list[dict]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        rprint("[red]  [Behance] playwright 未安装[/red]")
        return []

    data_dir = _data_dir()
    profile_dir = data_dir / "behance_profile"
    if not profile_dir.exists():
        rprint("[yellow]  [Behance] 未登录，跳过（到配置页点击 Behance 登录）[/yellow]")
        return []

    results = []
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=os.getenv("BEHANCE_HEADLESS", "false").lower() in {"1", "true", "yes"},
            viewport={"width": 1280, "height": 1000},
            args=["--no-sandbox"],
        )
        page = await context.new_page()
        for query in SEARCH_QUERIES:
            url = f"https://www.behance.net/search/projects?search={quote(query)}"
            try:
                rprint(f"  [Behance] 搜索: {query}")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(5000)
                for _ in range(2):
                    await page.mouse.wheel(0, 900)
                    await page.wait_for_timeout(900)
                shots = await _screenshot_cards(page)
                slug = re.sub(r"\W+", "_", query)
                for i, shot in enumerate(shots):
                    results.append({
                        "source": "behance",
                        "source_id": f"{slug}_{i}",
                        "source_url": url,
                        "title": f"Behance 搜索 · {query}",
                        "author": "",
                        "tags": [query, "Behance", "搜索结果"],
                        "likes": 0,
                        "views": 0,
                        "image_bytes": shot,
                    })
            except Exception as e:
                rprint(f"[yellow]  [Behance] {query} 失败: {e}[/yellow]")
        await context.close()
    rprint(f"[green]  [Behance] 共采集 {len(results)} 张[/green]")
    return results
