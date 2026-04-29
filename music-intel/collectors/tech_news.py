"""
collectors/tech_news.py · 科技/产品动向 RSS 采集
"""
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx
from rich import print as rprint

from storage.config_store import parse_feeds


def _text(node, name: str) -> str:
    child = node.find(name)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(value: str) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).isoformat()
    except Exception:
        return value[:32]


def _items_from_feed(source: str, xml_text: str, limit: int) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    result = []
    for node in items[:limit]:
        title = _text(node, "title") or _text(node, "{http://www.w3.org/2005/Atom}title")
        link = _text(node, "link")
        if not link:
            link_node = node.find("{http://www.w3.org/2005/Atom}link")
            link = link_node.attrib.get("href", "") if link_node is not None else ""
        summary = (
            _text(node, "description")
            or _text(node, "summary")
            or _text(node, "{http://www.w3.org/2005/Atom}summary")
            or _text(node, "{http://purl.org/rss/1.0/modules/content/}encoded")
        )
        published = (
            _text(node, "pubDate")
            or _text(node, "published")
            or _text(node, "{http://www.w3.org/2005/Atom}published")
            or _text(node, "updated")
            or _text(node, "{http://www.w3.org/2005/Atom}updated")
        )
        if title and link:
            result.append({
                "platform": source,
                "source_type": "rss",
                "title": _strip_html(title),
                "source_url": link,
                "published_at": _parse_date(published),
                "raw_content": _strip_html(summary)[:1800],
            })
    return result


async def collect_tech_news(limit_per_feed: int = 12) -> list[dict]:
    feeds = parse_feeds()
    results: list[dict] = []
    headers = {"User-Agent": "Mozilla/5.0 MusicIntel/1.0"}
    async with httpx.AsyncClient(headers=headers, timeout=20, follow_redirects=True) as client:
        for feed in feeds:
            try:
                rprint(f"  [Tech] {feed['name']}: {feed['url']}")
                resp = await client.get(feed["url"])
                resp.raise_for_status()
                results.extend(_items_from_feed(feed["name"], resp.text, limit_per_feed))
            except Exception as e:
                rprint(f"[yellow]  [Tech] {feed['name']} 采集失败: {e}[/yellow]")
    rprint(f"[green]  [Tech] 共采集 {len(results)} 条[/green]")
    return results
