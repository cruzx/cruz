"""
processors/claude_analyzer.py · 通用视觉模型分析模块
支持 OpenAI-compatible API：VISION_API_KEY / VISION_MODEL / VISION_BASE_URL
"""
import base64
import imghdr
import json
import re
import os
import httpx

DEFAULT_BASE_URL = "https://api.openai.com/v1"


def _parse_json(text: str) -> dict:
    """容错解析 Claude 返回的 JSON"""
    text = text.strip()
    # 尝试提取 ```json ... ``` 块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    # 直接找最外层 {}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return {}


def analyze_image(image_bytes: bytes, source: str) -> dict:
    """
    用 Claude Vision 分析设计截图。
    返回结构化设计标签，失败时返回空 dict。
    """
    if not image_bytes:
        return {}
    if not os.getenv("VISION_API_KEY", "").strip():
        return {}

    b64 = base64.standard_b64encode(image_bytes).decode()
    image_type = imghdr.what(None, image_bytes) or "png"
    media_type = "image/jpeg" if image_type == "jpeg" else f"image/{image_type}"
    prompt = f"来源平台：{source}。这是一张音乐/内容产品相关截图，请分析其中的产品情报。"
    system = """你是专业的音乐、内容、社区产品情报分析师。
分析图片，严格返回 JSON，不输出其他任何内容：
{
  "style_tags": ["设计风格或产品机制标签，如：订阅转化、社区互动、AI入口、短视频化"],
  "color_palette": ["#主色1","#主色2","#主色3"],
  "layout_pattern": "信息架构/交互布局描述，如：卡片流、全屏播放器、任务入口、弹窗转化",
  "key_elements": ["新的功能点、新交互、增长机制、值得关注的产品动作"],
  "reference_value": "high 或 mid 或 low",
  "notes": "总结它代表的产品动向，以及对音乐产品可借鉴/需警惕的点，80字以内"
}"""

    try:
        text = _chat_completion([
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}},
            ]},
        ], max_tokens=700)
        return _parse_json(text)
    except Exception as e:
        print(f"  [Vision] 图片分析失败: {e}")
        return {}


def analyze_article(title: str, content: str, source: str) -> dict:
    """分析科技/产品文章，返回结构化情报。"""
    if not os.getenv("VISION_API_KEY", "").strip():
        return {
            "summary": (content or title)[:180],
            "category": "未分析",
            "impact": "未配置视觉模型 API Key，先按原文摘要入库。",
        }
    prompt = f"来源：{source}\n标题：{title}\n正文摘要：{content[:2500]}"
    try:
        text = _chat_completion([
            {"role": "system", "content": """你是面向音乐/内容产品团队的产品情报分析师。
请严格返回 JSON，不输出其他内容：
{
  "summary": "一句话总结",
  "category": "新功能/新交互/商业化/AI/硬件/内容生态/公司动向/其他",
  "impact": "这对音乐、音频、社区或会员产品意味着什么，80字以内",
  "signals": ["可观察到的产品信号"],
  "watch": ["后续值得继续跟踪的问题"]
}"""},
            {"role": "user", "content": prompt},
        ], max_tokens=700)
        return _parse_json(text)
    except Exception as e:
        print(f"  [Vision] 文章分析失败: {e}")
        return {
            "summary": (content or title)[:180],
            "category": "分析失败",
            "impact": str(e)[:160],
        }


def analyze_overall(images: list[dict], features: list[dict]) -> str:
    """一次性生成总体产品情报总结。"""
    if not os.getenv("VISION_API_KEY", "").strip():
        return "未配置视觉模型 API Key，无法生成总体总结。请在配置页填写 API Key、模型和 Base URL。"

    image_lines = []
    for item in images[:80]:
        tags = item.get("tags") or []
        if isinstance(tags, list):
            tags_text = "、".join(str(t) for t in tags[:5])
        else:
            tags_text = str(tags)
        image_lines.append(
            f"- [{item.get('source','')}] {item.get('title','')} 标签:{tags_text} 链接:{item.get('source_url','')}"
        )

    feature_lines = []
    for item in features[:80]:
        feature_lines.append(
            f"- [{item.get('platform','')}] {item.get('title','')} 摘要:{item.get('summary') or item.get('raw_content','')}"
        )

    prompt = f"""请基于以下采集结果生成一份中文产品情报总体总结。

设计/截图样本：
{chr(10).join(image_lines) or "无"}

科技/产品文章：
{chr(10).join(feature_lines) or "无"}

输出要求：
1. 不要逐条复述。
2. 聚焦“有什么新的功能”“市面上有什么新的交互”“有什么新的产品动向”。
3. 给音乐/内容产品团队可执行建议。
4. 用 Markdown，包含：总体判断、值得关注的新功能、新交互模式、产品/商业动向、可借鉴机会、后续跟踪清单。"""

    return _chat_completion([
        {"role": "system", "content": "你是资深音乐、内容、社区产品战略分析师。输出高密度中文产品情报总结。"},
        {"role": "user", "content": prompt},
    ], max_tokens=1600)


def _chat_completion(messages: list, max_tokens: int = 700) -> str:
    key = os.getenv("VISION_API_KEY", "").strip()
    model = os.getenv("VISION_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini"
    base_url = (os.getenv("VISION_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL).rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]
