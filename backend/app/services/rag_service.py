"""
RAG 分层检索问答服务
====================
三层策略：
1. summary 层：对文献结构化摘要做粗检索，先圈定相关文献集合。
2. fulltext 层：在命中文献范围内做 chunk 级细检索。
3. rerank 层：bge-reranker 对合并结果重排序，取 top_n。

支持 summary / fulltext / hybrid 三种模式，hybrid 合并两层结果后重排序。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.core.logging import logger
from app.schemas.qa import (
    CompareItem,
    CompareResponse,
    ComparisonResult,
    QAResponse,
    RetrievalInfo,
    SourceItem,
)
from app.services.model_loader import model_loader
from app.services.vector_service import vector_service
from app.utils import prompts

settings = get_settings()


class RAGService:
    """分层 RAG 问答。"""

    def ask(
        self,
        question: str,
        document_ids: Optional[List[str]] = None,
        mode: str = "hybrid",
        top_k: int = 5,
        include_citations: bool = True,
    ) -> QAResponse:
        """执行一次完整的分层检索 + 生成。"""
        t0 = time.time()
        document_ids = document_ids or []

        summary_hits: List[Dict[str, Any]] = []
        fulltext_hits: List[Dict[str, Any]] = []

        # ---- 第一层：摘要粗检索 ----
        if mode in ("summary", "hybrid"):
            summary_hits = vector_service.search_summary(
                question, doc_ids=document_ids, top_k=settings.RAG_SUMMARY_TOP_K
            )
            logger.info("[RAG] summary 层命中 %d 篇", len(summary_hits))

        # ---- 第二层：全文细检索 ----
        if mode in ("fulltext", "hybrid"):
            # hybrid 模式下，把 summary 命中的文献作为 fulltext 的候选范围交集
            ft_scope: Optional[List[str]] = document_ids
            if mode == "hybrid" and summary_hits:
                summary_doc_ids = [h["document_id"] for h in summary_hits]
                # 若用户已限定 doc_ids，则取交集
                if document_ids:
                    ft_scope = [d for d in summary_doc_ids if d in document_ids]
                else:
                    ft_scope = summary_doc_ids
            fulltext_hits = vector_service.search_fulltext(
                question, doc_ids=ft_scope, top_k=settings.RAG_FULLTEXT_TOP_K
            )
            logger.info("[RAG] fulltext 层命中 %d chunks", len(fulltext_hits))

        # ---- 合并 + 重排序 ----
        merged = self._merge_hits(summary_hits, fulltext_hits, mode)
        reranked = False
        if settings.RAG_ENABLE_RERANK and merged:
            merged = self._rerank_hits(question, merged, top_n=settings.RERANK_TOP_N)
            reranked = True

        final = merged[:top_k]

        # ---- 生成答案 ----
        answer = self._generate_answer(question, final, include_citations)

        latency_ms = int((time.time() - t0) * 1000)
        sources = [
            SourceItem(
                document_id=h.get("document_id", ""),
                filename=h.get("filename", ""),
                chunk_id=h.get("chunk_id", "summary"),
                text=h.get("text", ""),
                page=h.get("page"),
                paragraph_index=h.get("paragraph_index"),
                char_offset=h.get("char_offset"),
                score=round(h.get("score", 0.0), 4),
                retrieval_layer=h.get("retrieval_layer", "fulltext"),
            )
            for h in final
        ]
        return QAResponse(
            answer=answer,
            sources=sources,
            retrieval_info=RetrievalInfo(
                mode=mode,
                summary_hits=len(summary_hits),
                fulltext_hits=len(fulltext_hits),
                reranked=reranked,
                latency_ms=latency_ms,
            ),
        )

    def _merge_hits(
        self,
        summary_hits: List[Dict[str, Any]],
        fulltext_hits: List[Dict[str, Any]],
        mode: str,
    ) -> List[Dict[str, Any]]:
        """合并两层结果：summary 层把整篇摘要作为一条召回；fulltext 给 chunk。"""
        merged: List[Dict[str, Any]] = []
        if mode == "summary":
            # 摘要层直接作为上下文
            for h in summary_hits:
                merged.append({**h, "chunk_id": "summary"})
        elif mode == "fulltext":
            merged.extend(fulltext_hits)
        else:  # hybrid
            # 摘要命中的整篇摘要作为一条粗召回，fulltext 作为细召回
            for h in summary_hits:
                merged.append({**h, "chunk_id": "summary"})
            merged.extend(fulltext_hits)

        # 按 chunk_id 去重
        seen = set()
        deduped: List[Dict[str, Any]] = []
        for h in merged:
            key = h.get("chunk_id") or h.get("document_id")
            if key in seen:
                continue
            seen.add(key)
            deduped.append(h)
        return deduped

    def _rerank_hits(
        self, query: str, hits: List[Dict[str, Any]], top_n: int
    ) -> List[Dict[str, Any]]:
        """用 bge-reranker 重排。"""
        try:
            texts = [h["text"] for h in hits]
            ranked = model_loader.rerank(query, texts, top_n=top_n)
            return [hits[i] for i, _ in ranked]
        except Exception as exc:  # noqa: BLE001
            logger.warning("重排序失败，退回向量相似度排序: %s", exc)
            return sorted(hits, key=lambda x: x.get("score", 0.0), reverse=True)[:top_n]

    def _generate_answer(
        self, question: str, hits: List[Dict[str, Any]], include_citations: bool
    ) -> str:
        """基于召回片段生成答案。"""
        if not hits:
            return "未检索到相关文献片段，请先上传文献或扩大检索范围。"
        context_parts = []
        for i, h in enumerate(hits, start=1):
            layer = h.get("retrieval_layer", "fulltext")
            tag = "摘要" if layer == "summary" else "正文片段"
            context_parts.append(
                f"[{i}] ({tag} | {h.get('filename', '')})\n{h.get('text', '')}"
            )
        context = "\n\n".join(context_parts)
        prompt = prompts.QA_USER_TEMPLATE.format(question=question, context=context)
        try:
            answer = model_loader.chat_text(prompts.QA_SYSTEM, prompt)
            if not include_citations:
                # 去掉 [n] 标记
                import re

                answer = re.sub(r"\[\d+\]", "", answer)
            return answer.strip()
        except Exception as exc:  # noqa: BLE001
            logger.exception("答案生成失败")
            return f"答案生成失败: {exc}"

    # ---------- 文献对比 ----------
    def compare(
        self, document_ids: List[str], dimension: str, titles: Optional[Dict[str, str]] = None
    ) -> CompareResponse:
        """按维度对比多篇文献。"""
        titles = titles or {}
        # 对每篇文献在指定维度上做定向摘要检索
        per_doc_info: List[str] = []
        for doc_id in document_ids:
            # 用维度关键词作为 query 召回该文献的相关片段
            hits = vector_service.search_fulltext(
                query=f"{dimension}",
                doc_ids=[doc_id],
                top_k=3,
            )
            snippet = "\n".join(h["text"][:600] for h in hits) or "（无相关片段）"
            per_doc_info.append(
                f"- doc_id={doc_id} 标题={titles.get(doc_id, '未知')}\n{snippet}"
            )
        user_prompt = prompts.COMPARE_USER_TEMPLATE.format(
            dimension=dimension,
            dimension_desc=prompts.COMPARE_DIMENSION_DESC.get(dimension, ""),
            per_doc_info="\n\n".join(per_doc_info),
        )
        try:
            raw = model_loader.chat_text(prompts.COMPARE_SYSTEM, user_prompt)
            parsed = self._safe_json(raw)
        except Exception as exc:  # noqa: BLE001
            logger.exception("对比生成失败")
            parsed = {}

        items = [
            CompareItem(
                document_id=it.get("document_id", ""),
                title=it.get("title"),
                content=it.get("content", ""),
            )
            for it in parsed.get("items", [])
        ]
        return CompareResponse(
            comparison=ComparisonResult(
                dimension=dimension,
                items=items,
                similarities=parsed.get("similarities", []),
                differences=parsed.get("differences", []),
            )
        )

    @staticmethod
    def _safe_json(text: str) -> Dict[str, Any]:
        import json
        import re

        if not text:
            return {}
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            cleaned = cleaned[start : end + 1]
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}


rag_service = RAGService()
