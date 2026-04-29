"""
collectors/browser_login.py · 通用网页登录 profile
"""
from pathlib import Path

from rich import print as rprint
from rich.panel import Panel


async def login_with_browser(data_dir: Path, platform: str, login_url: str, wait_seconds: int = 180) -> bool:
    from playwright.async_api import async_playwright

    profile_dir = data_dir / f"{platform}_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    rprint(Panel(
        f"[bold]{platform} 登录[/bold]\n\n"
        f"浏览器将打开 {login_url}\n"
        "请在窗口中完成账号登录。\n\n"
        "[dim]登录完成后稍等，程序会保存同一个浏览器会话供采集使用。[/dim]",
        title="[cyan]账号登录[/cyan]",
        expand=False,
    ))

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--no-sandbox"],
        )
        page = await context.new_page()
        await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        for _ in range(wait_seconds):
            await page.wait_for_timeout(1000)
            url = page.url.lower()
            if all(word not in url for word in ("login", "signin", "sign-in", "auth")):
                await context.close()
                return True
        await context.close()
    return profile_dir.exists()


def has_profile(data_dir: Path, platform: str) -> bool:
    return (data_dir / f"{platform}_profile").exists()
