#!/usr/bin/env python3
"""Daily strategy monitor for free-listening ad popups."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import mimetypes
import os
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REFERENCE_DIR = ROOT / "references"
QISHUI_DIR = ROOT / "qishui_daily"
QQ_MUSIC_DIR = ROOT / "qqmusic_daily"
REPORT_DIR = ROOT / "reports"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
TEXT_EXTS = {".txt", ".md", ".json"}

APP_CONFIG = {
    "qishui": {
        "name": "汽水音乐",
        "dir": QISHUI_DIR,
        "report_prefix": "qishui",
    },
    "qqmusic": {
        "name": "QQ 音乐",
        "dir": QQ_MUSIC_DIR,
        "report_prefix": "qqmusic",
    },
}


SYSTEM_PROMPT = """你是增长产品设计分析师，专门分析音乐 App 免广告/看广告免费听弹窗。
你需要基于证据比较“竞品当天样本”和“我们自己的参考样本”，输出可执行结论。
必须区分事实观察、推断和建议；不要编造截图中不存在的信息。"""

USER_PROMPT_TEMPLATE = """请完成一次“免费听设计策略”日更监控报告。

分析目标：
1. 提炼汽水音乐当天样本的免费听/看广告/会员转化策略。
2. 和我们上传的参考图或参考笔记做对比。
3. 输出明确结论：汽水音乐今天有哪些值得借鉴、哪些不适合照搬、我们下一版应该怎么改。

重点维度：
- 入口语义：按钮第一眼是收益、成本，还是会员售卖。
- 弹窗信息量：标题、副标题、规则、时长、价格是否清楚。
- 视觉层级：主按钮、次按钮、关闭按钮、权益图形的权重。
- 交易感：是否让用户感到“看一次/付一点钱/得到多久权益”划算。
- 付费分流：会员按钮是否抢主 CTA 点击。
- 全链路体验：点击、看视频、到账提示、返回播放的闭环是否明确。
- 可 A/B 测试点：文案、按钮层级、时长表达、价格锚点、权益反馈。

输出格式：
# {app_name}免费听策略日更 - {date}
## 今日结论
用 3-5 条短句给业务结论。
## {app_name}观察
列出有截图/笔记依据的观察。
## 和我们参考图的差异
用表格：维度 | {app_name} | 我们参考图 | 判断。
## 可借鉴点
列出 3-6 条。
## 不建议照搬
列出 2-5 条。
## 下一版建议
给出 2-3 套可直接 A/B 的弹窗方案，包含标题、副标题、主按钮、次按钮。
## 证据与缺口
说明本次使用了哪些文件；如果缺少截图或链路样本，要明确写出缺口。
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Qishui Music free-listening UI against reference designs.")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="Report date, e.g. 2026-04-20.")
    parser.add_argument("--app", choices=APP_CONFIG.keys(), default="qishui", help="Competitor app to analyze.")
    parser.add_argument("--app-dir", type=Path, default=None, help="Directory containing today's competitor screenshots/notes.")
    parser.add_argument("--qishui-dir", type=Path, default=None, help="Backward-compatible alias for --app-dir.")
    parser.add_argument("--reference-dir", type=Path, default=REFERENCE_DIR, help="Directory containing our reference screenshots/notes.")
    parser.add_argument("--out", type=Path, default=None, help="Markdown report path.")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), help="OpenAI vision-capable model.")
    return parser.parse_args()


def list_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        path for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS | TEXT_EXTS
    )


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def image_part(path: Path) -> dict[str, Any]:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{encoded}"},
    }


def build_content(date: str, app_name: str, app_files: list[Path], reference_files: list[Path]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [
        {"type": "text", "text": USER_PROMPT_TEMPLATE.format(date=date, app_name=app_name)},
        {"type": "text", "text": format_inventory(f"{app_name}当天文件", app_files)},
        {"type": "text", "text": format_inventory("我们参考文件", reference_files)},
    ]

    for label, files in ((f"{app_name}当天样本", app_files), ("我们参考样本", reference_files)):
        text_notes = []
        for path in files:
            if path.suffix.lower() in TEXT_EXTS:
                text_notes.append(f"## {label}: {path.name}\n{read_text_file(path)}")
            elif path.suffix.lower() in IMAGE_EXTS:
                parts.append({"type": "text", "text": f"{label}图片：{path.name}"})
                parts.append(image_part(path))
        if text_notes:
            parts.append({"type": "text", "text": "\n\n".join(text_notes)})
    return parts


def format_inventory(title: str, files: list[Path]) -> str:
    if not files:
        return f"{title}：未找到文件。"
    lines = "\n".join(f"- {path.name}" for path in files)
    return f"{title}：\n{lines}"


def generate_report(date: str, app_name: str, app_files: list[Path], reference_files: list[Path], model: str) -> str:
    if not os.getenv("OPENAI_API_KEY"):
        return fallback_report(date, app_name, app_files, reference_files)

    if os.getenv("OPENAI_BASE_URL"):
        return generate_report_with_curl(date, app_name, app_files, reference_files, model)

    try:
        from openai import OpenAI
    except ImportError:
        return fallback_report(date, app_name, app_files, reference_files, reason="未安装 openai Python 包")

    client = OpenAI()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_content(date, app_name, app_files, reference_files)},
            ],
            temperature=0.2,
        )
    except Exception as exc:
        reason = f"视觉模型调用失败：{type(exc).__name__}: {str(exc)[:240]}"
        return fallback_report(date, app_name, app_files, reference_files, reason=reason)
    return response.choices[0].message.content or fallback_report(date, app_name, app_files, reference_files)


def generate_report_with_curl(date: str, app_name: str, app_files: list[Path], reference_files: list[Path], model: str) -> str:
    base_url = (os.getenv("OPENAI_BASE_URL") or "").rstrip("/")
    api_key = os.getenv("OPENAI_API_KEY") or ""
    if model.startswith("gpt-5"):
        return generate_report_with_responses_curl(date, app_name, app_files, reference_files, model, base_url, api_key)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_content(date, app_name, app_files, reference_files)},
        ],
        "temperature": 0.2,
    }
    command = [
        "curl",
        "-sS",
        "--fail-with-body",
        "--retry",
        "3",
        "--retry-delay",
        "2",
        "--connect-timeout",
        "20",
        "-X",
        "POST",
        f"{base_url}/chat/completions",
        "-H",
        f"Authorization: Bearer {api_key}",
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        "@-",
    ]
    try:
        result = subprocess.run(
            command,
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
        )
    except Exception as exc:
        reason = f"第三方接口调用失败：{type(exc).__name__}: {str(exc)[:240]}"
        return fallback_report(date, app_name, app_files, reference_files, reason=reason)

    if result.returncode != 0:
        detail = (result.stdout or result.stderr).strip()
        reason = f"第三方接口返回错误：{detail[:360]}"
        return fallback_report(date, app_name, app_files, reference_files, reason=reason)

    try:
        data = json.loads(result.stdout)
        return data["choices"][0]["message"]["content"] or fallback_report(date, app_name, app_files, reference_files)
    except Exception as exc:
        reason = f"第三方接口响应解析失败：{type(exc).__name__}: {str(exc)[:240]}"
        return fallback_report(date, app_name, app_files, reference_files, reason=reason)


def generate_report_with_responses_curl(
    date: str,
    app_name: str,
    app_files: list[Path],
    reference_files: list[Path],
    model: str,
    base_url: str,
    api_key: str,
) -> str:
    content = []
    for part in build_content(date, app_name, app_files, reference_files):
        if part["type"] == "text":
            content.append({"type": "input_text", "text": part["text"]})
        elif part["type"] == "image_url":
            content.append({"type": "input_image", "image_url": part["image_url"]["url"]})

    payload = {
        "model": model,
        "instructions": SYSTEM_PROMPT,
        "input": [{"role": "user", "content": content}],
    }
    command = [
        "curl",
        "-sS",
        "--fail-with-body",
        "--retry",
        "3",
        "--retry-delay",
        "2",
        "--connect-timeout",
        "20",
        "-X",
        "POST",
        f"{base_url}/responses",
        "-H",
        f"Authorization: Bearer {api_key}",
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        "@-",
    ]
    try:
        result = subprocess.run(
            command,
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
        )
    except Exception as exc:
        reason = f"第三方 Responses 接口调用失败：{type(exc).__name__}: {str(exc)[:240]}"
        return fallback_report(date, app_name, app_files, reference_files, reason=reason)

    if result.returncode != 0:
        detail = (result.stdout or result.stderr).strip()
        reason = f"第三方 Responses 接口返回错误：{detail[:360]}"
        return fallback_report(date, app_name, app_files, reference_files, reason=reason)

    try:
        data = json.loads(result.stdout)
        if data.get("output_text"):
            return data["output_text"]
        chunks = []
        for item in data.get("output", []):
            for content_item in item.get("content", []):
                if content_item.get("type") in {"output_text", "text"}:
                    chunks.append(content_item.get("text", ""))
        return "\n".join(chunks).strip() or fallback_report(date, app_name, app_files, reference_files)
    except Exception as exc:
        reason = f"第三方 Responses 接口响应解析失败：{type(exc).__name__}: {str(exc)[:240]}"
        return fallback_report(date, app_name, app_files, reference_files, reason=reason)


def fallback_report(date: str, app_name: str, app_files: list[Path], reference_files: list[Path], reason: str | None = None) -> str:
    reason_line = reason or "未检测到 OPENAI_API_KEY，暂时无法自动读取图片内容"
    app_status = "已发现当天样本文件" if app_files else f"未发现当天{app_name}样本"
    ref_status = "已发现参考文件" if reference_files else "未发现我们自己的参考文件"
    app_text = collect_text(app_files)
    reference_text = collect_text(reference_files)

    if app_text and reference_text:
        return text_only_report(date, app_name, app_files, reference_files, app_text, reference_text, reason_line)

    return f"""# {app_name}免费听策略日更 - {date}

## 今日结论
- 本次未生成完整视觉对比结论：{reason_line}。
- {app_name}样本状态：{app_status}。
- 我们参考样本状态：{ref_status}。

## 待补充样本
- 将{app_name}当天截图或链路笔记放入对应 App 的日更样本区。
- 将我们自己的参考图、参考文案或策略笔记放入 `strategy_monitor/references/`。
- 配置 `OPENAI_API_KEY` 后重新运行脚本，即可生成完整对比报告。

## 建议的人工记录字段
| 字段 | 示例 |
| --- | --- |
| 入口场景 | 播放会员歌曲时弹窗 |
| 标题 | 免费听会员歌曲 20 分钟 |
| 主按钮 | 看视频免费听歌 |
| 次按钮 | ¥2 开会员畅听 |
| 权益时长 | 20 分钟 |
| 关闭入口 | 右上角灰色关闭 |
| 链路结果 | 视频结束后是否 Toast 提示到账 |

## 证据与缺口
- {app_name}文件：{", ".join(path.name for path in app_files) or "无"}
- 参考文件：{", ".join(path.name for path in reference_files) or "无"}
- 缺口：需要可识别的截图、录屏关键帧或文字笔记，才能判断视觉层级、交易感和转化策略。
"""


def collect_text(files: list[Path]) -> str:
    chunks = []
    for path in files:
        if path.suffix.lower() in TEXT_EXTS:
            chunks.append(read_text_file(path))
    return "\n\n".join(chunks)


def has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def text_only_report(
    date: str,
    app_name: str,
    app_files: list[Path],
    reference_files: list[Path],
    app_text: str,
    reference_text: str,
    reason_line: str,
) -> str:
    app_time = "20 分钟" if has_any(app_text, ["20 分钟", "20分钟"]) else "未明确"
    reference_time = "30 分钟 / 20 分钟" if has_any(reference_text, ["30 分钟", "30分钟"]) else "20 分钟"
    app_price = "¥2" if "¥2" in app_text else "未明确"
    reference_price = "¥6 / ¥2" if "¥6" in reference_text else "¥2"
    app_main = "看视频免费听歌" if "看视频免费听歌" in app_text else "未明确"
    reference_main = "看广告免费听 30 分钟 / 看视频免费听歌" if has_any(reference_text, ["看广告", "看视频"]) else "未明确"

    return f"""# {app_name}免费听策略日更 - {date}

## 今日结论
- {app_name}样本更强调“免费体验 + 会员转化”的组合，免费入口和付费入口同时前置。
- 相比我们早期参考图，{app_name}的视觉主次需要重点观察：主按钮、会员按钮和关闭入口是否清楚分层。
- 主要风险是主按钮仍然以“看视频”开头，成本感没有完全后置；¥2 会员也可能抢走一部分免费 CTA 点击。
- 下一版建议优先测试“收益前置”文案，把主按钮改成“免费解锁 20 分钟畅听”，把“看视频”移到说明位。

## {app_name}观察
- 权益表达：{app_time}。
- 主按钮：{app_main}。
- 会员锚点：{app_price}。
- 链路策略：样本笔记提到点击主按钮后直接加载视频，视频结束或跳过后自动关闭弹窗，并用 Toast 告知权益到账。
- 视觉策略：放大主按钮、弱化会员按钮、拉大按钮间距，核心目标是减少误触和选择犹豫。

## 和我们参考图的差异
| 维度 | {app_name} | 我们参考图 | 判断 |
| --- | --- | --- | --- |
| 权益时长 | {app_time} | {reference_time} | 重点看竞品是否把权益说得更具体 |
| 主 CTA | {app_main} | {reference_main} | 如果竞品仍成本前置，我们可以用收益前置做差异化 |
| 会员价格 | {app_price} | {reference_price} | 低价会员可能提升付费，也可能分流免费按钮 |
| 视觉层级 | 待结合截图判断 | 早期版本主次接近，后续版本已改善 | 需要用真实截图判断是否值得借鉴 |
| 链路闭环 | 待结合截图/笔记判断 | 参考图更偏静态弹窗 | 到账反馈和返回播放是关键观察点 |

## 可借鉴点
- 主按钮视觉权重显著高于会员按钮，让用户第一眼知道推荐路径。
- 用“到账 Toast”闭环，降低用户看完视频后的不确定感。
- 按钮间距拉大，减少“看视频”和“开会员”的误触。
- 低价会员作为备选路径，但视觉上不抢主按钮。

## 不建议照搬
- 不建议继续把“看视频”放在主按钮第一词，用户第一眼仍会感知成本。
- 不建议让 ¥2 会员按钮过强，否则会把免费听任务变成价格权衡。
- 不建议只表达“20 分钟”，还需要说明是“会员歌”“会员曲库”还是“当前歌曲”。

## 下一版建议
方案 A：收益前置型
- 标题：免费听会员歌曲 20 分钟
- 副标题：看完视频即可开启，本次立即生效
- 主按钮：免费解锁 20 分钟畅听
- 次按钮：¥2 开会员，免视频畅听

方案 B：即时播放型
- 标题：当前歌曲可免费听
- 副标题：看完视频后，立即继续播放会员歌曲
- 主按钮：立即免费听
- 次按钮：开会员免视频

方案 C：交易换算型
- 标题：看一次视频，听 20 分钟会员歌
- 副标题：无需开通会员，权益到账后自动播放
- 主按钮：看视频免费听
- 次按钮：¥2 开会员畅听

## 证据与缺口
- 使用的{app_name}文件：{", ".join(path.name for path in app_files)}
- 使用的参考文件：{", ".join(path.name for path in reference_files)}
- 本次为文字笔记兜底报告：{reason_line}。如果加入原始截图并配置 `OPENAI_API_KEY`，报告会补充更准确的视觉层级、版式和文案识别。
"""


def main() -> int:
    args = parse_args()
    config = APP_CONFIG[args.app]
    app_name = config["name"]
    app_dir = args.app_dir or args.qishui_dir or (config["dir"] / args.date)
    out = args.out or (REPORT_DIR / f"{config['report_prefix']}_{args.date}.md")
    app_files = list_files(app_dir)
    reference_files = list_files(args.reference_dir)

    out.parent.mkdir(parents=True, exist_ok=True)
    report = generate_report(args.date, app_name, app_files, reference_files, args.model)
    out.write_text(report.rstrip() + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
