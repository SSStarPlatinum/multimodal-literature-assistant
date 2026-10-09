"""
Neo4j 知识图谱服务
==================
- 连接池管理（neo4j driver 单例）。
- 调用 LLM 从文献抽取实体/关系（JSON），解析后写 Cypher。
- 节点 schema: Concept / Algorithm / Dataset / Metric / Conclusion。
- 关系: USES / IMPROVES / EVALUATES_ON / ACHIEVES / COMPARES_WITH / PROPOSED_BY。
- 查询返回 ECharts 兼容的 nodes/links。
- 每个图谱用 graph_id 隔离（一个 :Graph {graph_id} 节点作为根，文献/实体挂在其下）。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.core.exceptions import (
    GraphNodeNotFoundError,
    GraphNotFoundError,
    GraphServiceError,
)
from app.core.logging import logger
from app.schemas.graph import (
    GraphLink,
    GraphNode,
    GraphResponse,
    GraphStats,
)
from app.services.model_loader import model_loader
from app.utils import prompts

settings = get_settings()

# 图谱人工校对操作日志目录：data/graph_logs/{graph_id}.jsonl
DATA_ROOT = Path(settings.UPLOAD_DIR).parent
GRAPH_LOGS_DIR = DATA_ROOT / "graph_logs"

# 节点类型 -> 标签名映射（统一首字母大写）
NODE_TYPE_TO_LABEL = {
    "concept": "Concept",
    "algorithm": "Algorithm",
    "dataset": "Dataset",
    "metric": "Metric",
    "conclusion": "Conclusion",
}

# 中文类型名 -> 英文类型名（LLM 可能返回中文）
CHINESE_TYPE_TO_EN = {
    "概念": "concept",
    "算法": "algorithm",
    "模型": "algorithm",
    "方法": "algorithm",
    "数据集": "dataset",
    "数据": "dataset",
    "指标": "metric",
    "评估指标": "metric",
    "结论": "conclusion",
    "实验结论": "conclusion",
}

# 关系类型 -> Cypher 关系名
REL_TYPE_TO_REL = {
    "uses": "USES",
    "improves": "IMPROVES",
    "evaluates_on": "EVALUATES_ON",
    "achieves": "ACHIEVES",
    "compares_with": "COMPARES_WITH",
    "proposed_by": "PROPOSED_BY",
}

# 中文关系名 -> 英文关系名
CHINESE_REL_TO_EN = {
    "使用": "uses",
    "改进": "improves",
    "提升": "improves",
    "评估于": "evaluates_on",
    "在...上评估": "evaluates_on",
    "达到": "achieves",
    "取得": "achieves",
    "对比": "compares_with",
    "比较": "compares_with",
    "提出者": "proposed_by",
    "由...提出": "proposed_by",
}


class GraphService:
    """Neo4j 知识图谱服务。"""

    def __init__(self) -> None:
        self._driver = None

    # ---------- 连接 ----------
    def _ensure_driver(self):
        if self._driver is not None:
            return self._driver
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover
            raise GraphServiceError("未安装 neo4j driver") from exc
        try:
            self._driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            )
            self._driver.verify_connectivity()
            logger.info("Neo4j 连接成功: %s", settings.NEO4J_URI)
        except Exception as exc:  # noqa: BLE001
            logger.error("Neo4j 连接失败: %s", exc)
            raise GraphServiceError(f"Neo4j 连接失败: {exc}") from exc
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()

    # ---------- 构建 ----------
    def build_graph(
        self,
        document_ids: List[str],
        parsed_docs: Dict[str, Dict[str, Any]],
        entity_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        对给定文献集合构建一张图谱。
        parsed_docs: {doc_id: 解析结果 dict}
        """
        self._ensure_driver()
        graph_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        name = f"图谱-{now[:10]}"

        # 创建图谱根节点
        with self._driver.session(database=settings.NEO4J_DATABASE) as session:
            session.run(
                "CREATE (g:Graph {graph_id: $gid, name: $name, created_at: $now})",
                gid=graph_id,
                name=name,
                now=now,
            )

        total_nodes = 0
        total_rels = 0
        for doc_id in document_ids:
            doc = parsed_docs.get(doc_id)
            if not doc:
                logger.warning("构建图谱跳过未解析文档: %s", doc_id)
                continue
            n, r = self._extract_and_write(doc_id, doc, graph_id, entity_types or list(NODE_TYPE_TO_LABEL.keys()))
            total_nodes += n
            total_rels += r

        return {
            "graph_id": graph_id,
            "status": "completed",
            "stats": {"nodes": total_nodes, "relationships": total_rels},
        }

    def _extract_and_write(
        self,
        doc_id: str,
        doc: Dict[str, Any],
        graph_id: str,
        entity_types: List[str],
    ) -> tuple:
        """对单篇文献做实体/关系抽取并写库。返回 (节点数, 关系数)。"""
        title = doc.get("metadata", {}).get("title", "")
        full_text = doc.get("full_text", "") or ""

        # 兜底：如果 full_text 为空，用 text_blocks 拼接
        if not full_text.strip():
            blocks = doc.get("text_blocks", [])
            full_text = "\n".join(
                b.get("content", "") if isinstance(b, dict) else str(b)
                for b in blocks
            )
            logger.info("文档 %s full_text 为空，使用 text_blocks 拼接 (%d 字符)", doc_id, len(full_text))

        if not full_text.strip():
            logger.warning("文档 %s 无文本内容，跳过图谱抽取", doc_id)
            return 0, 0

        excerpt = full_text[:8000]  # 增加到 8000 字符，覆盖更多内容

        # ---- LLM 抽取（带重试） ----
        parsed: Dict[str, Any] = {}
        raw = ""
        for attempt in range(2):
            try:
                raw = model_loader.chat_text(
                    prompts.GRAPH_EXTRACT_SYSTEM,
                    prompts.GRAPH_EXTRACT_USER_TEMPLATE.format(
                        title=title, text=excerpt, page=1
                    ),
                )
                logger.info("文档 %s 图谱抽取 LLM 返回 (第%d次, %d字符): %s",
                            doc_id, attempt + 1, len(raw), raw[:300])
                parsed = self._safe_json(raw)
                if parsed.get("nodes"):
                    break
                logger.warning("文档 %s 第%d次抽取节点为空，重试", doc_id, attempt + 1)
            except Exception as exc:  # noqa: BLE001
                logger.error("文档 %s 实体抽取调用失败 (第%d次): %s", doc_id, attempt + 1, exc)
                if attempt == 1:
                    return 0, 0

        nodes = parsed.get("nodes", [])
        edges = parsed.get("edges", [])
        logger.info("文档 %s 抽取结果: nodes=%d, edges=%d", doc_id, len(nodes), len(edges))

        if not nodes:
            logger.warning("文档 %s 抽取后无有效节点，LLM原始返回前500字符: %s",
                           doc_id, raw[:500])
            return 0, 0

        created_nodes = 0
        created_rels = 0
        with self._driver.session(database=settings.NEO4J_DATABASE) as session:
            # 写入文献节点
            session.run(
                """
                MERGE (d:Document {doc_id: $did})
                SET d.title = $title, d.source_document = $did
                WITH d
                MATCH (g:Graph {graph_id: $gid})
                MERGE (g)-[:CONTAINS_DOC]->(d)
                """,
                did=doc_id,
                title=title,
                gid=graph_id,
            )

            node_name_map: Dict[str, str] = {}  # name -> element_id
            for node in nodes:
                ntype = (node.get("type") or "").strip().lower()
                # 中文类型名映射
                if ntype in CHINESE_TYPE_TO_EN:
                    ntype = CHINESE_TYPE_TO_EN[ntype]
                # 容错：如果类型不在预定义列表，尝试模糊匹配或降级为 concept
                if ntype not in NODE_TYPE_TO_LABEL:
                    # 模糊匹配：包含关键词
                    for key in NODE_TYPE_TO_LABEL:
                        if key in ntype:
                            ntype = key
                            break
                    else:
                        logger.debug("节点类型 '%s' 不在预定义列表，降级为 concept", ntype)
                        ntype = "concept"
                label = NODE_TYPE_TO_LABEL[ntype]
                name = (node.get("name") or "").strip()
                if not name:
                    continue
                desc = node.get("description", "")
                page = node.get("page_number", 1)
                try:
                    rec = session.run(
                        f"""
                        MATCH (g:Graph {{graph_id: $gid}})
                        MERGE (n:{label} {{name: $name, source_document: $did}})
                        SET n.description = $desc, n.page_number = $page, n.type = $ntype
                        MERGE (g)-[:CONTAINS_NODE]->(n)
                        RETURN elementId(n) AS eid
                        """,
                        gid=graph_id,
                        name=name,
                        did=doc_id,
                        desc=desc,
                        page=page,
                        ntype=ntype,
                    ).single()
                    if rec:
                        node_name_map[name] = rec["eid"]
                        created_nodes += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("写入节点失败 %s: %s", name, exc)

            for edge in edges:
                src = (edge.get("source") or "").strip()
                tgt = (edge.get("target") or "").strip()
                rel_raw = (edge.get("relation") or "").strip()
                # 中文关系名映射
                rel_en = CHINESE_REL_TO_EN.get(rel_raw, rel_raw.lower())
                rel = REL_TYPE_TO_REL.get(rel_en, "").upper()
                if not rel:
                    # 容错：尝试模糊匹配
                    for key, val in REL_TYPE_TO_REL.items():
                        if key in rel_en or val.lower() in rel_en:
                            rel = val
                            break
                if not src or not tgt or not rel:
                    logger.debug("跳过无效关系: src=%s, tgt=%s, rel=%s", src, tgt, rel_raw)
                    continue
                src_id = node_name_map.get(src)
                tgt_id = node_name_map.get(tgt)
                if not src_id or not tgt_id:
                    logger.debug("关系端点未找到节点: %s(%s) -> %s(%s)",
                                 src, "found" if src_id else "missing",
                                 tgt, "found" if tgt_id else "missing")
                    continue
                try:
                    session.run(
                        f"""
                        MATCH (a), (b)
                        WHERE elementId(a) = $src_id AND elementId(b) = $tgt_id
                        MERGE (a)-[r:{rel}]->(b)
                        SET r.source_document = $did
                        """,
                        src_id=src_id,
                        tgt_id=tgt_id,
                        did=doc_id,
                    )
                    created_rels += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("写入关系失败 %s->%s: %s", src, tgt, exc)

            # PROPOSED_BY: 每个节点都连到文献
            session.run(
                """
                MATCH (g:Graph {graph_id: $gid})-[:CONTAINS_NODE]->(n)
                MATCH (d:Document {doc_id: $did})
                MERGE (n)-[:PROPOSED_BY]->(d)
                """,
                gid=graph_id,
                did=doc_id,
            )

        logger.info(
            "文档 %s 图谱写入: nodes=%d, rels=%d", doc_id, created_nodes, created_rels
        )
        return created_nodes, created_rels

    # ---------- 查询 ----------
    def get_graph(
        self, graph_id: str, limit: int = 200, node_type: Optional[str] = None
    ) -> GraphResponse:
        self._ensure_driver()
        label = NODE_TYPE_TO_LABEL.get((node_type or "").lower())

        with self._driver.session(database=settings.NEO4J_DATABASE) as session:
            # 检查存在
            exists = session.run(
                "MATCH (g:Graph {graph_id: $gid}) RETURN g", gid=graph_id
            ).single()
            if not exists:
                raise GraphNotFoundError(f"图谱不存在: {graph_id}")

            # 取节点
            if label:
                node_q = f"""
                MATCH (g:Graph {{graph_id: $gid}})-[:CONTAINS_NODE]->(n:{label})
                RETURN elementId(n) AS eid, n.name AS name, n.type AS type,
                       n.description AS desc, n.source_document AS src, n.page_number AS page
                LIMIT $lim
                """
            else:
                node_q = """
                MATCH (g:Graph {graph_id: $gid})-[:CONTAINS_NODE]->(n)
                RETURN elementId(n) AS eid, n.name AS name, n.type AS type,
                       n.description AS desc, n.source_document AS src, n.page_number AS page
                LIMIT $lim
                """
            nodes: List[GraphNode] = []
            node_eids = set()
            for rec in session.run(node_q, gid=graph_id, lim=limit):
                eid = rec["eid"]
                node_eids.add(eid)
                nodes.append(
                    GraphNode(
                        id=eid,
                        label=rec["name"] or "",
                        type=rec["type"] or "concept",
                        properties={
                            "description": rec["desc"] or "",
                            "source_document": rec["src"] or "",
                            "page_number": rec["page"],
                        },
                    )
                )

            # 取边（两端都在已取节点集合内）
            links: List[GraphLink] = []
            if node_eids:
                link_q = """
                MATCH (a)-[r]->(b)
                WHERE elementId(a) IN $eids AND elementId(b) IN $eids
                RETURN elementId(a) AS src, elementId(b) AS tgt, type(r) AS rel
                """
                for rec in session.run(link_q, eids=list(node_eids)):
                    links.append(
                        GraphLink(
                            source=rec["src"],
                            target=rec["tgt"],
                            type=rec["rel"].lower(),
                            properties={},
                        )
                    )

            # 统计
            stats_rec = session.run(
                """
                MATCH (g:Graph {graph_id: $gid})-[:CONTAINS_NODE]->(n)
                WITH count(n) AS nn
                OPTIONAL MATCH (g)-[:CONTAINS_NODE]->(a)-[r]->(b)
                RETURN nn, count(DISTINCT r) AS rr
                """,
                gid=graph_id,
            ).single()
            stats = GraphStats(
                nodes=stats_rec["nn"] if stats_rec else 0,
                relationships=stats_rec["rr"] if stats_rec else 0,
            )

        return GraphResponse(
            graph_id=graph_id, nodes=nodes, links=links, stats=stats
        )

    def list_graphs(self) -> List[Dict[str, Any]]:
        self._ensure_driver()
        with self._driver.session(database=settings.NEO4J_DATABASE) as session:
            recs = session.run(
                """
                MATCH (g:Graph)
                OPTIONAL MATCH (g)-[:CONTAINS_NODE]->(n)
                RETURN g.graph_id AS gid, g.name AS name, g.created_at AS created_at,
                       count(n) AS node_count
                ORDER BY g.created_at DESC
                """
            )
            return [
                {
                    "graph_id": r["gid"],
                    "name": r["name"],
                    "created_at": r["created_at"],
                    "node_count": r["node_count"],
                }
                for r in recs
            ]

    def delete_graph(self, graph_id: str) -> bool:
        self._ensure_driver()
        with self._driver.session(database=settings.NEO4J_DATABASE) as session:
            exists = session.run(
                "MATCH (g:Graph {graph_id: $gid}) RETURN g", gid=graph_id
            ).single()
            if not exists:
                raise GraphNotFoundError(f"图谱不存在: {graph_id}")
            # 删图谱根 + 其下所有节点与关系
            # 注意：必须用 OPTIONAL MATCH，否则0节点图谱时 MATCH 为空导致后续不执行
            session.run(
                """
                MATCH (g:Graph {graph_id: $gid})
                // 删除 CONTAINS_NODE 下的所有实体节点及其关系
                OPTIONAL MATCH (g)-[:CONTAINS_NODE]->(n)
                DETACH DELETE n
                WITH g
                // 删除 CONTAINS_DOC 下的文献节点及其关系
                OPTIONAL MATCH (g)-[:CONTAINS_DOC]->(d)
                DETACH DELETE d
                WITH g
                // 最后删除图谱根节点
                DETACH DELETE g
                """,
                gid=graph_id,
            )
            logger.info("图谱已删除: %s", graph_id)
        return True

    # ---------- P1-3: 人工校对（节点/关系的增删改 + 操作日志） ----------
    @staticmethod
    def _log_operation(
        graph_id: str,
        operation: str,
        target_id: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """把一次人工校对操作追加写入 data/graph_logs/{graph_id}.jsonl。

        每行一个 JSON 对象，包含 UTC ISO 时间戳。日志必须持久化，不能只放内存。
        """
        GRAPH_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_path = GRAPH_LOGS_DIR / f"{graph_id}.jsonl"
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "target_id": target_id,
            "details": details or {},
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info("图谱 %s 人工校对: %s target=%s", graph_id, operation, target_id)

    def _ensure_graph_exists(self, session, graph_id: str) -> None:
        """校验图谱根节点存在，否则抛 GraphNotFoundError。"""
        if not session.run(
            "MATCH (g:Graph {graph_id: $gid}) RETURN g", gid=graph_id
        ).single():
            raise GraphNotFoundError(f"图谱不存在: {graph_id}")

    def update_node(
        self,
        graph_id: str,
        node_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """按 elementId 更新节点的 name/description/type。

        - type 变更时：移除旧 Label、挂载新 Label（动态 Label 来自白名单，安全）。
        - 记录操作日志。
        """
        self._ensure_driver()
        with self._driver.session(database=settings.NEO4J_DATABASE) as session:
            # 1) 校验图谱存在
            if not session.run(
                "MATCH (g:Graph {graph_id: $gid}) RETURN g", gid=graph_id
            ).single():
                raise GraphNotFoundError(f"图谱不存在: {graph_id}")

            # 2) 定位节点（必须挂在该图谱下，避免跨图谱误改），取当前类型
            cur = session.run(
                """
                MATCH (g:Graph {graph_id: $gid})-[:CONTAINS_NODE]->(n)
                WHERE elementId(n) = $nid
                RETURN n.name AS name, n.type AS type, n.description AS desc
                """,
                gid=graph_id,
                nid=node_id,
            ).single()
            if not cur:
                raise GraphNodeNotFoundError(f"节点不存在或不属于该图谱: {node_id}")

            old_type = cur["type"] or "concept"
            set_clauses: List[str] = []
            params: Dict[str, Any] = {"nid": node_id}

            if name is not None:
                set_clauses.append("n.name = $name")
                params["name"] = name
            if description is not None:
                set_clauses.append("n.description = $desc")
                params["desc"] = description

            # 3) 类型变更：REMOVE 旧 Label / SET 新 Label
            label_action = ""
            if type is not None and type != old_type and type in NODE_TYPE_TO_LABEL:
                old_label = NODE_TYPE_TO_LABEL[old_type]
                new_label = NODE_TYPE_TO_LABEL[type]
                label_action = f"REMOVE n:`{old_label}` SET n:`{new_label}` "
                set_clauses.append("n.type = $ntype")
                params["ntype"] = type

            if set_clauses:
                cypher = (
                    "MATCH (n) WHERE elementId(n) = $nid "
                    f"SET {', '.join(set_clauses)} {label_action}"
                )
                session.run(cypher, **params)
                logger.info(
                    "节点 %s 已更新: name=%s, type: %s -> %s",
                    node_id, name, old_type, type or old_type,
                )

            # 4) 回读最新节点信息
            fresh = session.run(
                """
                MATCH (n) WHERE elementId(n) = $nid
                RETURN elementId(n) AS eid, n.name AS name,
                       n.type AS type, n.description AS desc
                """,
                nid=node_id,
            ).single()
            result = {
                "id": fresh["eid"],
                "name": fresh["name"] or "",
                "type": fresh["type"] or old_type,
                "description": fresh["desc"] or "",
            }

        self._log_operation(
            graph_id,
            "update_node",
            node_id,
            {"name": name, "type": type, "old_type": old_type},
        )
        return result

    def delete_node(self, graph_id: str, node_id: str) -> bool:
        """按 elementId 删除节点，DETACH DELETE 连带删除全部关系。"""
        self._ensure_driver()
        with self._driver.session(database=settings.NEO4J_DATABASE) as session:
            if not session.run(
                "MATCH (g:Graph {graph_id: $gid}) RETURN g", gid=graph_id
            ).single():
                raise GraphNotFoundError(f"图谱不存在: {graph_id}")
            rec = session.run(
                """
                MATCH (g:Graph {graph_id: $gid})-[:CONTAINS_NODE]->(n)
                WHERE elementId(n) = $nid
                RETURN elementId(n) AS eid
                """,
                gid=graph_id,
                nid=node_id,
            ).single()
            if not rec:
                raise GraphNodeNotFoundError(f"节点不存在或不属于该图谱: {node_id}")
            # DETACH DELETE：连同所有关系一起删除
            session.run(
                "MATCH (n) WHERE elementId(n) = $nid DETACH DELETE n",
                nid=node_id,
            )
        self._log_operation(graph_id, "delete_node", node_id, {})
        return True

    def create_node(
        self, graph_id: str, name: str, description: str, type: str
    ) -> Dict[str, Any]:
        """在指定图谱下新建实体节点，并通过 CONTAINS_NODE 挂到图谱根。"""
        self._ensure_driver()
        label = NODE_TYPE_TO_LABEL[type]  # 白名单，安全拼接到 Cypher
        with self._driver.session(database=settings.NEO4J_DATABASE) as session:
            if not session.run(
                "MATCH (g:Graph {graph_id: $gid}) RETURN g", gid=graph_id
            ).single():
                raise GraphNotFoundError(f"图谱不存在: {graph_id}")
            rec = session.run(
                f"""
                MATCH (g:Graph {{graph_id: $gid}})
                CREATE (n:`{label}` {{name: $name, description: $desc, type: $ntype}})
                MERGE (g)-[:CONTAINS_NODE]->(n)
                RETURN elementId(n) AS eid, n.name AS name,
                       n.type AS type, n.description AS desc
                """,
                gid=graph_id,
                name=name,
                desc=description,
                ntype=type,
            ).single()
            result = {
                "id": rec["eid"],
                "name": rec["name"],
                "type": rec["type"],
                "description": rec["desc"] or "",
            }
        self._log_operation(
            graph_id, "create_node", result["id"],
            {"name": name, "type": type},
        )
        logger.info("图谱 %s 新建节点: %s (%s)", graph_id, name, type)
        return result

    def create_edge(
        self, graph_id: str, source_eid: str, target_eid: str, relation: str
    ) -> Dict[str, Any]:
        """在两端节点间创建关系，relation 小写入参转为大写关系名。"""
        self._ensure_driver()
        rel = REL_TYPE_TO_REL[relation.lower()]  # 白名单映射
        with self._driver.session(database=settings.NEO4J_DATABASE) as session:
            if not session.run(
                "MATCH (g:Graph {graph_id: $gid}) RETURN g", gid=graph_id
            ).single():
                raise GraphNotFoundError(f"图谱不存在: {graph_id}")
            rec = session.run(
                f"""
                MATCH (a), (b)
                WHERE elementId(a) = $src AND elementId(b) = $tgt
                MERGE (a)-[r:`{rel}`]->(b)
                RETURN elementId(a) AS src, elementId(b) AS tgt, type(r) AS rel
                """,
                src=source_eid,
                tgt=target_eid,
            ).single()
            if not rec:
                raise GraphNodeNotFoundError(
                    f"关系端点节点不存在: {source_eid} / {target_eid}"
                )
            result = {
                "source": rec["src"],
                "target": rec["tgt"],
                "relation": rec["rel"],
            }
        self._log_operation(
            graph_id, "create_edge", source_eid,
            {"target": target_eid, "relation": rel},
        )
        logger.info("图谱 %s 新建关系: %s -[%s]-> %s",
                    graph_id, source_eid, rel, target_eid)
        return result

    def get_operation_logs(self, graph_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """读取图谱人工校对操作日志，默认返回最近 limit 条（新的在前）。"""
        log_path = GRAPH_LOGS_DIR / f"{graph_id}.jsonl"
        if not log_path.exists():
            return []
        entries: List[Dict[str, Any]] = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("跳过无法解析的日志行: %s", line[:100])
        # 最近 limit 条，按时间倒序（最新在前）
        return list(reversed(entries[-limit:]))

    @staticmethod
    def _safe_json(text: str) -> Dict[str, Any]:
        """从 LLM 输出中稳健地解析 JSON。

        处理情况：
        - ```json ... ``` 包裹
        - JSON 前后有解释性文字
        - 多个 JSON 对象（取第一个包含 nodes 字段的）
        - 转义的引号和换行
        """
        import json
        import re

        if not text:
            return {}
        cleaned = text.strip()

        # 去除 markdown 代码块标记
        cleaned = re.sub(r"^```(?:json|JSON)?\s*", "", cleaned).strip()
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

        # 尝试1：直接解析
        try:
            result = json.loads(cleaned)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # 尝试2：截取第一个 { 到最后一个 }
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = cleaned[start : end + 1]
            try:
                result = json.loads(candidate)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        # 尝试3：逐段查找合法 JSON（处理 LLM 返回多个对象的情况）
        depth = 0
        start_idx = -1
        for i, ch in enumerate(cleaned):
            if ch == "{":
                if depth == 0:
                    start_idx = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start_idx != -1:
                    candidate = cleaned[start_idx : i + 1]
                    try:
                        result = json.loads(candidate)
                        if isinstance(result, dict) and "nodes" in result:
                            return result
                    except json.JSONDecodeError:
                        pass
                    start_idx = -1

        # 尝试4：修复常见的 LLM JSON 错误（尾逗号、单引号）
        if start != -1 and end != -1:
            candidate = cleaned[start : end + 1]
            # 移除尾逗号
            candidate = re.sub(r",\s*}", "}", candidate)
            candidate = re.sub(r",\s*]", "]", candidate)
            try:
                result = json.loads(candidate)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        logger.warning("图谱抽取 JSON 解析失败，原文前500字符: %s", text[:500])
        return {}

    def health(self) -> str:
        try:
            self._ensure_driver()
            with self._driver.session(database=settings.NEO4J_DATABASE) as s:
                s.run("RETURN 1").single()
            return "connected"
        except Exception:  # noqa: BLE001
            return "disconnected"


graph_service = GraphService()
