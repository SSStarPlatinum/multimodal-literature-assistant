"""
向量嵌入与索引服务
==================
基于 BGE-M3 嵌入 + Chroma 持久化向量库，维护两层索引：
1. summary 层：每篇文献一条记录，向量 = 结构化摘要拼接文本。
2. fulltext 层：把全文按 chunk_size 切分后的多条记录，带 document_id / page 元数据。

同时提供 LlamaIndex 风格的节点切分（SentenceSplitter）。
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import get_settings
from app.core.exceptions import VectorStoreError
from app.core.logging import logger
from app.services.model_loader import model_loader

settings = get_settings()


class VectorService:
    """两层向量索引服务。"""

    def __init__(self) -> None:
        self._client = None
        self._summary_coll = None
        self._fulltext_coll = None

    # ---------- 初始化 Chroma ----------
    def _ensure_collections(self):
        if self._summary_coll is not None and self._fulltext_coll is not None:
            return
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except ImportError as exc:  # pragma: no cover
            raise VectorStoreError("未安装 chromadb") from exc

        self._client = chromadb.PersistentClient(
            path=settings.VECTOR_STORE_PATH,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._summary_coll = self._client.get_or_create_collection(
            name=f"{settings.VECTOR_COLLECTION_NAME}_summary",
            metadata={"hnsw:space": "cosine"},
        )
        self._fulltext_coll = self._client.get_or_create_collection(
            name=settings.VECTOR_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "Chroma 向量库就绪: summary=%d chunks, fulltext=%d chunks",
            self._summary_coll.count(),
            self._fulltext_coll.count(),
        )

    # ---------- 文档切分 ----------
    def _split_into_parts(self, text: str) -> List[str]:
        """把一段文本切成若干 chunk 字符串。

        优先用 LlamaIndex SentenceSplitter；不可用时退化为按字符滑窗。
        """
        if not text:
            return []
        try:
            from llama_index.core.node_parser import SentenceSplitter

            splitter = SentenceSplitter(
                chunk_size=settings.CHUNK_SIZE,
                chunk_overlap=settings.CHUNK_OVERLAP,
            )
            return splitter.split_text(text)
        except Exception:  # noqa: BLE001
            # 退化：按字符滑窗
            parts: List[str] = []
            step = max(1, settings.CHUNK_SIZE - settings.CHUNK_OVERLAP)
            for i in range(0, len(text), step):
                parts.append(text[i : i + settings.CHUNK_SIZE])
            return parts

    def _split_text(
        self,
        text: str,
        text_blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """切分文本为 chunks，每个 chunk 携带溯源元数据。

        Args:
            text: 全文（当 text_blocks 为空时用于滑窗切分）。
            text_blocks: parser_service 产出的结构化块
                ``[{"page": int, "type": "text", "content": str}, ...]``。
                提供时按段落块逐块切分，每个 chunk 记录真实页码 / 段落序号 / 字符偏移；
                为空时回退到全文滑窗切分（page=0），保持旧行为。

        Returns:
            chunk 列表，每项含 chunk_id/text/tokens，块模式下额外含
            page/paragraph_index/char_offset。
        """
        # ---- 有结构化块：按段落逐块切分，记录页码与偏移 ----
        if text_blocks:
            return self._split_text_by_blocks(text_blocks)

        # ---- 回退：全文滑窗（page=0） ----
        chunks: List[Dict[str, Any]] = []
        node_texts = self._split_into_parts(text)
        for idx, ct in enumerate(node_texts):
            ct = ct.strip()
            if not ct:
                continue
            chunks.append(
                {
                    "chunk_id": f"chunk-{idx}",
                    "text": ct,
                    "tokens": len(ct),
                    "page": 0,
                    "paragraph_index": 0,
                    "char_offset": 0,
                }
            )
        return chunks

    def _split_text_by_blocks(
        self, text_blocks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """按结构化文本块逐块切分，为每个 chunk 记录页码/段落序号/字符偏移。

        char_offset 以「各块 content 用 "\\n\\n" 连接后的全文」为基准累计，
        保证后续可凭偏移在重建全文中定位到 chunk 原文。
        """
        chunks: List[Dict[str, Any]] = []
        char_offset = 0       # 在重建全文中的累计起始字符位置
        paragraph_index = 0   # 段落序号（只统计正文文本块）

        for block in text_blocks:
            # 只切正文文本块，跳过图片等非文本块
            if block.get("type") != "text":
                continue
            content = (block.get("content") or "").strip()
            if not content:
                continue
            page_no = block.get("page", 0)

            # 对该段落内容做 chunk 切分
            parts = self._split_into_parts(content)
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                chunks.append(
                    {
                        "chunk_id": f"chunk-{len(chunks)}",
                        "text": part,
                        "tokens": len(part),
                        "page": page_no,
                        "paragraph_index": paragraph_index,
                        "char_offset": char_offset,
                    }
                )
                # 推进偏移：加上本 chunk 字符数
                char_offset += len(part)
            # 段落之间以 "\n\n" 连接，推进 2 个字符
            char_offset += 2
            paragraph_index += 1

        return chunks

    # ---------- 写入 ----------
    def index_document(
        self,
        doc_id: str,
        filename: str,
        full_text: str,
        structured_summary: Optional[Dict[str, str]] = None,
        text_blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, int]:
        """把一篇文献写入两层索引。返回写入条数统计。

        Args:
            text_blocks: parser_service 产出的结构化文本块（带页码）。
                提供时按块切分并记录 page/paragraph_index/char_offset；
                为空时回退到全文滑窗切分（page=0）。
        """
        self._ensure_collections()
        structured_summary = structured_summary or {}

        # 1) summary 层
        summary_text = "。".join(
            filter(
                None,
                [
                    f"目的: {structured_summary.get('purpose', '')}",
                    f"方法: {structured_summary.get('methods', '')}",
                    f"数据: {structured_summary.get('data', '')}",
                    f"结论: {structured_summary.get('conclusion', '')}",
                ],
            )
        )
        if not summary_text:
            summary_text = full_text[:1000]
        sum_emb = model_loader.embed_texts([summary_text])[0]
        self._upsert_summary(doc_id, filename, summary_text, sum_emb)

        # 2) fulltext 层（按结构化块切分，携带页码/段落/偏移元数据）
        chunks = self._split_text(full_text, text_blocks=text_blocks)
        n_chunks = 0
        batch_texts = [c["text"] for c in chunks]
        if batch_texts:
            embs = model_loader.embed_texts(batch_texts)
            ids = [f"{doc_id}_{c['chunk_id']}" for c in chunks]
            # Chroma metadata 只接受 str/int/float/bool 等原始类型
            metas = [
                {
                    "document_id": doc_id,
                    "filename": filename,
                    "chunk_id": c["chunk_id"],
                    "page": c.get("page", 0),
                    "paragraph_index": c.get("paragraph_index", 0),
                    "char_offset": c.get("char_offset", 0),
                }
                for c in chunks
            ]
            self._fulltext_coll.upsert(
                ids=ids, embeddings=embs, documents=batch_texts, metadatas=metas
            )
            n_chunks = len(chunks)

        logger.info("文档 %s 索引完成: summary=1, chunks=%d", doc_id, n_chunks)
        return {"summary": 1, "chunks": n_chunks}

    def _upsert_summary(
        self, doc_id: str, filename: str, text: str, embedding: List[float]
    ) -> None:
        self._summary_coll.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{"document_id": doc_id, "filename": filename}],
        )

    # ---------- 检索 ----------
    def search_summary(
        self, query: str, doc_ids: Optional[List[str]] = None, top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """第一层：摘要粗检索，返回命中的 document_id 列表。"""
        self._ensure_collections()
        q_emb = model_loader.embed_query(query)
        where = self._build_where(doc_ids)
        res = self._summary_coll.query(
            query_embeddings=[q_emb],
            n_results=top_k,
            where=where,
        )
        hits: List[Dict[str, Any]] = []
        ids = res.get("ids", [[]])[0]
        dists = res.get("distances", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        for did, dist, text, meta in zip(ids, dists, docs, metas):
            hits.append(
                {
                    "document_id": did,
                    "filename": (meta or {}).get("filename", ""),
                    "text": text,
                    "score": 1.0 - float(dist),  # cosine distance -> similarity
                    "retrieval_layer": "summary",
                }
            )
        return hits

    def search_fulltext(
        self,
        query: str,
        doc_ids: Optional[List[str]] = None,
        top_k: int = 8,
    ) -> List[Dict[str, Any]]:
        """第二层：全文 chunk 细检索。"""
        self._ensure_collections()
        q_emb = model_loader.embed_query(query)
        where = self._build_where(doc_ids)
        res = self._fulltext_coll.query(
            query_embeddings=[q_emb],
            n_results=top_k,
            where=where,
        )
        hits: List[Dict[str, Any]] = []
        ids = res.get("ids", [[]])[0]
        dists = res.get("distances", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        for cid, dist, text, meta in zip(ids, dists, docs, metas):
            meta = meta or {}
            hits.append(
                {
                    "chunk_id": cid,
                    "document_id": meta.get("document_id", ""),
                    "filename": meta.get("filename", ""),
                    "text": text,
                    "page": meta.get("page", 0),
                    "paragraph_index": meta.get("paragraph_index", 0),
                    "char_offset": meta.get("char_offset", 0),
                    "score": 1.0 - float(dist),
                    "retrieval_layer": "fulltext",
                }
            )
        return hits

    def get_chunk_by_id(self, doc_id: str, chunk_id: str) -> Optional[Dict[str, Any]]:
        """按 ``{doc_id}_{chunk_id}`` 从 fulltext collection 取单个 chunk 详情。

        Returns:
            命中返回 {document_id, chunk_id, text, page, paragraph_index,
            char_offset, filename}；不存在返回 None。
        """
        self._ensure_collections()
        full_id = f"{doc_id}_{chunk_id}"
        try:
            res = self._fulltext_coll.get(
                ids=[full_id],
                include=["documents", "metadatas"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("查询 chunk 详情失败 %s: %s", full_id, exc)
            return None
        ids = res.get("ids", []) or []
        if not ids:
            return None
        doc_text = (res.get("documents") or [""])[0] or ""
        meta = (res.get("metadatas") or [{}])[0] or {}
        return {
            "document_id": meta.get("document_id", doc_id),
            "chunk_id": chunk_id,
            "text": doc_text,
            "page": meta.get("page", 0),
            "paragraph_index": meta.get("paragraph_index", 0),
            "char_offset": meta.get("char_offset", 0),
            "filename": meta.get("filename", ""),
        }

    @staticmethod
    def _build_where(doc_ids: Optional[List[str]]) -> Optional[Dict[str, Any]]:
        """构造 chroma where 过滤：限定 document_id 集合。"""
        if not doc_ids:
            return None
        if len(doc_ids) == 1:
            return {"document_id": {"$eq": doc_ids[0]}}
        return {"document_id": {"$in": doc_ids}}

    # ---------- 删除 ----------
    def delete_document(self, doc_id: str) -> None:
        self._ensure_collections()
        try:
            self._summary_coll.delete(ids=[doc_id])
            # fulltext 用 where 批量删
            self._fulltext_coll.delete(where={"document_id": {"$eq": doc_id}})
            logger.info("已从向量库删除文档 %s", doc_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除向量库文档失败 %s: %s", doc_id, exc)

    def stats(self) -> Dict[str, int]:
        self._ensure_collections()
        return {
            "summary_docs": self._summary_coll.count(),
            "chunks": self._fulltext_coll.count(),
        }


vector_service = VectorService()
