"""
collectors/xhs_login.py · 小红书扫码登录
用 Playwright 打开登录页，展示二维码，等你扫码后保存 Cookie。
之后采集时直接加载已保存的 Cookie，不需要再次扫码。
"""
import json
import asyncio
from pathlib import Path
from typing import Optional
from rich import print as rprint
from rich.panel import Panel

COOKIE_FILE: Path = None  # 由外部初始化
STATE_FILE: Path = None
PROFILE_DIR: Path = None


def init_login(data_dir: Path):
    global COOKIE_FILE, STATE_FILE, PROFILE_DIR
    COOKIE_FILE = data_dir / "xhs_cookies.json"
    STATE_FILE = data_dir / "xhs_state.json"
    PROFILE_DIR = data_dir / "xhs_profile"


def is_logged_in() -> bool:
    """检查是否有有效的 Cookie 文件"""
    return (
        PROFILE_DIR and PROFILE_DIR.exists()
    ) or (
        STATE_FILE and STATE_FILE.exists() and STATE_FILE.stat().st_size > 10
    ) or (
        COOKIE_FILE and COOKIE_FILE.exists() and COOKIE_FILE.stat().st_size > 10
    )


async def login_with_qr() -> bool:
    """
    打开浏览器，引导用户扫码登录小红书。
    成功后保存 Cookie 到本地文件，返回 True。
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        rprint("[red]playwright 未安装，运行: playwright install chromium[/red]")
        return False

    rprint(Panel(
        "[bold]小红书登录[/bold]\n\n"
        "浏览器将自动打开小红书登录页面\n"
        "请用手机小红书 App 扫描页面上的二维码完成登录\n\n"
        "[dim]登录成功后程序会自动继续，Cookie 保存在本地[/dim]",
        title="[red]扫码登录[/red]",
        expand=False,
    ))

    async with async_playwright() as pw:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        # 用持久化浏览器目录登录，采集时复用同一个 profile。
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=["--no-sandbox"],
            viewport={"width": 900, "height": 700},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        # 打开登录页
        await page.goto("https://www.xiaohongshu.com/", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # 点击登录按钮（如果页面有的话）
        try:
            login_btn = await page.query_selector("[class*='login'], .login-btn, .sign-in")
            if login_btn:
                await login_btn.click()
                await page.wait_for_timeout(1500)
        except Exception:
            pass

        rprint("[cyan]请在弹出的浏览器窗口中扫码登录...[/cyan]")
        rprint("[dim]（扫码后程序自动检测登录状态，最多等待 3 分钟）[/dim]")

        # 等待登录成功：不能只看 Cookie，小红书未登录态也会写入部分 Cookie。
        logged_in = False
        for _ in range(180):  # 最多等 3 分钟
            await asyncio.sleep(1)
            cookies = await context.cookies()
            cookie_names = {c["name"] for c in cookies}
            try:
                body_text = await page.locator("body").inner_text(timeout=1000)
            except Exception:
                body_text = ""
            login_wall = any(t in body_text for t in ("手机号登录", "扫码", "获取验证码", "登录后查看"))
            if "web_session" in cookie_names and not login_wall:
                logged_in = True
                break

        if logged_in:
            # 保存所有 Cookie
            cookies = await context.cookies(["https://www.xiaohongshu.com"])
            COOKIE_FILE.write_text(
                json.dumps(cookies, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            await context.storage_state(path=str(STATE_FILE))
            rprint(f"[green]✓ 登录成功！Cookie 已保存到 {COOKIE_FILE}[/green]")
            rprint(f"[green]✓ 浏览器状态已保存到 {STATE_FILE}[/green]")
            await page.wait_for_timeout(1000)
        else:
            rprint("[red]✗ 等待超时，未检测到登录状态，请重试[/red]")

        await context.close()
        return logged_in


def load_cookies() -> list[dict]:
    """加载已保存的 Cookie"""
    if not is_logged_in():
        return []
    try:
        return json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def load_storage_state() -> Optional[str]:
    """返回 Playwright storage_state 文件路径。"""
    if STATE_FILE and STATE_FILE.exists() and STATE_FILE.stat().st_size > 10:
        return str(STATE_FILE)
    return None


def load_profile_dir() -> Optional[str]:
    if PROFILE_DIR and PROFILE_DIR.exists():
        return str(PROFILE_DIR)
    return None


async def verify_login() -> bool:
    """
    用已有 Cookie 验证登录状态是否还有效。
    失效时返回 False，提示重新扫码。
    """
    cookies = load_cookies()
    if not cookies:
        return False

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            profile_dir = load_profile_dir()
            if profile_dir:
                context = await pw.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=False,
                    locale="zh-CN",
                    viewport={"width": 900, "height": 700},
                )
            else:
                browser = await pw.chromium.launch(headless=True)
                context = await browser.new_context(locale="zh-CN")
                await context.add_cookies(cookies)
            page = await context.new_page()
            await page.goto(
                "https://www.xiaohongshu.com/search_result?keyword=%E9%9F%B3%E4%B9%90APP&type=51",
                wait_until="domcontentloaded",
            )
            await page.wait_for_timeout(3000)
            body_text = await page.locator("body").inner_text(timeout=5000)
            has_login_wall = "登录后查看搜索结果" in body_text or "手机号登录" in body_text
            has_search_content = await page.locator("a[href*='explore']").count() > 3
            valid = has_search_content and not has_login_wall
            await context.close()
            return valid
    except Exception:
        return False
