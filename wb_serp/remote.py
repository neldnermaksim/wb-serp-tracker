"""Загрузка опубликованной базы для веб-интерфейса (Streamlit Cloud и т. п.)."""

from __future__ import annotations

import gzip
import json
import lzma
import os
import shutil
import sqlite3
import time
from pathlib import Path

import requests

from .storage import SCHEMA

XZ_MAGIC = b"\xfd7zXZ\x00"
GZ_MAGIC = b"\x1f\x8b"


def _unpack(src: Path, dst: Path) -> None:
    with open(src, "rb") as f:
        head = f.read(6)
    if head.startswith(XZ_MAGIC):
        opener = lzma.open
    elif head.startswith(GZ_MAGIC):
        opener = gzip.open
    else:
        shutil.copyfile(src, dst)
        return
    with opener(src, "rb") as f_in, open(dst, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


def fetch_db(url: str, target_dir: Path) -> Path:
    """Скачивает базу, если она изменилась (по ETag), и возвращает путь к файлу SQLite."""
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "serp.db"
    meta_path = target_dir / "serp.meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() and target.exists() else {}

    headers = {"User-Agent": "wb-serp-tracker"}
    if meta.get("url") == url and meta.get("etag"):
        headers["If-None-Match"] = meta["etag"]
    stamp = f"{os.getpid()}.{time.time_ns()}"
    raw, unpacked = target_dir / f"download.{stamp}", target_dir / f"serp.{stamp}.db"
    try:
        with requests.get(url, headers=headers, timeout=120, stream=True) as resp:
            if resp.status_code == 304:
                return target
            resp.raise_for_status()
            etag = resp.headers.get("ETag")
            with open(raw, "wb") as out:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    out.write(chunk)
        _unpack(raw, unpacked)
        conn = sqlite3.connect(unpacked)
        try:
            conn.executescript(SCHEMA)  # восстанавливает индексы, убранные при публикации
        finally:
            conn.close()
        os.replace(unpacked, target)
    finally:
        raw.unlink(missing_ok=True)
        unpacked.unlink(missing_ok=True)
    meta_path.write_text(json.dumps({"url": url, "etag": etag, "fetched_at": time.time()}))
    return target
