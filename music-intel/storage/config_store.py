"""
storage/config_store.py · .env 配置读写
"""
import os
import re
from pathlib import Path
from typing import Any, Optional

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

DEFAULT_TECH_FEEDS = (
    "爱范儿|https://www.ifanr.com/feed,"
    "少数派|https://sspai.com/feed,"
    "36氪|https://36kr.com/feed,"
    "cnBeta|https://www.cnbeta.com.tw/backend.php,"
    "IT之家|https://www.ithome.com/rss/,"
    "Solidot|https://www.solidot.org/index.rss,"
    "虎嗅|https://rss.huxiu.com/,"
    "钛媒体|https://www.tmtpost.com/rss.xml,"
    "Product Hunt|https://www.producthunt.com/feed,"
    "TechCrunch|https://techcrunch.com/feed/,"
    "The Verge|https://www.theverge.com/rss/index.xml"
)

DEFAULTS = {
    "VISION_API_KEY": "",
    "VISION_MODEL": "gpt-5.4-mini",
    "VISION_BASE_URL": "https://api.openai.com/v1",
    "STORAGE_MODE": "local",
    "SUPABASE_URL": "",
    "SUPABASE_KEY": "",
    "SUPABASE_BUCKET": "design-images",
    "DATA_DIR": "./data",
    "PORT": "8765",
    "COLLECT_INTERVAL_HOURS": "24",
    "TECH_FEEDS": DEFAULT_TECH_FEEDS,
}

SECRET_KEYS = {"VISION_API_KEY", "SUPABASE_KEY"}


def load_config() -> dict[str, str]:
    values = {**DEFAULTS, **{k: v for k, v in dotenv_values(ENV_PATH).items() if v is not None}}
    return values


def public_config() -> dict[str, Any]:
    values = load_config()
    result: dict[str, Any] = {}
    for key, val in values.items():
        if key in SECRET_KEYS:
            result[key] = ""
            result[f"{key}_SET"] = bool(val.strip())
        else:
            result[key] = val
    result["DRIBBBLE_LOGGED_IN"] = (ROOT / "data" / "dribbble_profile").exists()
    result["BEHANCE_LOGGED_IN"] = (ROOT / "data" / "behance_profile").exists()
    result["PINTEREST_LOGGED_IN"] = (ROOT / "data" / "pinterest_profile").exists()
    return result


def save_config(payload: dict[str, Any]) -> dict[str, str]:
    current = load_config()
    for key in DEFAULTS:
        if key not in payload:
            continue
        value = str(payload.get(key) or "").strip()
        if key == "TECH_FEEDS":
            value = _normalize_feeds(value) or DEFAULT_TECH_FEEDS
        if key in SECRET_KEYS and not value:
            continue
        current[key] = value

    lines = [
        "# 音乐情报雷达配置",
        "# 密钥留空保存时表示保持原值。",
        "",
    ]
    for key in DEFAULTS:
        lines.append(f"{key}={current.get(key, '')}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    for key, value in current.items():
        os.environ[key] = value
    return current


def parse_feeds(raw: Optional[str] = None) -> list[dict[str, str]]:
    raw = raw if raw is not None else load_config().get("TECH_FEEDS", "")
    feeds = []
    for part in re.split(r"[\n,]+", raw or ""):
        part = part.strip()
        if not part:
            continue
        if "|" in part:
            name, url = part.split("|", 1)
        else:
            name, url = part, part
        if url.strip():
            feeds.append({"name": name.strip(), "url": url.strip()})
    return feeds


def _normalize_feeds(raw: str) -> str:
    parts = [p.strip() for p in re.split(r"[\n,]+", raw or "") if p.strip()]
    return ",".join(parts)
