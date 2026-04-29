"""
storage/db.py · SQLite 数据库层
使用 aiosqlite 异步操作，数据存本地 data/intel.db
"""
import aiosqlite
import hashlib
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

DB_PATH: Path = None  # 由 init_db() 设置


async def init_db(data_dir: Path):
    global DB_PATH
    DB_PATH = data_dir / "intel.db"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS design_images (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source       TEXT NOT NULL,        -- 'dribbble'|'behance'|'xhs'
            source_id    TEXT,                 -- 原平台 ID
            source_url   TEXT,                 -- 原始链接
            local_path   TEXT NOT NULL,        -- 本地图片路径
            title        TEXT,
            author       TEXT,
            tags         TEXT,                 -- JSON array string
            likes        INTEGER DEFAULT 0,
            views        INTEGER DEFAULT 0,
            img_hash     TEXT UNIQUE,          -- MD5，去重用
            ai_style_tags    TEXT,             -- JSON array
            ai_color_palette TEXT,             -- JSON array  
            ai_layout        TEXT,
            ai_key_elements  TEXT,             -- JSON array
            ai_reference     TEXT,             -- high/mid/low
            ai_notes         TEXT,
            collected_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS feature_intel (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            platform     TEXT NOT NULL,
            source_type  TEXT,
            title        TEXT,
            summary      TEXT,
            category     TEXT,
            impact       TEXT,
            raw_content  TEXT,
            source_url   TEXT,
            published_at TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS intel_reports (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            report_type  TEXT NOT NULL,
            title        TEXT,
            content      TEXT NOT NULL,
            raw_payload  TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_images_source ON design_images(source);
        CREATE INDEX IF NOT EXISTS idx_images_collected ON design_images(collected_at);
        CREATE INDEX IF NOT EXISTS idx_images_ref ON design_images(ai_reference);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_feature_url ON feature_intel(source_url);
        CREATE INDEX IF NOT EXISTS idx_feature_created ON feature_intel(created_at);
        CREATE INDEX IF NOT EXISTS idx_reports_created ON intel_reports(created_at);
        """)
        await db.commit()


async def image_exists(img_hash: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM design_images WHERE img_hash = ?", (img_hash,)
        ) as cur:
            return await cur.fetchone() is not None


async def insert_image(record: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT OR IGNORE INTO design_images
            (source, source_id, source_url, local_path, title, author,
             tags, likes, views, img_hash,
             ai_style_tags, ai_color_palette, ai_layout,
             ai_key_elements, ai_reference, ai_notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            record.get("source"),
            record.get("source_id"),
            record.get("source_url"),
            record.get("local_path"),
            record.get("title"),
            record.get("author"),
            json.dumps(record.get("tags", []), ensure_ascii=False),
            record.get("likes", 0),
            record.get("views", 0),
            record.get("img_hash"),
            json.dumps(record.get("ai_style_tags", []), ensure_ascii=False),
            json.dumps(record.get("ai_color_palette", []), ensure_ascii=False),
            record.get("ai_layout"),
            json.dumps(record.get("ai_key_elements", []), ensure_ascii=False),
            record.get("ai_reference"),
            record.get("ai_notes"),
        ))
        await db.commit()
        return cur.lastrowid


async def query_images(
    source: Optional[str] = None,
    reference: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    clauses, params = [], []
    if source and source != "all":
        clauses.append("source = ?")
        params.append(source)
    else:
        clauses.append("source != ?")
        params.append("xhs")
    if reference and reference != "all":
        clauses.append("ai_reference = ?")
        params.append(reference)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params += [limit, offset]

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""SELECT * FROM design_images
                {where}
                ORDER BY collected_at DESC
                LIMIT ? OFFSET ?""",
            params,
        ) as cur:
            rows = await cur.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                for f in ("tags", "ai_style_tags", "ai_color_palette", "ai_key_elements"):
                    try:
                        d[f] = json.loads(d[f] or "[]")
                    except Exception:
                        d[f] = []
                result.append(d)
            return result


async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM design_images WHERE source != 'xhs'") as c:
            total = (await c.fetchone())[0]
        async with db.execute(
            "SELECT source, COUNT(*) FROM design_images WHERE source != 'xhs' GROUP BY source"
        ) as c:
            by_source = dict(await c.fetchall())
        async with db.execute(
            "SELECT ai_reference, COUNT(*) FROM design_images WHERE source != 'xhs' AND ai_reference IS NOT NULL GROUP BY ai_reference"
        ) as c:
            by_ref = dict(await c.fetchall())
        async with db.execute("SELECT COUNT(*) FROM feature_intel") as c:
            feature_total = (await c.fetchone())[0]
    return {"total": total, "by_source": by_source, "by_reference": by_ref, "feature_total": feature_total}


async def insert_feature(record: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT OR IGNORE INTO feature_intel
            (platform, source_type, title, summary, category, impact,
             raw_content, source_url, published_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            record.get("platform"),
            record.get("source_type"),
            record.get("title"),
            record.get("summary"),
            record.get("category"),
            record.get("impact"),
            record.get("raw_content"),
            record.get("source_url"),
            record.get("published_at"),
        ))
        await db.commit()
        return cur.lastrowid


async def query_features(limit: int = 80, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM feature_intel
               ORDER BY COALESCE(published_at, created_at) DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def insert_report(record: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO intel_reports (report_type, title, content, raw_payload)
            VALUES (?,?,?,?)
        """, (
            record.get("report_type", "overall"),
            record.get("title"),
            record.get("content"),
            record.get("raw_payload"),
        ))
        await db.commit()
        return cur.lastrowid


async def latest_report(report_type: str = "overall") -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM intel_reports
               WHERE report_type = ?
               ORDER BY created_at DESC, id DESC
               LIMIT 1""",
            (report_type,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
