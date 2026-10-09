"""
综述生成服务
============
- 基于多篇文献的结构化摘要 + 全文片段，生成综述大纲。
- 汇总核心观点（每条标注支撑文献）。
- 研究缺口分析（按严重程度分级 high/medium/low）。
- 研究发展脉络时间线。
- 结果持久化到 data/reviews/。
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import get_settings
from app.core.exceptions import ReviewNotFoundError
from app.core.logging import logger
from app.schemas.review import (
    CoreView,
    EvolutionEvent,
    OutlineSection,
    ResearchGap,
    ReviewResponse,
)
from app.services.model_loader import model_loader
from app.utils import prompts
from app.utils.file_utils import ensure_dirs, load_parsed_result, safe_filename

settings = get_settings()

REVIEWS_DIR = Path(settings.UPLOAD_DIR).parent / "reviews"


class ReviewService:
    """综述生成服务。"""

    def _ensure_dir(self) -> None:
        ensure_dirs()
        REVIEWS_DIR.mkdir(parents=True, exist_ok=True)

    def generate_review(
        self,
        document_ids: List[str],
        topic: str,
        sections: List[str],
        parsed_docs: Dict[str, Dict[str, Any]],
    ) -> ReviewResponse:
        """生成综述并持久化。"""
        self._ensure_dir()
        review_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        # 准备文献摘要上下文
        doc_summaries = self._build_doc_summaries(document_ids, parsed_docs)

        # 1) 大纲
        outline = self._build_outline(topic, sections, doc_summaries)

        # 2) 核心观点 / 缺口 / 时间线
        views, gaps, timeline = self._build_views_gaps_timeline(topic, doc_summaries)

        review = ReviewResponse(
            review_id=review_id,
            title=topic,
            outline=outline,
            core_views=views,
            research_gaps=gaps,
            evolution_timeline=timeline,
            created_at=created_at,
        )
        self._save(review)
        logger.info("综述 %s 生成完成: %s", review_id, topic)
        return review

    def _build_doc_summaries(
        self,
        document_ids: List[str],
        parsed_docs: Dict[str, Dict[str, Any]],
    ) -> str:
        lines: List[str] = []
        for doc_id in document_ids:
            doc = parsed_docs.get(doc_id)
            if not doc:
                continue
            title = doc.get("metadata", {}).get("title", "未知标题")
            sm = doc.get("structured_summary") or {}
            refs = doc.get("references", [])
            years = [r.get("year") for r in refs if r.get("year")]
            year = years[0] if years else "未知"
            lines.append(
                f"- doc_id={doc_id} 标题《{title}》 年份={year}\n"
                f"  目的: {sm.get('purpose', '')}\n"
                f"  方法: {sm.get('methods', '')}\n"
                f"  数据: {sm.get('data', '')}\n"
                f"  结论: {sm.get('conclusion', '')}"
            )
        return "\n\n".join(lines)

    def _build_outline(
        self, topic: str, sections: List[str], doc_summaries: str
    ) -> List[OutlineSection]:
        try:
            raw = model_loader.chat_text(
                prompts.REVIEW_OUTLINE_SYSTEM,
                prompts.REVIEW_OUTLINE_USER_TEMPLATE.format(
                    topic=topic, sections=", ".join(sections), doc_summaries=doc_summaries
                ),
            )
            arr = self._safe_json_list(raw)
            return [
                OutlineSection(
                    section=it.get("section", ""),
                    key_points=it.get("key_points", []),
                )
                for it in arr
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("大纲生成失败: %s", exc)
            return [OutlineSection(section=s, key_points=[]) for s in sections]

    def _build_views_gaps_timeline(
        self, topic: str, doc_summaries: str
    ) -> tuple:
        try:
            raw = model_loader.chat_text(
                prompts.REVIEW_VIEWS_SYSTEM,
                prompts.REVIEW_VIEWS_USER_TEMPLATE.format(
                    topic=topic, doc_summaries=doc_summaries
                ),
            )
            obj = self._safe_json(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("观点/缺口/时间线生成失败: %s", exc)
            return [], [], []

        views = [
            CoreView(
                view=v.get("view", ""),
                supporting_docs=v.get("supporting_docs", []),
                evidence=v.get("evidence"),
            )
            for v in obj.get("core_views", [])
        ]
        gaps = [
            ResearchGap(
                gap=g.get("gap", ""),
                severity=g.get("severity", "medium"),
                suggested_direction=g.get("suggested_direction"),
            )
            for g in obj.get("research_gaps", [])
        ]
        timeline = [
            EvolutionEvent(
                year=e.get("year", ""),
                event=e.get("event", ""),
                document_id=e.get("document_id"),
            )
            for e in obj.get("evolution_timeline", [])
        ]
        return views, gaps, timeline

    # ---------- 持久化 ----------
    def _save(self, review: ReviewResponse) -> None:
        path = REVIEWS_DIR / f"{review.review_id}.json"
        path.write_text(
            json.dumps(review.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_review(self, review_id: str) -> ReviewResponse:
        path = REVIEWS_DIR / f"{review_id}.json"
        if not path.exists():
            raise ReviewNotFoundError(f"综述不存在: {review_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return ReviewResponse(**data)

    # ---------- P1-5: 综述导出（md / docx） ----------
    def export_review(self, review_id: str, fmt: str) -> Tuple[bytes, str]:
        """导出综述为 Markdown 或 Word(docx)。

        Args:
            review_id: 综述 ID
            fmt: "md" 或 "docx"

        Returns:
            (文件字节内容, 下载文件名)
        """
        review = self.get_review(review_id)  # 不存在则抛 ReviewNotFoundError
        refs = self._build_references(review)
        base = safe_filename(review.title or review_id)

        if fmt == "md":
            content = self._build_markdown(review, refs)
            return content, f"{base}.md"
        if fmt == "docx":
            content = self._build_docx(review, refs)
            return content, f"{base}.docx"
        raise ValueError(f"不支持的导出格式: {fmt}（仅支持 md / docx）")

    def _collect_review_doc_ids(self, review: ReviewResponse) -> List[str]:
        """收集综述关联的全部 document_id（核心观点支撑文献 + 发展脉络事件），去重保序。"""
        seen = set()
        doc_ids: List[str] = []
        for v in review.core_views:
            for d in v.supporting_docs:
                if d and d not in seen:
                    seen.add(d)
                    doc_ids.append(d)
        for e in review.evolution_timeline:
            if e.document_id and e.document_id not in seen:
                seen.add(e.document_id)
                doc_ids.append(e.document_id)
        return doc_ids

    def _build_references(self, review: ReviewResponse) -> List[str]:
        """从综述关联文献的实际解析结果中提取参考文献条目。

        - 通过 document_id 调 load_parsed_result 取 metadata(authors/title) 与年份；
        - 加载失败时退化为 document_id 前 8 位作为标识，绝不编造文献信息。
        """
        refs: List[str] = []
        for doc_id in self._collect_review_doc_ids(review):
            doc = load_parsed_result(doc_id)
            if not doc:
                logger.warning("导出综述参考文献：无法加载文档 %s，用 id 前8位兜底", doc_id)
                refs.append(f"[{len(refs) + 1}] {doc_id[:8]}")
                continue
            meta = doc.get("metadata", {}) or {}
            authors = meta.get("authors", []) or []
            author_str = ", ".join(authors[:3]) if authors else "Unknown"
            title = meta.get("title") or doc_id[:8]
            # 年份：优先取文档参考文献里的首个年份，其次解析时间的年份
            year = ""
            for r in doc.get("references", []) or []:
                if isinstance(r, dict) and r.get("year"):
                    year = r["year"]
                    break
            if not year and meta.get("parsed_at"):
                year = str(meta["parsed_at"])[:4]
            # 解析结果不包含期刊字段，不编造，按实际可得信息组织
            refs.append(f'[{len(refs) + 1}] {author_str}, "{title}", {year}'.rstrip(", "))
        return refs

    @staticmethod
    def _build_markdown(review: ReviewResponse, refs: List[str]) -> bytes:
        """把综述渲染为 Markdown 文本（UTF-8 字节）。"""
        lines: List[str] = []
        lines.append(f"# {review.title}")
        lines.append("")
        lines.append(f"生成时间: {review.created_at or ''}")
        lines.append("")

        # 一、综述大纲
        lines.append("## 一、综述大纲")
        for sec in review.outline:
            lines.append(f"### {sec.section}")
            for kp in sec.key_points:
                lines.append(f"- {kp}")
            lines.append("")

        # 二、核心观点
        lines.append("## 二、核心观点")
        for v in review.core_views:
            lines.append(f"### {v.view}")
            if v.evidence:
                lines.append(f"依据: {v.evidence}")
            if v.supporting_docs:
                lines.append(f"支撑文献: {', '.join(v.supporting_docs)}")
            lines.append("")

        # 三、研究缺口
        lines.append("## 三、研究缺口")
        for g in review.research_gaps:
            lines.append(f"- [{g.severity}] {g.gap}")
            if g.suggested_direction:
                lines.append(f"  建议方向: {g.suggested_direction}")
        lines.append("")

        # 四、发展脉络
        lines.append("## 四、发展脉络")
        for e in review.evolution_timeline:
            src = f" ({e.document_id})" if e.document_id else ""
            lines.append(f"- [{e.year}] {e.event}{src}")
        lines.append("")

        # 五、参考文献
        lines.append("## 五、参考文献")
        for r in refs:
            lines.append(r)

        return "\n".join(lines).encode("utf-8")

    @staticmethod
    def _build_docx(review: ReviewResponse, refs: List[str]) -> bytes:
        """把综述渲染为 Word(docx) 字节流。结构与 Markdown 版一致。"""
        try:
            from docx import Document
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("未安装 python-docx，无法导出 docx") from exc

        doc = Document()
        # 标题：Heading 1
        doc.add_heading(review.title or "综述", level=1)
        doc.add_paragraph(f"生成时间: {review.created_at or ''}")

        # 一、综述大纲
        doc.add_heading("一、综述大纲", level=2)
        for sec in review.outline:
            doc.add_heading(sec.section, level=3)
            for kp in sec.key_points:
                doc.add_paragraph(kp, style="List Bullet")

        # 二、核心观点
        doc.add_heading("二、核心观点", level=2)
        for v in review.core_views:
            doc.add_heading(v.view, level=3)
            if v.evidence:
                doc.add_paragraph(f"依据: {v.evidence}")
            if v.supporting_docs:
                doc.add_paragraph(f"支撑文献: {', '.join(v.supporting_docs)}")

        # 三、研究缺口
        doc.add_heading("三、研究缺口", level=2)
        for g in review.research_gaps:
            doc.add_paragraph(f"[{g.severity}] {g.gap}", style="List Bullet")
            if g.suggested_direction:
                doc.add_paragraph(f"建议方向: {g.suggested_direction}")

        # 四、发展脉络
        doc.add_heading("四、发展脉络", level=2)
        for e in review.evolution_timeline:
            src = f" ({e.document_id})" if e.document_id else ""
            doc.add_paragraph(f"[{e.year}] {e.event}{src}", style="List Bullet")

        # 五、参考文献（编号列表）
        doc.add_heading("五、参考文献", level=2)
        for r in refs:
            doc.add_paragraph(r, style="List Number")

        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()


    @staticmethod
    def _safe_json(text: str) -> Dict[str, Any]:
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
            logger.warning("综述 JSON 解析失败: %s", text[:200])
            return {}

    @staticmethod
    def _safe_json_list(text: str) -> List[Dict[str, Any]]:
        import re

        if not text:
            return []
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1:
            cleaned = cleaned[start : end + 1]
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("综述列表 JSON 解析失败: %s", text[:200])
            return []


review_service = ReviewService()
