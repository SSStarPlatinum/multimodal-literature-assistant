"""
多模态文献解析服务
==================
职责：
1. PDF 文本/布局提取（PyMuPDF 为主引擎，空格/布局准确率远高于 pdfplumber；
   pdfplumber 保留作表格提取备选）。
2. 页面/区域图片经 PIL 预处理后送 Qwen2.5-VL 做公式识别与表格识别。
3. 数学公式转 LaTeX（严格检测 + VL 修正）。
4. 嵌入图片提取并持久化，返回可访问 URL。
5. 参考文献正则提取并结构化（支持 IEEE / ACM / 数字编号等多种格式）。
6. 生成结构化摘要（purpose/methods/data/conclusion）供 RAG 第一层使用。
7. 解析结果持久化为 JSON。
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.config import get_settings
from app.core.exceptions import ParsingError
from app.core.logging import logger
from app.services.model_loader import model_loader
from app.utils import prompts
from app.utils.file_utils import (
    load_parsed_result,
    save_figure_image,
    save_parsed_result,
    utc_now_iso,
)

settings = get_settings()

# ===== 公式检测相关常量 =====
# 真正的数学符号集合（不含普通连字符 -，避免 cross-domain 误判）
_MATH_SYMBOLS = set("=+*/∑∫√≤≥≠×÷∈∀∃∞∂∇∏∐∮∯∰∱∲∳±∓∔∕∖∗∘∙√∛∜∝∞∠∡∢∣∤∥∦∧∨∩∪∫∬∭∮∯∰∱∲∳∴∵∼∽∾∿≀≁≂≃≄≅≆≇≈≉≊≋≌≍≎≏≐≑≒≓≔≕≖≗≘≙≚≛≜≝≞≟≠≡≢≣≤≥≦≧≨≩≪≫≬≭≮≯≰≱≲≳≴≵≶≷≸≹≺≻≼≽≾≿⊀⊁⊂⊃⊄⊅⊆⊇⊈⊉⊊⊋⊌⊍⊎⊏⊐⊑⊒⊓⊔⊕⊖⊗⊘⊙⊚⊛⊜⊝⊞⊟⊠⊡⊢⊣⊤⊥⊦⊧⊨⊩⊪⊫⊬⊭⊮⊯⊰⊱⊲⊳⊴⊵⊶⊷⊸⊹⊺⊻⊼⊽⊾⊿⋀⋁⋂⋃⋄⋅⋆⋇⋈⋉⋊⋋⋌⋍⋎⋏⋐⋑⋒⋓⋔⋕⋖⋗⋘⋙⋚⋛⋜⋝⋞⋟⋠⋡⋢⋣⋤⋥⋦⋧⋨⋩⋪⋫⋬⋭⋮⋯⋰⋱")
# LaTeX 数学命令关键词（出现即高度疑似公式）
_LATEX_MATH_KEYWORDS = [
    r"\\frac", r"\\sum", r"\\int", r"\\lim", r"\\log", r"\\exp",
    r"\\sqrt", r"\\alpha", r"\\beta", r"\\gamma", r"\\delta",
    r"\\epsilon", r"\\theta", r"\\lambda", r"\\mu", r"\\sigma",
    r"\\omega", r"\\pi", r"\\phi", r"\\varphi", r"\\infty",
    r"\\partial", r"\\nabla", r"\\times", r"\\cdot", r"\\leq",
    r"\\geq", r"\\neq", r"\\approx", r"\\equiv", r"\\propto",
    r"\\rightarrow", r"\\leftarrow", r"\\Rightarrow", r"\\Leftarrow",
    r"\\mathbb", r"\\mathcal", r"\\mathbf", r"\\mathrm",
    r"\\operatorname", r"\\widehat", r"\\widetilde", r"\\overline",
    r"\\underline", r"\\overbrace", r"\\underbrace",
]
# 普通英文单词（用于排除普通文本行）
_COMMON_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are",
    "was", "were", "have", "has", "had", "not", "but", "all",
    "can", "may", "will", "each", "which", "their", "they",
    "them", "then", "than", "into", "over", "such", "been",
    "also", "more", "most", "other", "some", "its", "our",
    "your", "what", "when", "where", "how", "why", "who",
    "proposed", "method", "results", "experiment", "model",
    "based", "using", "show", "shown", "figure", "table",
    "section", "paper", "study", "research", "analysis",
}


class ParserService:
    """文献解析服务。"""

    def parse_file(
        self,
        doc_id: str,
        file_path: Path,
        filename: str,
        parse_formula: bool = True,
        parse_figures: bool = True,
        parse_references: bool = True,
        on_progress: Optional[Callable[[str, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """入口：根据文件类型分发解析。

        Args:
            on_progress: 可选进度回调，签名为 on_progress(step, percent, message)，
                         回调内部异常不会影响解析主流程。
        """
        ext = file_path.suffix.lower().lstrip(".")
        try:
            if ext == "pdf":
                result = self._parse_pdf(
                    doc_id, file_path, parse_formula, parse_figures, parse_references,
                    on_progress=on_progress,
                )
            elif ext in ("png", "jpg", "jpeg", "tiff"):
                result = self._parse_single_image(file_path, parse_formula)
            else:
                raise ParsingError(f"不支持的解析类型: {ext}")
        except ParsingError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("解析文件失败: %s", file_path)
            raise ParsingError(f"解析失败: {exc}") from exc

        result["document_id"] = doc_id
        result["filename"] = filename
        result["status"] = "completed"
        result["metadata"]["parsed_at"] = utc_now_iso()

        # 生成结构化摘要（RAG 第一层）
        result["structured_summary"] = self._build_structured_summary(result)
        # 结构化摘要生成完成，上报最终进度
        self._report_progress(on_progress, "summary_generation", 100, "结构化摘要生成完成")

        save_parsed_result(doc_id, result)
        logger.info("文档 %s 解析完成: %s", doc_id, result["stats"])
        return result

    # ---------- PDF 解析（PyMuPDF 主引擎） ----------
    def _parse_pdf(
        self,
        doc_id: str,
        file_path: Path,
        parse_formula: bool,
        parse_figures: bool,
        parse_references: bool,
        on_progress: Optional[Callable[[str, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """用 PyMuPDF 逐页提取文本块、嵌入图片；pdfplumber 提取表格。"""
        import fitz  # PyMuPDF

        text_blocks: List[Dict[str, Any]] = []
        tables: List[Dict[str, Any]] = []
        formulas: List[Dict[str, Any]] = []
        figures: List[Dict[str, Any]] = []
        all_text_parts: List[str] = []
        # 候选公式区域（带页码/坐标），供后续 VL 识别使用
        formula_regions: List[Dict[str, Any]] = []

        doc = fitz.open(str(file_path))
        page_count = len(doc)

        try:
            for page_no, page in enumerate(doc, start=1):
                # ---- 文本提取：fitz get_text 自带正确的空格与换行 ----
                # 使用 "text" 模式：保留自然阅读顺序，空格由 fitz 根据字符间距自动插入
                page_text = page.get_text("text") or ""
                all_text_parts.append(page_text)

                # ---- 文本块切分：基于 PyMuPDF block 结构切分段落（比空行切分更可靠） ----
                page_blocks = self._split_into_paragraphs(page, page_no)
                text_blocks.extend(page_blocks)

                # ---- 候选公式区域检测（带坐标，仅在启用 VL 时才逐页扫描）----
                # 注意：这里只收集候选 bbox，不立即调 VL（避免持锁/开销），
                # 等到全文提取完成后统一在公式识别阶段送 VL。
                if parse_formula and settings.FORMULA_VL_ENABLED:
                    try:
                        page_regions = self._detect_formula_regions(page)
                        formula_regions.extend(page_regions)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("第 %d 页候选公式区域检测失败: %s", page_no, exc)

                # ---- 表格提取：pdfplumber 备选（fitz 的表格提取在某些版本不稳定） ----
                try:
                    page_tables = self._extract_tables_with_pdfplumber(file_path, page_no)
                    tables.extend(page_tables)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("第 %d 页表格提取跳过: %s", page_no, exc)

            # ---- 全文构建完成：上报文本提取进度 ----
            full_text = "\n\n".join(all_text_parts)
            self._report_progress(on_progress, "text_extraction", 30, "文本提取完成")

            # ---- 公式检测：基于标号定位 + 文本提取，VL 可选增强 ----
            if parse_formula:
                # 基于标号检测公式区域（精准，不会误判普通文本）
                formula_regions_all: List[Dict[str, Any]] = []
                for page_no_inner, page_inner in enumerate(doc, start=1):
                    try:
                        page_regions = self._detect_formula_regions(page_inner)
                        formula_regions_all.extend(page_regions)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("第 %d 页公式区域检测失败: %s", page_no_inner, exc)
                # 识别公式（默认文本提取，VL可选），同时保存公式原图供"查看原文"
                formulas = self._recognize_formulas(doc, formula_regions_all, doc_id)
                # 如果标号检测没找到任何公式，回退到严格正则检测（兼容无标号论文）
                if not formulas:
                    logger.info("标号检测未找到公式，回退正则全文检测")
                    formulas = self._extract_formulas_strict(full_text)
            self._report_progress(on_progress, "formula_recognition", 50, "公式识别完成")

            # ---- 图表提取：fitz 提取嵌入图片并持久化 ----
            if parse_figures:
                figures = self._extract_figures_fitz(doc, doc_id)
            self._report_progress(on_progress, "figure_extraction", 70, "图表提取完成")

            # ---- 元信息抽取 ----
            metadata = self._extract_metadata(full_text, page_count)

            # ---- 参考文献 ----
            references = []
            if parse_references:
                references = self._extract_references(full_text)
            self._report_progress(on_progress, "references", 85, "参考文献提取完成")

        finally:
            doc.close()

        stats = {
            "text_blocks": len(text_blocks),
            "formulas": len(formulas),
            "figures": len(figures),
            "tables": len(tables),
            "references": len(references),
        }

        return {
            "metadata": metadata,
            "stats": stats,
            "text_blocks": text_blocks,
            "formulas": formulas,
            "figures": figures,
            "tables": tables,
            "references": references,
            "full_text": full_text,
        }

    # ---------- 文本块切分 ----------
    @staticmethod
    def _split_into_paragraphs(page, page_no: int) -> List[Dict[str, Any]]:
        """将页面文本按段落切分（基于 PyMuPDF block 结构）。

        使用 get_text("dict") 获取带坐标的 blocks，每个 block 通常就是一个段落。
        比纯文本空行切分更可靠，尤其适合 IEEE 双栏论文（纯文本模式下段落间无空行）。

        处理逻辑：
        1. 获取所有文本 block，按 y 坐标排序（同 y 按 x 排序，处理双栏）
        2. 每个 block 内的 lines 合并为一个段落（处理自动换行和连字符）
        3. 过滤掉过短的碎片（< 10 字符），但保留标题行
        4. 跳过公式行、图表标题等非正文内容（可选）
        """
        import fitz  # PyMuPDF

        blocks: List[Dict[str, Any]] = []
        raw = page.get_text("dict") or {}
        page_width = page.rect.width

        # 收集所有文本 block
        text_blocks = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0:  # 0 = text
                continue
            bbox = block.get("bbox", [0, 0, 0, 0])
            lines = block.get("lines", [])
            if not lines:
                continue

            # 合并 block 内所有行的文本
            block_text = ""
            for line in lines:
                spans = line.get("spans", [])
                line_text = "".join(s.get("text", "") for s in spans).strip()
                if not line_text:
                    continue
                if block_text:
                    # 连字符换行：cross-\ndomain -> crossdomain
                    if block_text.endswith("-") and not block_text.endswith("--"):
                        block_text = block_text[:-1] + line_text
                    else:
                        block_text += " " + line_text
                else:
                    block_text = line_text

            block_text = block_text.strip()
            if not block_text:
                continue

            text_blocks.append({
                "bbox": bbox,
                "text": block_text,
                "y": bbox[1],
                "x": bbox[0],
            })

        if not text_blocks:
            return []

        # 双栏排序：先按栏（x < 页面中线为左栏），再按 y
        mid_x = page_width * 0.5
        left_col = [b for b in text_blocks if b["x"] < mid_x]
        right_col = [b for b in text_blocks if b["x"] >= mid_x]
        left_col.sort(key=lambda b: b["y"])
        right_col.sort(key=lambda b: b["y"])
        sorted_blocks = left_col + right_col

        # 生成文本块
        for tb in sorted_blocks:
            content = tb["text"]
            # 过滤过短的碎片（页码、页眉等），但保留标题（以数字开头或全大写）
            if len(content) < 10:
                is_heading = bool(re.match(r"^[IVX]+\.\s", content) or
                                  re.match(r"^\d+(\.\d+)*\s", content) or
                                  (content.isupper() and len(content) > 3))
                if not is_heading:
                    continue

            blocks.append({
                "page": page_no,
                "type": "text",
                "content": content,
            })

        return blocks

    # ---------- 表格提取（pdfplumber 备选） ----------
    @staticmethod
    def _extract_tables_with_pdfplumber(file_path: Path, page_no: int) -> List[Dict[str, Any]]:
        """用 pdfplumber 提取指定页的表格。"""
        import pdfplumber

        tables: List[Dict[str, Any]] = []
        with pdfplumber.open(str(file_path)) as pdf:
            if page_no - 1 < len(pdf.pages):
                page = pdf.pages[page_no - 1]
                for tbl in page.extract_tables():
                    if not tbl or not tbl[0]:
                        continue
                    markdown = ParserService._table_to_markdown(tbl)
                    if markdown.count("|") >= 4:  # 至少有实际内容
                        tables.append({
                            "page": page_no,
                            "markdown": markdown,
                            "caption": "",
                        })
        return tables

    # ---------- 公式检测（严格版） ----------
    def _extract_formulas_strict(self, full_text: str) -> List[Dict[str, Any]]:
        """严格检测数学公式行，避免把普通文本误判为公式。

        判定逻辑（满足任一即候选）：
        1. 包含 LaTeX 数学命令（\\frac, \\sum 等）
        2. 数学符号密度 > 15% 且 不含 3 个以上常见英文单词

        排除规则：
        - 包含 3 个以上常见英文单词的行（普通句子）
        - 纯数字/日期行
        - 参考文献条目行
        """
        formulas: List[Dict[str, Any]] = []
        idx = 0

        for line in full_text.splitlines():
            s = line.strip()
            if len(s) < 5 or len(s) > 300:
                continue

            # 排除参考文献行
            if re.match(r"^\[\d+\]", s) or re.match(r"^\d+\.\s+[A-Z]", s):
                continue

            # 排除纯数字/页码/日期
            if re.match(r"^[\d\s,./:;-]+$", s):
                continue

            is_formula = False
            reason = ""

            # 条件1：包含 LaTeX 数学命令
            for kw in _LATEX_MATH_KEYWORDS:
                if re.search(kw, s, re.IGNORECASE):
                    is_formula = True
                    reason = "latex_command"
                    break

            # 条件2：数学符号密度高
            if not is_formula:
                math_char_count = sum(1 for c in s if c in _MATH_SYMBOLS)
                # 必须包含等号或核心数学运算符
                has_core_math = any(c in s for c in "=+∑∫√≤≥≠×÷±∂∇∏∈∀∃∞")
                if has_core_math and len(s) > 0:
                    density = math_char_count / len(s)
                    # 统计常见英文单词数量
                    words = re.findall(r"[a-zA-Z]{2,}", s.lower())
                    common_word_count = sum(1 for w in words if w in _COMMON_WORDS)
                    if density >= 0.08 and common_word_count <= 2:
                        is_formula = True
                        reason = f"math_density={density:.2f}"

            if is_formula:
                # 清理：去掉行首行尾的编号、标点
                latex = s.strip()
                # 如果已经是 $...$ 格式，保留；否则包裹
                if not (latex.startswith("$") and latex.endswith("$")):
                    latex = f"${latex}$"
                formulas.append({
                    "page": 0,
                    "index": idx,
                    "latex": latex,
                    "original": s,
                    "detect_reason": reason,
                    "vl_success": False,
                })
                idx += 1
                if idx >= 100:
                    break

        logger.info("公式严格检测完成: 命中 %d 条", len(formulas))
        return formulas

    # ---------- 公式检测（基于标号 + 区域裁剪，VL 可选） ----------
    def _detect_formula_regions(self, page) -> List[Dict[str, Any]]:
        """基于公式标号检测候选公式区域，支持多行/二维公式布局。

        核心思路：学术论文中正式公式都有标号（如 (1), (2.3)），位于公式右侧。
        IEEE双栏论文中，标号通常单独一行（不含公式主体），公式主体可能分布在
        标号行上下方（分数、求和符号、上下标等二维布局）。

        算法：
        1. 遍历所有文本行，检测行尾是否有标号模式：(数字) 或 (数字.数字)
        2. 标号行不要求包含数学符号（因为标号常单独成行）
        3. 以标号行为基准，确定较小的公式区域（向上2.5倍行高 ~ 向下1.5倍行高）
        4. 用 page.get_text("text", clip=bbox) 提取区域文本
        5. 从区域文本中只保留含数学符号/等号的行（过滤正文行），合并为公式文本
        6. 验证数学符号密度，过滤误判

        Returns:
            [{"bbox": [x0,y0,x1,y1], "text": "公式文本", "page": 页码,
              "formula_number": "1"}, ...]
        """
        page_no = getattr(page, "number", 0) + 1
        page_width = page.rect.width
        import fitz  # PyMuPDF
        raw = page.get_text("dict") or {}

        # 收集所有行（带坐标和文本），计算平均行高
        all_lines: List[Dict[str, Any]] = []
        total_height = 0.0
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(s.get("text", "") for s in spans).strip()
                if not text:
                    continue
                bbox = line.get("bbox") or [0, 0, 0, 0]
                line_height = bbox[3] - bbox[1] if bbox[3] > bbox[1] else 10
                all_lines.append({
                    "bbox": list(bbox),
                    "text": text,
                    "height": line_height,
                })
                total_height += line_height

        if not all_lines:
            return []

        avg_line_height = total_height / len(all_lines)
        # 数学符号集合
        math_chars = set("=+∑∫√≤≥≠×÷±∂∇∏∈∀∃∞^_/−·…∼≈∝∞∫∮∯∰∱∲∳")
        # 行级数学符号检测：一行中包含这些字符则认为是公式行
        math_line_chars = set("=+∑∫√≤≥≠×÷±∂∇∏∈∀∃∞^_/−·…∼≈∝∘⊙⊗")

        # 标号模式：行尾的 (1), (2.3), (10) 等
        label_pattern = re.compile(r"\((\d+(?:\.\d+)?)\)\s*$")
        # 行内标号（用于清理）
        label_inline = re.compile(r"\((\d+(?:\.\d+)?)\)")

        candidates: List[Dict[str, Any]] = []

        for i, line_info in enumerate(all_lines):
            text = line_info["text"]
            m = label_pattern.search(text)
            if not m:
                continue

            formula_number = m.group(1)
            label_bbox = line_info["bbox"]
            label_y0 = label_bbox[1]
            label_x0 = label_bbox[0]
            label_x1 = label_bbox[2]

            # 判断所在栏：标号行x > 页面宽度50%则在右栏
            # 双栏论文左栏右边缘约在页面48%处，用50%阈值更准确
            if label_x0 > page_width * 0.50:
                col_x0 = page_width * 0.52
            else:
                col_x0 = 40.0

            # 公式区域y范围：向上2.5倍行高，向下1.5倍行高
            # 覆盖分数（分子/分母）、求和符号（上下限）等二维布局，同时避免包含过多正文
            formula_y0 = label_y0 - avg_line_height * 2.5
            formula_y1 = label_bbox[3] + avg_line_height * 1.5

            # 公式区域x范围：栏左边界到标号行右边界+10pt
            formula_x0 = col_x0
            formula_x1 = label_x1 + 10.0

            clip_rect = fitz.Rect(
                max(0, formula_x0),
                max(0, formula_y0),
                min(page_width, formula_x1),
                min(page.rect.height, formula_y1),
            )

            # 用clip提取区域文本
            try:
                region_text = page.get_text("text", clip=clip_rect)
            except Exception:
                region_text = ""

            if not region_text.strip():
                continue

            # 关键：从区域文本中精确过滤出公式行，排除正文行
            # 正文行特征：包含常见英文单词 + 长度较长 + 有完整句子结构
            # 公式行特征：包含等号/数学运算符/希腊字母，或短行含字母数字混合
            common_words = set(["the", "a", "an", "is", "are", "of", "and", "or",
                                "where", "with", "for", "in", "to", "given", "this",
                                "that", "we", "can", "be", "as", "by", "from", "which",
                                "has", "have", "been", "was", "were", "will", "would",
                                "could", "should", "may", "might", "must", "shall",
                                "used", "using", "use", "define", "defined", "denotes",
                                "denote", "respectively", "figure", "fig", "table",
                                "shown", "show", "illustrated", "algorithm", "equation",
                                "section", "chapter", "its", "their", "our", "these",
                                "those", "such", "each", "all", "both", "between",
                                "through", "during", "before", "after", "above",
                                "below", "into", "onto", "upon", "over", "under",
                                "again", "further", "then", "once", "here", "there",
                                "when", "where", "why", "how", "all", "any", "both",
                                "each", "few", "more", "most", "other", "some",
                                "such", "no", "nor", "not", "only", "own", "same",
                                "so", "than", "too", "very", "just", "because",
                                "but", "if", "or", "and", "while", "although",
                                "though", "since", "until", "unless", "however",
                                "therefore", "thus", "hence", "moreover",
                                "furthermore", "nevertheless", "nonetheless",
                                "consequently", "accordingly", "meanwhile"])

            # 第一步：过滤掉明显的正文行
            candidate_lines = []
            for line in region_text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # 跳过纯标号行
                if label_pattern.match(line):
                    continue

                # 正文行检测：
                words_in_line = set(re.findall(r"\b[a-z]{2,}\b", line.lower()))
                common_word_count = len(words_in_line & common_words)
                # 包含1个以上常见单词且长度>20 → 正文
                if common_word_count >= 1 and len(line) > 20:
                    continue
                # 包含2个以上常见单词 → 正文（不管长度）
                if common_word_count >= 2:
                    continue
                # 以大写字母开头且长度>25 → 正文句子开头
                if re.match(r"^[A-Z]", line) and len(line) > 25 and common_word_count >= 1:
                    continue

                candidate_lines.append(line)

            # 第二步：找到公式起始行（第一个包含等号的行）
            # 公式通常以等号为标志，等号之前的是正文引入
            formula_start_idx = -1
            for idx, line in enumerate(candidate_lines):
                if "=" in line:
                    formula_start_idx = idx
                    break

            if formula_start_idx >= 0:
                # 如果等号行的前一行很短（<15字符）且含数学符号/希腊字母，也包含进来
                # （公式左半部分可能被拆到上一行，如 "θt+1 S" + "= ..."）
                if formula_start_idx > 0:
                    prev_line = candidate_lines[formula_start_idx - 1]
                    prev_has_math = any(c in prev_line for c in "=+−×÷∑∫√≤≥≠±∂∇∏∈∞∘⊙⊗αβγδεζηθικλμνξοπρστυφχψω")
                    if len(prev_line) < 20 and prev_has_math:
                        formula_start_idx -= 1
                formula_lines = candidate_lines[formula_start_idx:]
            else:
                # 没有等号的公式（如不等式、集合定义），保留所有候选行
                formula_lines = candidate_lines

            if not formula_lines:
                continue

            # 合并公式行，用空格连接
            formula_text = " ".join(formula_lines)
            # 去掉行内标号
            formula_text = label_inline.sub("", formula_text).strip()
            # 清理多余空格
            formula_text = re.sub(r"\s+", " ", formula_text).strip()

            # 第三步：去掉开头的正文片段
            # 如果以小写字母开头且前面是被截断的单词（如"cenarios."），去掉
            if re.match(r"^[a-z]+[.,]?\s+[A-Z]", formula_text):
                formula_text = re.sub(r"^[a-z]+[.,]?\s+", "", formula_text)
            # 如果以"Given"、"Where"、"With"等正文引导词开头，去掉到冒号
            formula_text = re.sub(r"^(Given|Where|With|For|In|Let|Suppose|Assume|Define|Consider)[^:]*:\s*", "", formula_text, flags=re.IGNORECASE)

            # 第四步：去掉末尾的正文片段和短碎片
            # 去掉以"where"、"with"、"and"、"the"、"in"、"of"等开头的末尾片段
            formula_text = re.sub(r"\s+(where|with|and|the|in|of|for|to|as|by|from|which|that|this|these|those|its|their|our)\s+.*$", "", formula_text, flags=re.IGNORECASE)
            # 去掉末尾连续的单个字母碎片（如 "h d l b l l i li i"）
            formula_text = re.sub(r"(\s+[a-zA-Z]{1,2}){3,}$", "", formula_text)
            # 去掉末尾的孤立逗号、句号
            formula_text = re.sub(r"[,\s]+$", "", formula_text).strip()

            if not formula_text or len(formula_text) < 3:
                continue

            # 验证：必须包含等号或数学运算符
            has_eq = "=" in formula_text
            has_math_op = any(c in formula_text for c in "+−×÷∑∫√≤≥≠±∂∇∏∈∞")
            if not (has_eq or has_math_op):
                continue

            # 数学符号密度验证（过滤误判）
            math_count = sum(1 for c in formula_text if c in math_chars)
            math_density = math_count / max(len(formula_text), 1)
            if math_density < 0.02 and len(formula_text) > 30:
                continue

            candidates.append({
                "bbox": [clip_rect.x0, clip_rect.y0, clip_rect.x1, clip_rect.y1],
                "text": formula_text,
                "page": page_no,
                "formula_number": formula_number,
                "math_density": round(math_density, 3),
            })

        logger.info(
            "第 %d 页公式标号检测: 命中 %d 个公式 (avg_line_height=%.1f)",
            page_no, len(candidates), avg_line_height,
        )
        for c in candidates:
            logger.debug("  公式(%s): density=%.3f text=%s",
                         c["formula_number"], c["math_density"], c["text"][:80])
        return candidates

    def _extract_formula_text(self, page, bbox: List[float]) -> str:
        """从指定 bbox 区域提取公式文本并做基础清理。

        用 PyMuPDF 直接从区域提取文本，不依赖 VL，稳定可靠。
        清理步骤：
        1. 去掉行尾标号 (1), (2.3)
        2. 合并多行（去掉换行，加空格）
        3. 常见 Unicode 数学符号替换为 LaTeX 命令
        4. 清理多余空格

        Returns:
            清理后的公式文本
        """
        import fitz  # PyMuPDF

        try:
            rect = fitz.Rect(*bbox)
            if rect.is_empty or rect.is_infinite:
                return ""
            # 从区域提取文本
            text = page.get_text("text", clip=rect) or ""
            # 去掉行尾标号
            text = re.sub(r"\(\d+(?:\.\d+)?\)\s*$", "", text, flags=re.MULTILINE)
            # 合并多行：换行替换为空格
            text = re.sub(r"\s*\n\s*", " ", text)
            # 常见 Unicode 数学符号 → LaTeX
            replacements = {
                "≤": r"\leq", "≥": r"\geq", "≠": r"\neq", "≈": r"\approx",
                "∑": r"\sum", "∫": r"\int", "√": r"\sqrt", "∞": r"\infty",
                "∂": r"\partial", "∇": r"\nabla", "∏": r"\prod",
                "∈": r"\in", "∀": r"\forall", "∃": r"\exists",
                "×": r"\times", "÷": r"\div", "±": r"\pm",
                "→": r"\rightarrow", "←": r"\leftarrow",
                "⇒": r"\Rightarrow", "⇐": r"\Leftarrow",
                "α": r"\alpha", "β": r"\beta", "γ": r"\gamma",
                "δ": r"\delta", "ε": r"\epsilon", "θ": r"\theta",
                "λ": r"\lambda", "μ": r"\mu", "σ": r"\sigma",
                "ω": r"\omega", "π": r"\pi", "φ": r"\phi",
                "≤": r"\leq", "≥": r"\geq",
            }
            for unicode_char, latex_cmd in replacements.items():
                text = text.replace(unicode_char, f" {latex_cmd} ")
            # 清理多余空格
            text = re.sub(r"\s+", " ", text).strip()
            return text
        except Exception as exc:  # noqa: BLE001
            logger.warning("公式区域文本提取失败 (bbox=%s): %s", bbox, exc)
            return ""

    def _ocr_formula_with_vl(self, page, bbox: List[float]) -> Optional[List[str]]:
        """把页面指定 bbox 区域渲染成图片，送 VL 模型识别为 LaTeX 列表。

        仅在 FORMULA_VL_ENABLED=true 时调用，作为文本提取的可选增强。
        默认关闭，因为 VL 识别公式容易出错，文本提取更稳定。

        Returns:
            识别成功返回 LaTeX 字符串列表；失败返回 None。
        """
        import fitz  # PyMuPDF

        try:
            rect = fitz.Rect(*bbox)
            if rect.is_empty or rect.is_infinite:
                return None
            pix = page.get_pixmap(clip=rect, dpi=300)
            image_bytes = pix.tobytes("png")

            out = model_loader.chat_with_image(
                prompts.FORMULA_VL_USER_TEMPLATE, image_bytes
            )
            if not out or not out.strip():
                return None
            latex_list = self._extract_latex_from_output(out)
            return latex_list if latex_list else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("VL 公式识别失败 (bbox=%s): %s", bbox, exc)
            return None

    @staticmethod
    def _extract_latex_from_output(text: str) -> List[str]:
        """从 VL 模型输出中提取 LaTeX 公式。

        支持格式：
        - $$E = mc^2$$ （标准）
        - $E = mc^2$ （单行）
        - \\[ E = mc^2 \\] （LaTeX 环境）
        - 纯文本中包含的公式（兜底：去掉非公式字符）

        过滤规则：
        - 去掉 "NONE"、"无公式" 等无效输出
        - 去掉过短的碎片（< 3 字符）
        """
        if not text:
            return []
        results: List[str] = []

        # 1. 提取 $$...$$
        for m in re.finditer(r"\$\$(.+?)\$\$", text, re.DOTALL):
            latex = m.group(1).strip()
            if latex and latex.upper() != "NONE" and len(latex) >= 3:
                results.append(latex)

        # 2. 提取 $...$（单行公式，避免匹配 $$）
        if not results:
            for m in re.finditer(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", text, re.DOTALL):
                latex = m.group(1).strip()
                if latex and latex.upper() != "NONE" and len(latex) >= 3:
                    results.append(latex)

        # 3. 提取 \[ ... \]
        if not results:
            for m in re.finditer(r"\\\[(.+?)\\\]", text, re.DOTALL):
                latex = m.group(1).strip()
                if latex and len(latex) >= 3:
                    results.append(latex)

        # 4. 兜底：如果输出看起来就是纯 LaTeX（没有解释性文字）
        if not results:
            cleaned = text.strip()
            # 去掉可能的前后缀说明
            cleaned = re.sub(r"^(这里是|以下是|公式为|LaTeX:?)\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*(结束|end|完毕)$", "", cleaned, flags=re.IGNORECASE)
            if cleaned and len(cleaned) >= 3 and not cleaned.upper().startswith("NONE"):
                # 检查是否包含数学特征
                if any(c in cleaned for c in "=^_{}\\") or re.search(r"\\[a-zA-Z]+", cleaned):
                    results.append(cleaned)

        return results

    def _recognize_formulas(
        self, doc, regions: List[Dict[str, Any]], doc_id: str = ""
    ) -> List[Dict[str, Any]]:
        """对检测到的公式区域进行识别，默认文本提取，VL 可选增强。

        策略：
        1. 默认：使用 _detect_formula_regions 中已过滤好的纯净公式文本
           （已排除正文行，只保留公式行），做符号替换和清理
        2. 可选增强：如果 FORMULA_VL_ENABLED=true，尝试 VL 识别为 LaTeX
        3. 保存公式区域渲染图到 /app/data/figures/，供前端"查看原文"显示

        Returns:
            公式条目列表，每条含
            ``{page, index, latex, original, detect_reason, vl_success,
              formula_number, image_url}``。
        """
        import fitz  # PyMuPDF
        from pathlib import Path

        formulas: List[Dict[str, Any]] = []
        text_ok = 0
        vl_ok = 0
        vl_fail = 0
        formula_idx = 0

        # 公式图片保存目录
        figures_dir = Path("/app/data/figures")
        figures_dir.mkdir(parents=True, exist_ok=True)

        for region in regions:
            page_no = region["page"]
            bbox = region["bbox"]
            # 使用已过滤好的纯净公式文本（不重新提取，避免正文混入）
            formula_text = region.get("text", "")
            formula_number = region.get("formula_number", "")
            try:
                page = doc[page_no - 1]  # fitz 页码 0-based
            except Exception as exc:  # noqa: BLE001
                logger.warning("定位第 %d 页失败，跳过该候选: %s", page_no, exc)
                continue

            # 如果过滤后的文本为空，回退到区域提取
            if not formula_text:
                formula_text = self._extract_formula_text(page, bbox)

            # 保存公式原图（渲染公式区域为PNG，供"查看原文"显示）
            image_url = ""
            try:
                rect = fitz.Rect(*bbox)
                if not rect.is_empty and not rect.is_infinite:
                    # 向外扩3pt，避免公式边缘被裁剪
                    expand_rect = fitz.Rect(
                        max(0, rect.x0 - 3),
                        max(0, rect.y0 - 3),
                        min(page.rect.width, rect.x1 + 3),
                        min(page.rect.height, rect.y1 + 3),
                    )
                    pix = page.get_pixmap(clip=expand_rect, dpi=200)
                    img_filename = f"{doc_id}_formula_{formula_idx}.png"
                    img_path = figures_dir / img_filename
                    pix.save(str(img_path))
                    image_url = f"/static/figures/{img_filename}"
            except Exception as exc:  # noqa: BLE001
                logger.warning("公式原图保存失败 (idx=%d): %s", formula_idx, exc)

            # 可选：VL 增强识别
            final_latex = formula_text
            detect_reason = "text"
            vl_success = False
            if settings.FORMULA_VL_ENABLED:
                vl_result = self._ocr_formula_with_vl(page, bbox)
                if vl_result:
                    final_latex = vl_result[0]
                    detect_reason = "vl"
                    vl_success = True
                    vl_ok += 1
                else:
                    vl_fail += 1

            # 统一包裹 $$...$$（独立公式用 display math）
            if not (final_latex.startswith("$$") and final_latex.endswith("$$")):
                if not (final_latex.startswith("$") and final_latex.endswith("$")):
                    final_latex = f"$${final_latex}$$"

            formulas.append({
                "page": page_no,
                "index": formula_idx,
                "latex": final_latex,
                "original": formula_text,
                "detect_reason": detect_reason,
                "vl_success": vl_success,
                "formula_number": formula_number,
                "image_url": image_url,
            })
            formula_idx += 1
            if detect_reason == "text":
                text_ok += 1

        logger.info(
            "公式识别完成: 文本提取 %d 条, VL 成功 %d 条, VL 失败回退 %d 条 (候选共 %d 个)",
            text_ok, vl_ok, vl_fail, len(regions),
        )
        return formulas

    # ---------- 图表提取（fitz 真正提取嵌入图片） ----------
    @staticmethod
    def _extract_figures_fitz(doc, doc_id: str) -> List[Dict[str, Any]]:
        """用 PyMuPDF 提取 PDF 中的嵌入图片，保存为 PNG 并返回 URL。

        去重策略：同一 xref 的图片只提取一次（PDF 中图片可能被多页引用）。
        """
        figures: List[Dict[str, Any]] = []
        seen_xrefs: set = set()
        img_index = 0

        for page_no, page in enumerate(doc, start=1):
            image_list = page.get_images(full=True)
            for img_info in image_list:
                xref = img_info[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                try:
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    ext = base_image.get("ext", "png")

                    # 过滤过小的图片（通常是装饰性元素、logo）
                    if len(image_bytes) < 2048:  # < 2KB 跳过
                        continue

                    # 保存图片并获取 URL
                    url = save_figure_image(doc_id, img_index, image_bytes, ext)

                    # 尝试在页面文本中查找图注
                    caption = ParserService._find_figure_caption(page, img_info)

                    figures.append({
                        "page": page_no,
                        "type": "figure",
                        "url": url,
                        "image_url": url,  # 兼容前端字段
                        "caption": caption,
                        "xref": xref,
                        "width": base_image.get("width", 0),
                        "height": base_image.get("height", 0),
                    })
                    img_index += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("提取图片 xref=%d 失败: %s", xref, exc)
                    continue

        logger.info("图表提取完成: %d 张（已去重）", len(figures))
        return figures

    @staticmethod
    def _find_figure_caption(page, img_info: Tuple) -> str:
        """在图片附近的文本中查找图注（Fig. / Figure / 图）。"""
        try:
            page_text = page.get_text("text")
            # 查找 "Fig. X" 或 "Figure X" 或 "图 X" 开头的行
            caption_pattern = re.compile(
                r"(?:Fig\.?|Figure|图)\s*\d+[:：.\s]+[^\n]{5,150}",
                re.IGNORECASE,
            )
            matches = caption_pattern.findall(page_text)
            if matches:
                return matches[0].strip()[:200]
        except Exception:  # noqa: BLE001
            pass
        return ""

    # ---------- 单张图片（直接 OCR/公式） ----------
    def _parse_single_image(
        self, file_path: Path, parse_formula: bool
    ) -> Dict[str, Any]:
        image_bytes = file_path.read_bytes()
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        processed = buf.getvalue()

        formulas: List[Dict[str, Any]] = []
        figures: List[Dict[str, Any]] = []
        tables: List[Dict[str, Any]] = []

        if parse_formula:
            try:
                out = model_loader.chat_with_image(
                    prompts.FORMULA_VL_USER_TEMPLATE, processed
                )
                latex_list = self._extract_latex_from_output(out)
                for i, latex in enumerate(latex_list):
                    if not (latex.startswith("$") and latex.endswith("$")):
                        latex = f"${latex}$"
                    formulas.append({
                        "page": 1, "index": i, "latex": latex,
                        "original": "", "detect_reason": "vl", "vl_success": True,
                    })
            except Exception as exc:  # noqa: BLE001
                logger.warning("图片公式识别失败: %s", exc)

        # 表格识别
        try:
            out = model_loader.chat_with_image(
                prompts.TABLE_VL_USER_TEMPLATE, processed
            )
            parsed = self._safe_json(out)
            if parsed.get("is_table"):
                tables.append(
                    {"page": 1, "markdown": parsed.get("markdown", ""), "caption": parsed.get("caption", "")}
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("图片表格识别失败: %s", exc)

        metadata = {"title": file_path.stem, "authors": [], "abstract": None, "page_count": 1}
        return {
            "metadata": metadata,
            "stats": {
                "text_blocks": 1,
                "formulas": len(formulas),
                "figures": 0,
                "tables": len(tables),
                "references": 0,
            },
            "text_blocks": [{"page": 1, "type": "image", "content": ""}],
            "formulas": formulas,
            "figures": figures,
            "tables": tables,
            "references": [],
            "full_text": "",
        }

    # ---------- 元信息 ----------
    def _extract_metadata(self, full_text: str, page_count: int) -> Dict[str, Any]:
        """从正文头部猜测标题/作者/摘要。"""
        lines = [l.strip() for l in full_text.splitlines() if l.strip()]
        title = lines[0] if lines else None
        abstract = None

        # 摘要提取：支持 Abstract / ABSTRACT / 摘要
        m = re.search(
            r"abstract[:：]?\s*(.+?)(?=\n\s*(?:1\s*\.?\s*introduction|keywords|index\s*terms|1\s+introduction|关键词))",
            full_text,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            abstract = m.group(1).strip()[:2000]

        # 作者提取：标题后、摘要前的行
        authors: List[str] = []
        if lines and len(lines) > 2:
            # 简单启发：标题后第一行非空且不是 Abstract 的行可能是作者
            for line in lines[1:5]:
                if line.lower().startswith("abstract"):
                    break
                if re.search(r"[a-zA-Z]", line) and len(line) < 200:
                    # 作者行通常包含逗号分隔的名字或邮箱
                    if "@" in line or "," in line or re.match(r"^[A-Z][a-z]+ [A-Z]", line):
                        authors.append(line)

        return {
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "page_count": page_count,
            "parsed_at": None,
        }

    # ---------- 参考文献（改进版） ----------
    def _extract_references(self, full_text: str) -> List[Dict[str, Any]]:
        """定位 References 区段，按编号切分并结构化。

        支持格式：
        - [1] Author, "Title," Journal, vol. X, pp. Y, Year.
        - 1. Author, "Title," Journal, Year.
        - [1] Author. Title. Journal, Year.
        """
        # 更宽松的定位：不要求严格的换行包围
        ref_start = -1
        for pattern in [
            r"(?im)^\s*(?:references|bibliography|参考\s*文献)\s*$",
            r"(?im)\n\s*(?:references|bibliography|参考\s*文献)\s*\n",
            r"(?i)\b(?:references|bibliography)\b",
        ]:
            m = re.search(pattern, full_text)
            if m:
                ref_start = m.end()
                break

        if ref_start == -1:
            logger.info("未找到 References 区段")
            return []

        ref_block = full_text[ref_start:]
        # 限制参考文献区段长度（避免把后面的附录也算进来）
        ref_block = ref_block[:8000]

        refs: List[Dict[str, Any]] = []

        # 按 [1] [2] 或 1. 2. 切分
        # 使用正向先行断言，匹配编号开头
        raw_entries = re.split(
            r"(?=\[\d+\]|\b\d+\.\s+[A-Z])",
            ref_block,
        )

        for entry in raw_entries:
            entry = entry.strip()
            # 过滤过短或非参考文献条目
            if len(entry) < 15:
                continue
            # 必须以编号开头
            if not re.match(r"^\[?\d+[\].]", entry):
                continue

            # 提取编号
            num_match = re.match(r"^\[?(\d+)[\].]", entry)
            ref_num = num_match.group(1) if num_match else None

            # 提取年份
            year_match = re.search(r"\b(19|20)\d{2}\b", entry)
            year = year_match.group(0) if year_match else None

            # 提取标题（引号内或首句）
            title = ""
            title_match = re.search(r'"([^"]{5,200})"', entry)
            if title_match:
                title = title_match.group(1)
            else:
                # 尝试提取第一个句子
                parts = re.split(r"[.?!]\s", entry, maxsplit=2)
                if len(parts) >= 2:
                    title = parts[1][:200]

            refs.append({
                "raw": entry[:500],
                "text": entry[:500],  # 兼容前端字段
                "number": ref_num,
                "year": year,
                "title": title,
            })

            if len(refs) >= 200:
                break

        logger.info("参考文献提取完成: %d 条", len(refs))
        return refs

    # ---------- 工具 ----------
    @staticmethod
    def _table_to_markdown(table: List[List[Optional[str]]]) -> str:
        """把 pdfplumber 的二维表格转 Markdown。"""
        if not table:
            return ""
        rows = [[(c or "").replace("\n", " ").strip() for c in row] for row in table]
        header = rows[0]
        lines = ["| " + " | ".join(header) + " |"]
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")
        for row in rows[1:]:
            row = row + [""] * (len(header) - len(row))
            lines.append("| " + " | ".join(row[: len(header)]) + " |")
        return "\n".join(lines)

    @staticmethod
    def _safe_json(text: str) -> Dict[str, Any]:
        """从 LLM 输出中稳健地解析 JSON（容忍 ```json 包裹）。"""
        if not text:
            return {}
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("JSON 解析失败，原文: %s", text[:200])
            return {}

    # ---------- 进度上报 ----------
    @staticmethod
    def _report_progress(
        on_progress: Optional[Callable[[str, int, str], None]],
        step: str,
        percent: int,
        message: str,
    ) -> None:
        """安全地上报解析进度，回调异常不会影响解析主流程。"""
        if on_progress is None:
            return
        try:
            on_progress(step, percent, message)
        except Exception:
            pass  # 进度回调失败不影响主流程

    # ---------- 结构化摘要 ----------
    def _build_structured_summary(self, result: Dict[str, Any]) -> Dict[str, str]:
        """调用 LLM 生成 purpose/methods/data/conclusion 四元组。"""
        full_text = result.get("full_text", "")
        if not full_text:
            return {}
        title = result.get("metadata", {}).get("title") or ""
        excerpt = full_text[:6000]
        try:
            out = model_loader.chat_text(
                prompts.SUMMARY_SYSTEM,
                prompts.SUMMARY_USER_TEMPLATE.format(title=title, text=excerpt),
            )
            parsed = self._safe_json(out)
            return {
                "purpose": parsed.get("purpose", ""),
                "methods": parsed.get("methods", ""),
                "data": parsed.get("data", ""),
                "conclusion": parsed.get("conclusion", ""),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("结构化摘要生成失败: %s", exc)
            return {}

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        return load_parsed_result(doc_id)


parser_service = ParserService()
