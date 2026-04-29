"""
collectors/xhs.py · 小红书采集
使用 xhs_login.py 保存的 Cookie 文件登录，截图笔记图片
"""
import asyncio
import re
import os
from urllib.parse import quote
from rich import print as rprint

try:
    from playwright.async_api import async_playwright, Page
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from collectors.xhs_login import load_cookies, load_storage_state, load_profile_dir, is_logged_in

XHS_SEARCH_URL = "https://www.xiaohongshu.com/search_result?keyword={keyword}&type=51"


async def _wait_for_images(page):
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(2500)


async def _screenshot_note_images(page, note_url: str) -> list:
    screenshots = []
    try:
        await page.goto(note_url, wait_until="domcontentloaded", timeout=20000)
        await _wait_for_images(page)

        selectors = [
            ".note-slider .swiper-slide img",
            ".carousel-container img",
            "[class*='slide'] img",
            ".image-container img",
            "section.note-content img",
        ]
        img_elements = []
        for sel in selectors:
            img_elements = await page.query_selector_all(sel)
            if img_elements:
                break

        if not img_elements:
            content = await page.query_selector(".note-content, main, article")
            if content:
                screenshots.append(await content.screenshot(type="png"))
            return screenshots

        for img in img_elements[:9]:
            try:
                await img.scroll_into_view_if_needed()
                await page.wait_for_timeout(400)
                shot = await img.screenshot(type="png")
                if len(shot) > 5000:
                    screenshots.append(shot)
            except Exception:
                continue

    except Exception as e:
        rprint(f"[red]    截图失败 {note_url[:60]}: {e}[/red]")
    return screenshots


async def _screenshot_search_cards(page) -> list:
    """直接截搜索结果卡片。小红书详情页经常拦截网页访问，搜索页反而稳定。"""
    screenshots = []
    selectors = [".note-item", ".feeds-container section", "[class*='note-item']"]
    cards = []
    for sel in selectors:
        cards = await page.query_selector_all(sel)
        if cards:
            break

    for card in cards[:12]:
        try:
            await card.scroll_into_view_if_needed()
            await page.wait_for_timeout(300)
            shot = await card.screenshot(type="png")
            if len(shot) > 5000:
                screenshots.append(shot)
        except Exception:
            continue
    return screenshots


async def collect(sem: asyncio.Semaphore) -> list:
    if not HAS_PLAYWRIGHT:
        rprint("[red]  [小红书] playwright 未安装[/red]")
        return []

    if not is_logged_in():
        rprint("[yellow]  [小红书] 未登录，跳过（主菜单选「小红书登录」）[/yellow]")
        return []

    cookies = load_cookies()
    state_path = load_storage_state()
    profile_dir = load_profile_dir()
    if not cookies and not state_path and not profile_dir:
        rprint("[yellow]  [小红书] Cookie 加载失败，跳过[/yellow]")
        return []

    keywords_raw = os.getenv("XHS_KEYWORDS", "音乐APP,听歌体验,音乐播放器UI,酷狗音乐,网易云音乐")
    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
    results = []

    async with async_playwright() as pw:
        headless = os.getenv("XHS_HEADLESS", "false").strip().lower() in {"1", "true", "yes", "y"}
        context_kwargs = {
            "viewport": {"width": 1280, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "locale": "zh-CN",
        }
        if profile_dir:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                **context_kwargs,
            )
        else:
            browser = await pw.chromium.launch(
                headless=headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context_kwargs["device_scale_factor"] = 2
            if state_path:
                context_kwargs["storage_state"] = state_path
            context = await browser.new_context(**context_kwargs)
        if cookies and not state_path and not profile_dir:
            await context.add_cookies(cookies)
        page = await context.new_page()

        for keyword in keywords:
            rprint(f"  [小红书] 搜索: {keyword}")
            try:
                url = XHS_SEARCH_URL.format(keyword=quote(keyword))
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                await _wait_for_images(page)
                for _ in range(2):
                    await page.mouse.wheel(0, 700)
                    await page.wait_for_timeout(800)

                card_shots = await _screenshot_search_cards(page)
                for i, shot_bytes in enumerate(card_shots):
                    results.append({
                        "source": "xhs",
                        "source_id": f"{keyword}_{i}",
                        "source_url": url,
                        "title": f"小红书搜索 · {keyword}",
                        "author": "",
                        "tags": [keyword, "小红书", "搜索结果"],
                        "likes": 0,
                        "views": 0,
                        "image_bytes": shot_bytes,
                    })
                if card_shots:
                    rprint(f"    搜索结果卡片截图: {len(card_shots)} 张")
                    continue

                note_links = await page.eval_on_selector_all(
                    "a[href*='explore']",
                    "els => els.map(e => e.href)"
                )
                note_links = [
                    href for href in dict.fromkeys(note_links)
                    if re.search(r"/explore/[0-9a-f]{24}", href)
                ][:8]
                if not note_links:
                    body_text = (await page.locator("body").inner_text(timeout=5000))[:80]
                    rprint(f"[yellow]  [小红书] 未找到搜索结果，页面提示: {body_text}[/yellow]")

                for note_url in note_links:
                    async with sem:
                        rprint(f"    -> {note_url[:70]}")
                        shots = await _screenshot_note_images(page, note_url)
                        await asyncio.sleep(1.5)

                    m = re.search(r"/explore/(\w+)", note_url, re.I)
                    base_id = m.group(1) if m else note_url[-8:]

                    for i, shot_bytes in enumerate(shots):
                        results.append({
                            "source": "xhs",
                            "source_id": f"{base_id}_{i}",
                            "source_url": note_url,
                            "title": f"小红书 · {keyword}",
                            "author": "",
                            "tags": [keyword, "小红书"],
                            "likes": 0,
                            "views": 0,
                            "image_bytes": shot_bytes,
                        })

            except Exception as e:
                rprint(f"[red]  [小红书] '{keyword}' 失败: {e}[/red]")

        await context.close()

    rprint(f"[green]  [小红书] 共采集 {len(results)} 张[/green]")
    return results
