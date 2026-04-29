"""
storage/image_store.py · 可切换存储适配器
STORAGE_MODE=local    → 存到本地 data/images/
STORAGE_MODE=supabase → 上传到 Supabase Storage
"""
import hashlib
import io
import os
from pathlib import Path
from PIL import Image

_mode = "local"
_data_dir = None
_supabase_client = None
_supabase_bucket = "design-images"


def init_image_store(data_dir: Path):
    global _mode, _data_dir, _supabase_client, _supabase_bucket
    _data_dir = data_dir
    _mode = os.getenv("STORAGE_MODE", "local").strip().lower()

    for sub in ("dribbble", "behance", "xhs"):
        (data_dir / "images" / sub).mkdir(parents=True, exist_ok=True)

    if _mode == "supabase":
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_KEY", "")
        _supabase_bucket = os.getenv("SUPABASE_BUCKET", "design-images")
        if not url or not key:
            print("[image_store] 未设置 SUPABASE_URL/KEY，回退到 local")
            _mode = "local"
            return
        try:
            from supabase import create_client
            _supabase_client = create_client(url, key)
            print(f"[image_store] Supabase bucket={_supabase_bucket}")
        except Exception as e:
            print(f"[image_store] Supabase 初始化失败，回退 local: {e}")
            _mode = "local"
    else:
        print(f"[image_store] 本地存储: {data_dir / 'images'}")


def current_mode():
    return _mode


def compute_hash(image_bytes: bytes) -> str:
    return hashlib.md5(image_bytes).hexdigest()[:16]


def _compress(image_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img.thumbnail((600, 600), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=85, method=4)
    return buf.getvalue()


def _save_local(image_bytes: bytes, source: str, img_hash: str):
    rel = f"images/{source}/{img_hash}.webp"
    abs_path = _data_dir / rel
    if not abs_path.exists():
        try:
            abs_path.write_bytes(_compress(image_bytes))
        except Exception:
            rel = f"images/{source}/{img_hash}.png"
            (_data_dir / rel).write_bytes(image_bytes)
    return img_hash, rel


def _save_supabase(image_bytes: bytes, source: str, img_hash: str):
    storage_path = f"{source}/{img_hash}.webp"
    try:
        _supabase_client.storage.from_(_supabase_bucket).upload(
            path=storage_path,
            file=_compress(image_bytes),
            file_options={"content-type": "image/webp", "upsert": "false"},
        )
    except Exception as e:
        if "already exists" not in str(e).lower():
            raise
    public_url = (
        _supabase_client.storage.from_(_supabase_bucket).get_public_url(storage_path)
    )
    return img_hash, public_url


def save_image(image_bytes: bytes, source: str):
    img_hash = compute_hash(image_bytes)
    if _mode == "supabase" and _supabase_client:
        return _save_supabase(image_bytes, source, img_hash)
    return _save_local(image_bytes, source, img_hash)


def path_to_url(local_path: str) -> str:
    if local_path.startswith("http"):
        return local_path
    return "/" + local_path.replace("\\", "/").lstrip("/")
