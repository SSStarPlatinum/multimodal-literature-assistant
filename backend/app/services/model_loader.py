"""
模型加载器（单例）
==================
统一管理三类模型资源：
1. Qwen2.5-VL 多模态模型 —— local 模式用 transformers + bitsandbytes 4-bit 加载；
   api 模式走 OpenAI 兼容客户端（DashScope）。
2. BGE-M3 嵌入模型 —— sentence-transformers 加载。
3. bge-reranker —— sentence-transformers CrossEncoder 加载。

所有模型在进程内懒加载、全局共享，避免重复占用显存/内存。
"""
from __future__ import annotations

import base64
import io
import threading
from typing import List, Optional

from app.core.config import get_settings
from app.core.exceptions import ModelInferenceError
from app.core.logging import logger

settings = get_settings()


class ModelLoader:
    """模型单例加载器。线程安全。"""

    _lock = threading.Lock()

    def __init__(self) -> None:
        self._vl_processor = None
        self._vl_model = None
        self._embed_model = None
        self._reranker = None
        self._openai_client = None
        self._loaded = False

    # ---------- OpenAI 兼容客户端（api 模式）----------
    def _get_openai_client(self):
        if self._openai_client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover
                raise ModelInferenceError(
                    "未安装 openai 库，api 模式依赖 openai>=1.0"
                ) from exc
            self._openai_client = OpenAI(
                base_url=settings.QWEN_API_BASE,
                api_key=settings.QWEN_API_KEY or "NOT_SET",
            )
        return self._openai_client

    # ---------- 本地 VL 模型 ----------
    def _ensure_local_vl(self) -> None:
        """local 模式下懒加载 Qwen2.5-VL。"""
        if self._vl_model is not None:
            return
        with self._lock:
            if self._vl_model is not None:
                return
            try:
                import torch
                from transformers import (
                    AutoProcessor,
                    BitsAndBytesConfig,
                )

                model_path = settings.QWEN_MODEL_PATH
                logger.info("正在加载本地 VL 模型: %s", model_path)

                # 4-bit 量化配置
                quant_config = None
                if settings.ENABLE_4BIT_QUANTIZATION and settings.LOAD_IN_4BIT:
                    compute_dtype = getattr(
                        torch, settings.BNB_4BIT_COMPUTE_DTYPE, torch.float16
                    )
                    quant_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=compute_dtype,
                        bnb_4bit_quant_type=settings.BNB_4BIT_QUANT_TYPE,
                        bnb_4bit_use_double_quant=settings.BNB_4BIT_USE_NESTED_QUANT,
                    )
                    logger.info("已启用 4-bit 量化: %s", settings.BNB_4BIT_QUANT_TYPE)

                # Qwen2.5-VL 模型类名在不同 transformers 版本不同，做兼容导入
                try:
                    from transformers import Qwen2_5_VLForConditionalGeneration as VLModel
                except ImportError:
                    from transformers import (
                        Qwen2VLForConditionalGeneration as VLModel,
                    )

                self._vl_processor = AutoProcessor.from_pretrained(model_path)
                self._vl_model = VLModel.from_pretrained(
                    model_path,
                    quantization_config=quant_config,
                    device_map="auto",
                    torch_dtype=torch.float16 if quant_config is None else None,
                    trust_remote_code=True,
                )
                logger.info("本地 VL 模型加载完成")
            except Exception as exc:  # noqa: BLE001
                logger.exception("本地 VL 模型加载失败")
                raise ModelInferenceError(f"VL 模型加载失败: {exc}") from exc

    # ---------- 嵌入模型 BGE-M3 ----------
    def get_embed_model(self):
        """获取 BGE-M3 sentence-transformers 模型（单例）。

        加载策略：
        1. 如果本地路径 EMBEDDING_MODEL_PATH 存在，直接加载
        2. 否则使用模型名称 EMBEDDING_MODEL_NAME 从 HuggingFace 在线下载
           （通过 HF_ENDPOINT 环境变量可配置国内镜像，如 https://hf-mirror.com）
        """
        if self._embed_model is None:
            with self._lock:
                if self._embed_model is None:
                    try:
                        from sentence_transformers import SentenceTransformer
                    except ImportError as exc:  # pragma: no cover
                        raise ModelInferenceError(
                            "未安装 sentence-transformers"
                        ) from exc

                    import os
                    local_path = settings.EMBEDDING_MODEL_PATH
                    model_name = settings.EMBEDDING_MODEL_NAME

                    if os.path.isdir(local_path):
                        logger.info("正在加载嵌入模型(本地): %s", local_path)
                        self._embed_model = SentenceTransformer(
                            local_path, device=settings.EMBEDDING_DEVICE
                        )
                    else:
                        logger.info(
                            "本地路径 %s 不存在，从 HuggingFace 下载: %s (HF_ENDPOINT=%s)",
                            local_path, model_name,
                            os.environ.get("HF_ENDPOINT", "default"),
                        )
                        self._embed_model = SentenceTransformer(
                            model_name, device=settings.EMBEDDING_DEVICE
                        )
                        # 下载成功后保存到本地路径，避免重复下载
                        try:
                            os.makedirs(local_path, exist_ok=True)
                            self._embed_model.save(local_path)
                            logger.info("嵌入模型已缓存到: %s", local_path)
                        except Exception as save_exc:  # noqa: BLE001
                            logger.warning("嵌入模型缓存失败(不影响使用): %s", save_exc)
                    logger.info("嵌入模型加载完成")
        return self._embed_model

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """批量文本嵌入。"""
        if not texts:
            return []
        model = self.get_embed_model()
        emb = model.encode(
            texts,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return emb.tolist()

    def embed_query(self, text: str) -> List[float]:
        """单条查询嵌入。"""
        return self.embed_texts([text])[0]

    # ---------- Reranker ----------
    def get_reranker(self):
        """获取 bge-reranker CrossEncoder（单例）。"""
        if self._reranker is None:
            with self._lock:
                if self._reranker is None:
                    try:
                        from sentence_transformers import CrossEncoder
                    except ImportError as exc:  # pragma: no cover
                        raise ModelInferenceError(
                            "未安装 sentence-transformers (CrossEncoder)"
                        ) from exc
                    logger.info("正在加载 reranker: %s", settings.RERANK_MODEL_NAME)
                    self._reranker = CrossEncoder(
                        settings.RERANK_MODEL_NAME, device=settings.RERANK_DEVICE
                    )
                    logger.info("reranker 加载完成")
        return self._reranker

    def rerank(self, query: str, documents: List[str], top_n: Optional[int] = None):
        """对 (query, doc) 对重排序，返回 [(index, score), ...]。"""
        if not documents:
            return []
        ranker = self.get_reranker()
        pairs = [(query, d) for d in documents]
        scores = ranker.predict(pairs)
        indexed = list(enumerate(scores))
        indexed.sort(key=lambda x: x[1], reverse=True)
        if top_n:
            indexed = indexed[:top_n]
        return [(int(i), float(s)) for i, s in indexed]

    # ---------- 文本生成（纯文本，摘要/抽取/综述）----------
    def chat_text(self, system_prompt: str, user_prompt: str) -> str:
        """纯文本对话。api 模式走 DashScope；local 模式复用 VL 模型的文本能力。"""
        if settings.use_local_model:
            return self._chat_text_local(system_prompt, user_prompt)
        return self._chat_text_api(system_prompt, user_prompt)

    def _chat_text_api(self, system_prompt: str, user_prompt: str) -> str:
        client = self._get_openai_client()
        try:
            resp = client.chat.completions.create(
                model=settings.QWEN_TEXT_API_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
            )
            message = resp.choices[0].message
            content = message.content or ""
            # 推理模型（如 deepseek-reasoner / v4-pro）可能把思考过程放在 reasoning_content
            if not content and hasattr(message, "reasoning_content") and message.reasoning_content:
                logger.warning("LLM content 为空，使用 reasoning_content 作为兜底")
                content = message.reasoning_content
            if not content:
                logger.warning(
                    "LLM 返回空内容 (model=%s, finish_reason=%s)",
                    settings.QWEN_TEXT_API_MODEL,
                    getattr(resp.choices[0], "finish_reason", "unknown"),
                )
            return content
        except Exception as exc:  # noqa: BLE001
            logger.exception("API 文本生成失败")
            raise ModelInferenceError(f"文本生成 API 调用失败: {exc}") from exc

    def _chat_text_local(self, system_prompt: str, user_prompt: str) -> str:
        self._ensure_local_vl()
        try:
            import torch

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            text = self._vl_processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self._vl_processor(
                text=[text], return_tensors="pt"
            ).to(self._vl_model.device)
            with torch.no_grad():
                out = self._vl_model.generate(
                    **inputs,
                    max_new_tokens=settings.LLM_MAX_TOKENS,
                    temperature=settings.LLM_TEMPERATURE,
                )
            trimmed = out[0][inputs["input_ids"].shape[1]:]
            return self._vl_processor.decode(trimmed, skip_special_tokens=True)
        except Exception as exc:  # noqa: BLE001
            logger.exception("本地文本生成失败")
            raise ModelInferenceError(f"本地文本生成失败: {exc}") from exc

    # ---------- 多模态生成（图片 + prompt）----------
    def chat_with_image(self, prompt: str, image_bytes: bytes) -> str:
        """图文对话。api 模式把图片 base64 后传给 OpenAI 兼容接口。"""
        if not settings.VISION_ENABLED:
            raise ModelInferenceError(
                "当前模型不支持视觉输入（VISION_ENABLED=false）。"
                "图片公式/图表识别已跳过，文本型 PDF 仍可正常解析。"
            )
        if settings.use_local_model:
            return self._chat_image_local(prompt, image_bytes)
        return self._chat_image_api(prompt, image_bytes)

    def _image_to_data_url(self, image_bytes: bytes) -> str:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:image/png;base64,{b64}"

    def _chat_image_api(self, prompt: str, image_bytes: bytes) -> str:
        client = self._get_openai_client()
        data_url = self._image_to_data_url(image_bytes)
        try:
            resp = client.chat.completions.create(
                model=settings.QWEN_API_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_url}},
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            logger.exception("API 图文生成失败")
            raise ModelInferenceError(f"图文 API 调用失败: {exc}") from exc

    def _chat_image_local(self, prompt: str, image_bytes: bytes) -> str:
        self._ensure_local_vl()
        try:
            import torch
            from PIL import Image

            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
            text = self._vl_processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self._vl_processor(
                text=[text], images=[image], return_tensors="pt"
            ).to(self._vl_model.device)
            with torch.no_grad():
                out = self._vl_model.generate(
                    **inputs, max_new_tokens=settings.LLM_MAX_TOKENS
                )
            trimmed = out[0][inputs["input_ids"].shape[1]:]
            return self._vl_processor.decode(trimmed, skip_special_tokens=True)
        except Exception as exc:  # noqa: BLE001
            logger.exception("本地图文生成失败")
            raise ModelInferenceError(f"本地图文生成失败: {exc}") from exc

    # ---------- 健康检查用的模型名 ----------
    def model_label(self) -> str:
        if settings.use_local_model:
            suffix = " (4-bit)" if settings.ENABLE_4BIT_QUANTIZATION else ""
            return f"{settings.QWEN_MODEL_NAME}{suffix}"
        return f"{settings.QWEN_API_MODEL} (api)"


# 全局单例
model_loader = ModelLoader()
