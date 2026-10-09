"""
文件处理工具
============
负责上传文件的校验、持久化、解析结果 JSON 的读写，以及文档库索引管理。
文档库索引用一个 documents_index.json 记录所有已解析文档的元信息与产物路径。
"""
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.core.exceptions import FileValidationError
from app.core.logging import logger

settings = get_settings()

# 解析产物根目录（相对 UPLOAD_DIR 的同级 data 目录）
DATA_ROOT = Path(settings.UPLOAD_DIR).parent
PARSED_DIR = DATA_ROOT / "parsed"
FIGURE_DIR = Path(settings.FIGURE_DIR)
DOCS_INDEX_PATH = DATA_ROOT / "documents_index.json"


def ensure_dirs() -> None:
    """确保所有需要的目录存在。容器启动时调用。"""
    for p in (settings.UPLOAD_DIR, settings.VECTOR_STORE_PATH, str(PARSED_DIR), str(FIGURE_DIR)):
        try:
            Path(p).mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # 权限/挂载问题
            logger.warning("创建目录 %s 失败: %s", p, exc)


def save_figure_image(doc_id: str, index: int, image_bytes: bytes, ext: str = "png") -> str:
    """保存从 PDF 提取的图表图片，返回可访问的相对 URL。

    Args:
        doc_id: 文档 ID
        index: 图片序号（从 0 开始）
        image_bytes: 图片二进制数据
        ext: 图片扩展名（png/jpg）

    Returns:
        相对 URL，如 /static/figures/{doc_id}_{index}.png
    """
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{doc_id}_{index}.{ext}"
    filepath = FIGURE_DIR / filename
    filepath.write_bytes(image_bytes)
    return f"{settings.STATIC_URL_PREFIX}/figures/{filename}"


def utc_now_iso() -> str:
    """返回当前 UTC 时间 ISO8601 字符串。"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_upload_file(filename: str, size: int) -> None:
    """校验上传文件的扩展名与大小。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in settings.allowed_ext_list:
        raise FileValidationError(
            f"不支持的文件类型: .{ext}，仅支持 {settings.allowed_ext_list}"
        )
    if size > settings.MAX_UPLOAD_SIZE:
        raise FileValidationError(
            f"文件过大: {size} 字节，上限 {settings.MAX_UPLOAD_SIZE} 字节"
        )


def save_upload_file(content: bytes, filename: str) -> str:
    """把上传字节流保存到 UPLOAD_DIR，返回 document_id。"""
    doc_id = str(uuid.uuid4())
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    saved_path = Path(settings.UPLOAD_DIR) / f"{doc_id}.{ext}"
    saved_path.write_bytes(content)
    logger.info("文件已保存: %s (doc_id=%s)", saved_path, doc_id)
    return doc_id


def get_upload_path(doc_id: str) -> Optional[Path]:
    """根据 document_id 找到原始上传文件。"""
    for ext in settings.allowed_ext_list:
        p = Path(settings.UPLOAD_DIR) / f"{doc_id}.{ext}"
        if p.exists():
            return p
    return None


def parsed_result_path(doc_id: str) -> Path:
    """解析结果 JSON 路径。"""
    return PARSED_DIR / f"{doc_id}.json"


def save_parsed_result(doc_id: str, result: Dict[str, Any]) -> Path:
    """把解析结果序列化为 JSON 落盘。"""
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    path = parsed_result_path(doc_id)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def load_parsed_result(doc_id: str) -> Optional[Dict[str, Any]]:
    """读取解析结果 JSON。"""
    path = parsed_result_path(doc_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("读取解析结果失败 %s: %s", path, exc)
        return None


# ---------- 文档索引（轻量元信息持久化） ----------

def _read_index() -> List[Dict[str, Any]]:
    if not DOCS_INDEX_PATH.exists():
        return []
    try:
        return json.loads(DOCS_INDEX_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _write_index(index: List[Dict[str, Any]]) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    DOCS_INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def upsert_document_index(
    doc_id: str,
    filename: str,
    title: Optional[str],
    status: str,
    uploaded_at: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> None:
    """新增或更新文档索引条目。

    Args:
        doc_id: 文档 ID
        filename: 原始文件名
        title: 解析出的标题（上传阶段为 None）
        status: parsing|completed|failed
        uploaded_at: 上传时间（缺省当前 UTC 时间）
        tags: 标签列表。仅在显式传入时覆盖；已存在条目未传 tags 时保留原标签。
    """
    index = _read_index()
    now = uploaded_at or utc_now_iso()
    entry = {
        "document_id": doc_id,
        "filename": filename,
        "title": title,
        "status": status,
        "uploaded_at": now,
        "tags": tags if tags is not None else [],
    }
    replaced = False
    for i, item in enumerate(index):
        if item.get("document_id") == doc_id:
            # 保留已有 uploaded_at
            entry["uploaded_at"] = item.get("uploaded_at", now)
            # 保留已有标签（未显式传入新标签时）
            entry["tags"] = tags if tags is not None else item.get("tags", [])
            index[i] = entry
            replaced = True
            break
    if not replaced:
        index.append(entry)
    _write_index(index)


def list_documents_index() -> List[Dict[str, Any]]:
    return _read_index()


def get_document_index(doc_id: str) -> Optional[Dict[str, Any]]:
    for item in _read_index():
        if item.get("document_id") == doc_id:
            return item
    return None


def update_document_tags(doc_id: str, tags: List[str]) -> bool:
    """更新指定文档的标签。返回是否找到该文档。"""
    index = _read_index()
    for i, item in enumerate(index):
        if item.get("document_id") == doc_id:
            item["tags"] = list(tags or [])
            index[i] = item
            _write_index(index)
            logger.info("文档 %s 标签已更新: %s", doc_id, tags)
            return True
    return False


def search_documents(keyword: str, tag: Optional[str] = None) -> List[Dict[str, Any]]:
    """按关键词 + 标签搜索文档索引。

    - keyword 大小写不敏感，匹配 title / filename；若索引条目里带作者字段
      （authors 或 metadata.authors）也一并匹配（向后兼容，索引当前默认不含作者）。
    - tag 精确过滤：文档标签列表中必须包含该 tag。
    """
    kw = (keyword or "").strip().lower()
    results: List[Dict[str, Any]] = []
    for item in _read_index():
        # 标签精确过滤
        if tag:
            item_tags = item.get("tags", []) or []
            if tag not in item_tags:
                continue
        if not kw:
            results.append(item)
            continue
        # 关键词匹配 title / filename
        title = str(item.get("title") or "").lower()
        filename = str(item.get("filename") or "").lower()
        hit = kw in title or kw in filename
        # 兼容：索引条目里若带作者信息也参与匹配
        if not hit:
            authors = item.get("authors") or (item.get("metadata") or {}).get("authors") or []
            if isinstance(authors, list):
                hit = any(kw in str(a).lower() for a in authors)
        if hit:
            results.append(item)
    return results


def remove_document_index(doc_id: str) -> None:
    index = [i for i in _read_index() if i.get("document_id") != doc_id]
    _write_index(index)
    # 同时删除原始文件与解析结果
    src = get_upload_path(doc_id)
    if src and src.exists():
        try:
            src.unlink()
        except OSError as exc:
            logger.warning("删除原始文件失败 %s: %s", src, exc)
    pr = parsed_result_path(doc_id)
    if pr.exists():
        try:
            pr.unlink()
        except OSError as exc:
            logger.warning("删除解析结果失败 %s: %s", pr, exc)


# ---------- 通用：安全文件名 / slug ----------

def safe_filename(name: str) -> str:
    """去掉文件名中的不安全字符。"""
    return re.sub(r"[^\w\-.]", "_", name)
