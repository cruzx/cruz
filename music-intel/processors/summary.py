"""
processors/summary.py · 总体情报总结
"""
import json

from processors.claude_analyzer import analyze_overall
from storage import db


async def generate_overall_summary() -> dict:
    images = await db.query_images(limit=120)
    features = await db.query_features(limit=120)
    content = analyze_overall(images, features)
    title = "产品情报总体总结"
    payload = {
        "image_count": len(images),
        "feature_count": len(features),
        "image_sources": sorted({i.get("source", "") for i in images if i.get("source")}),
        "feature_sources": sorted({i.get("platform", "") for i in features if i.get("platform")}),
    }
    await db.insert_report({
        "report_type": "overall",
        "title": title,
        "content": content,
        "raw_payload": json.dumps(payload, ensure_ascii=False),
    })
    report = await db.latest_report("overall")
    return report or {"title": title, "content": content, "raw_payload": json.dumps(payload, ensure_ascii=False)}
