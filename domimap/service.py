"""service — CLI / MCP / UI 共用的应用服务（product#6：查询语义、范围、新鲜度、错误状态三入口一致）。

此前三入口各自装配 Graph/Searcher/seeds、各自硬编码默认参数（UI expand=False、kg_doc_search 8/6000 无 seeds
且不记录）、各自实现热重载（MCP 有、UI 无、CLI 每进程）、影响面预算只在 MCP 执行。本模块是唯一的默认参数与
装配点：入口只做协议映射（exit code / isError / HTTP status），不再持有检索逻辑。
"""
import json
import os

from .graph import Graph, load_seeds
from .search import Searcher

QUERY_DEFAULTS = {"top_k": 6, "expand": True, "budget": 3800, "min_cov": 0.3, "domain": None}
DOC_SEARCH_DEFAULTS = {"top_k": 8, "expand": False, "budget": 6000}  # 文档检索：更宽候选、更大文本预算
IMPACT_DEFAULT_DEPTH = 2
IMPACT_MAX_NODES = 200
IMPACT_MAX_DEPTH = 8
SEEDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.json")


class ServiceError(ValueError):
    """入口可直接映射的有界错误：code ∈ invalid_params | not_found | conflict | exists | unavailable | internal。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


AS_OF_MAX = 4102444800  # 2100-01-01：超出视为非法而不是静默接受


def parse_as_of(value):
    """as_of 统一解析（三入口同语义）：None/"" → None；epoch 秒（数值）或 'YYYY-MM-DD'（UTC 零点）。"""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ServiceError("invalid_params", "as_of 须为 epoch 秒或 YYYY-MM-DD")
    if isinstance(value, (int, float)):
        v = float(value)
        if 0 <= v <= AS_OF_MAX and v >= 946684800:  # 2000-01-01 起：更早的数值几乎总是单位或字段错误
            return v
        raise ServiceError("invalid_params", "as_of 超出范围（2000-01-01 ~ 2100-01-01 的 epoch 秒）")
    import calendar
    import time as _t
    try:
        return float(calendar.timegm(_t.strptime(str(value).strip(), "%Y-%m-%d")))
    except ValueError:
        raise ServiceError("invalid_params", "as_of 须为 epoch 秒或 YYYY-MM-DD")


class AppService:
    def __init__(self, graph_path):
        self.graph_path = os.path.abspath(graph_path)
        self.ws = os.path.dirname(self.graph_path)
        self._sig = None
        self.reload()

    # ---------- 装配与热重载 ----------
    def _signature(self):
        sig = []
        for name in (self.graph_path, os.path.join(self.ws, "knowledge.db"), os.path.join(self.ws, "store.db")):
            try:
                st = os.stat(name)
                sig.append((st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append(None)
        return tuple(sig)

    def reload(self):
        from .knowledge import attach_if_present
        from .store import EvidenceResolver
        self.g = Graph.load(self.graph_path)
        coverage = {}
        cov = os.path.join(self.ws, "coverage.json")
        if os.path.exists(cov):
            try:
                with open(cov, encoding="utf-8") as f:
                    coverage = json.load(f)
            except (OSError, ValueError):
                coverage = {}
        self.s = Searcher(self.g, cache_path=self.graph_path + ".idx.json", coverage=coverage)
        attach_if_present(self.s, self.graph_path)  # 图旁 knowledge.db（人工/LLM 笔记）
        self.seeds = load_seeds(SEEDS_PATH)
        self.resolver = EvidenceResolver.beside(self.graph_path)
        self._sig = self._signature()
        return self

    def refresh(self, force=False):
        """graph.json / knowledge.db / store.db 任一变化即重建；返回是否重建（长驻 MCP/UI 不需重启）。"""
        if force or self._signature() != self._sig:
            self.reload()
            return True
        return False

    # ---------- 查询 ----------
    def query(self, text, entry, **overrides):
        """主查询：三入口同一默认参数 + 同一观测记录。返回 (result, obs)。"""
        from .observation import run_query
        if not isinstance(text, str) or not text.strip():
            raise ServiceError("invalid_params", "空查询")
        params = dict(QUERY_DEFAULTS)
        params.update({k: v for k, v in overrides.items() if v is not None or k == "domain"})
        if "as_of" in params:
            params["as_of"] = parse_as_of(params["as_of"])
        if "top_k" in params and not (isinstance(params["top_k"], int) and 1 <= params["top_k"] <= 50):
            raise ServiceError("invalid_params", "top_k 须为 1-50 的整数")
        params["seeds"] = self.seeds
        return run_query(self.graph_path, self.s, text, entry, params)

    def doc_search(self, text, entry, **overrides):
        """文档检索：与主查询同一路径与观测，只是默认 top_k/预算不同。返回 (docs, result, obs)。"""
        params = dict(DOC_SEARCH_DEFAULTS)
        params.update({k: v for k, v in overrides.items() if v is not None})  # None 不得覆盖文档默认
        r, obs = self.query(text, entry, **params)
        docs = [n for n in r["seeds"] if n["kind"] == "Doc"]
        return docs, r, obs

    # ---------- 图 ----------
    def impact(self, symbol, depth=IMPACT_DEFAULT_DEPTH, max_nodes=IMPACT_MAX_NODES):
        """反向影响面：预算在遍历中执行；三入口都拿到同一个 partial/truncated 语义。"""
        if not isinstance(symbol, str) or not symbol.strip():
            raise ServiceError("invalid_params", "符号不能为空")
        try:
            depth = int(depth)
            max_nodes = int(max_nodes)
        except (TypeError, ValueError):
            raise ServiceError("invalid_params", "depth/max_nodes 须为整数")
        if not 0 <= depth <= IMPACT_MAX_DEPTH or not 1 <= max_nodes <= 2000:
            raise ServiceError("invalid_params", "depth 0-%d，max_nodes 1-2000" % IMPACT_MAX_DEPTH)
        start, deps = self.g.impact(symbol, depth, max_nodes=max_nodes + 1)
        if not start:
            raise ServiceError("not_found", "无匹配符号")
        partial = len(deps) > max_nodes
        deps = deps[:max_nodes]
        deps = [{"src": a, "kind": k, "dst": b, "strength": st} for a, k, b, st in deps]
        return {"start": start, "deps": deps, "total": len(deps), "partial": partial,
                "truncated": partial, "max_nodes": max_nodes, "depth": depth}

    def domain_map(self):
        return self.g.domain_map()

    # ---------- 可信上下文（F3） ----------
    def trusted_context(self, scope=None, budget=None, root=None):
        """从**目标**可信根加载 AGENTS.md/SOUL.md（RV04：跨根不串用）。

        单根登记 → 默认该根（向后兼容）；多根未指定 root → ServiceError("ambiguous_root")（结构化歧义，
        列出候选）；root 未登记 → invalid_params。只加载目标根的规则，其他根的内容不读。
        

        changed：相对上次加载（store meta 记录每个规则文件 sha）内容变化或新增的文件；本次加载即视为已读。
        普通扫描摄入的同名文件永不进入这里——只有 `domimap trust add` 登记过的根才读。
        """
        from . import context as _ctx
        from .store import EvidenceStore
        budget = budget or _ctx.DEFAULT_BUDGET
        db = os.path.join(self.ws, "store.db")
        if not os.path.exists(db):
            return {"roots": [], "items": [], "text": "", "changed": [], "truncated": False, "dropped": [],
                    "scope": scope or "", "note": "无证据库（先 build 工作区）"}
        store = EvidenceStore(db)
        try:
            roots = store.trusted_roots()
            if not roots:
                return {"roots": [], "items": [], "text": "", "changed": [], "truncated": False, "dropped": [],
                        "scope": scope or "", "note": "未登记可信根（domimap trust add LABEL PATH）"}
            if root is None and len(roots) > 1:
                raise ServiceError(
                    "ambiguous_root",
                    "登记了多个可信根，须指定 root（候选：%s）；不同仓库的规则不得互相串用"
                    % ", ".join(r["label"] for r in roots))
            target = roots[0] if root is None else next(
                (r for r in roots if r["label"] == root), None)
            if target is None:
                raise ServiceError("invalid_params", "未登记的可信根：%s" % root)
            items, blocks, changed, dropped, truncated = [], [], [], [], False
            limit_hit = False
            r = target
            if not os.path.isdir(r["path"]):
                raise ServiceError("invalid_params", "可信根目录不存在：%s" % r["path"])
            try:
                out = _ctx.load_context(r["path"], trusted=[r["path"]], budget=budget, scope=scope)
            except PermissionError as e:
                raise ServiceError("invalid_params", str(e))
            truncated = truncated or out["truncated"]
            limit_hit = limit_hit or out.get("limit_hit", False)
            dropped += ["%s/%s" % (r["label"], d) for d in out["dropped"]]
            for i in out["items"]:
                key = "context_sha:%s/%s" % (r["label"], i["path"])
                prev = store.meta_get(key)
                if prev != i["sha256"]:
                    changed.append("%s/%s" % (r["label"], i["path"]))
                    store.meta_set(key, i["sha256"])
                items.append(dict(i, root=r["label"]))
            blocks.append(_ctx.render(out["items"], label=r["label"]))
            return {"roots": roots, "root": r["label"], "items": items,
                    "text": "\n".join(b for b in blocks if b),
                    "changed": changed, "truncated": truncated, "dropped": dropped,
                    "limit_hit": limit_hit, "scope": scope or ""}
        finally:
            store.close()

    # ---------- 知识复核（R06 原义） ----------
    def _kb(self):
        from .knowledge import KnowledgeStore
        path = os.path.join(self.ws, "knowledge.db")
        if not os.path.exists(path):
            raise ServiceError("unavailable", "无知识库（尚无笔记）")
        return KnowledgeStore(path)

    def review_queue(self):
        kb = self._kb()
        try:
            return kb.review_queue()
        finally:
            kb.close()

    def confirm_review(self, note_id, claim_idx):
        """确认 = 把陈述的引用换成同来源最新证据并绑定其版本；不是点击即真。"""
        try:
            claim_idx = int(claim_idx)
        except (TypeError, ValueError):
            raise ServiceError("invalid_params", "claim_idx 须为整数")
        kb = self._kb()
        try:
            item = next((q for q in kb.review_queue()
                         if q["note_id"] == note_id and q["claim_idx"] == claim_idx), None)
            if item is None:
                raise ServiceError("not_found", "无此待复核项：%s#%s" % (note_id, claim_idx))
            claims = kb._claims_of(note_id)
            claim = next((c for c in claims if c.get("idx", claims.index(c)) == claim_idx), None)
            if claim is None:
                raise ServiceError("not_found", "陈述不存在：%s#%s" % (note_id, claim_idx))
            new_ev = item.get("new_evidence") or item["evidence"]
            new_evidence = [new_ev if ev == item["evidence"] else ev for ev in claim.get("evidence", [])]
            kb.confirm_review(note_id, claim_idx, new_evidence, item["new_sha"])
            self.refresh(force=True)
            return {"note_id": note_id, "claim_idx": claim_idx, "new_evidence": new_ev,
                    "bound_sha": item["new_sha"]}
        finally:
            kb.close()

    # ---------- 知识写入口（R05/R07）：CLI/MCP/UI 共用同一校验与错误映射 ----------
    def _kb_rw(self):
        from .knowledge import KnowledgeStore
        return KnowledgeStore(os.path.join(self.ws, "knowledge.db"))  # 不存在则创建（首条笔记）

    def _knowledge_op(self, fn):
        from .knowledge import ConflictError
        kb = self._kb_rw()
        try:
            try:
                out = fn(kb)
            except ConflictError as e:
                raise ServiceError("conflict", str(e))
            except (ValueError, KeyError) as e:
                raise ServiceError("invalid_params", str(e))
        finally:
            kb.close()
        self.refresh(force=True)
        return out

    @staticmethod
    def _claims_arg(claims):
        if claims is None or claims == "":
            return []
        if isinstance(claims, str):
            try:
                claims = json.loads(claims)
            except ValueError:
                raise ServiceError("invalid_params", "claims 须为 JSON 数组")
        if not isinstance(claims, list):
            raise ServiceError("invalid_params", "claims 须为数组")
        return claims

    def note_submit(self, body, claims=None, idempotency_key=None):
        if not isinstance(body, str) or not body.strip():
            raise ServiceError("invalid_params", "正文不能为空")
        claims = self._claims_arg(claims)
        return self._knowledge_op(lambda kb: kb.submit(body, claims=claims, idempotency_key=idempotency_key))

    def note_amend(self, note_id, body, expected_revision, claims=None):
        if not isinstance(body, str) or not body.strip():
            raise ServiceError("invalid_params", "正文不能为空")
        try:
            expected_revision = int(expected_revision)
        except (TypeError, ValueError):
            raise ServiceError("invalid_params", "expected_revision 须为整数")
        claims = self._claims_arg(claims) if claims is not None else None
        return self._knowledge_op(lambda kb: kb.amend(note_id, body, expected_revision, claims=claims))

    def note_withdraw(self, note_id):
        return self._knowledge_op(lambda kb: kb.withdraw(note_id))

    def note_accept(self, note_id, idx, expected_revision=None, statement=None,
                    auditor="human:cli", reason=""):
        """审定（RV03）：必须绑定 expected_revision 与陈述原文；MCP 来源须单独授权（见 note_accept_agent）。"""
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            raise ServiceError("invalid_params", "idx 须为整数")
        if expected_revision is None or statement is None:
            raise ServiceError("invalid_params",
                               "审定需要 --expected-revision 与 --statement（绑定审定对象，防旧请求批准新内容）")
        return self._knowledge_op(
            lambda kb: kb.accept_claim(note_id, idx, expected_revision=expected_revision,
                                       statement=statement, auditor=auditor, reason=reason))

    def note_accept_agent(self, note_id, idx, expected_revision, statement):
        """MCP 转达的审定：--enable-write 不等于人工审定，须 DOMIMAP_MCP_ADJUDICATE=1 单独授权。"""
        import os as _os
        if _os.environ.get("DOMIMAP_MCP_ADJUDICATE") != "1":
            raise ServiceError(
                "forbidden",
                "审定须单独授权：设置 DOMIMAP_MCP_ADJUDICATE=1（--enable-write 只授权提案/修订，"
                "不自动等同于人工审定）")
        return self.note_accept(note_id, idx, expected_revision=expected_revision,
                                statement=statement, auditor="agent:mcp", reason="MCP adjudication")

    def note_get(self, note_id):
        kb = self._kb()
        try:
            note = kb.get(note_id)
        finally:
            kb.close()
        if note is None:
            raise ServiceError("not_found", "无此笔记：%s" % note_id)
        return note

    def note_history(self, note_id):
        kb = self._kb()
        try:
            hist = kb.history(note_id)
        finally:
            kb.close()
        if not hist:
            raise ServiceError("not_found", "无此笔记：%s" % note_id)
        return hist

    def kb_export(self, out_dir):
        kb = self._kb()
        try:
            return kb.export_markdown(out_dir)
        finally:
            kb.close()

    def kb_import(self, path, preview=False):
        from .knowledge import ConflictError
        kb = self._kb()
        try:
            try:
                return kb.preview_import(path) if preview else kb.import_markdown(path)
            except ConflictError as e:
                raise ServiceError("conflict", str(e))
            except (ValueError, KeyError, OSError) as e:
                raise ServiceError("invalid_params", str(e))
        finally:
            kb.close()

    def kb_backup(self, dest):
        kb = self._kb()
        try:
            try:
                return kb.backup(dest)
            except FileExistsError as e:
                raise ServiceError("exists", str(e))
        finally:
            kb.close()

    @staticmethod
    def kb_restore(archive, dest):
        from .knowledge import KnowledgeStore
        try:
            k = KnowledgeStore.restore(archive, dest)
        except FileExistsError as e:
            raise ServiceError("exists", str(e))
        except (ValueError, OSError) as e:
            raise ServiceError("invalid_params", str(e))
        try:
            return {"path": dest, "notes": k.count()}
        finally:
            k.close()

    # ---------- 证据 ----------
    def evidence_for(self, node):
        return self.resolver.for_node(node)

    def read_evidence(self, ev_id):
        from .store import EvidenceStore
        db = os.path.join(self.ws, "store.db")
        if not os.path.exists(db):
            return {"available": False, "reason": "无证据库（先 build 工作区）"}
        store = EvidenceStore(db)
        try:
            return store.read_evidence(ev_id)  # None = 无此 ID；dict.available=False = 已登记但不可用
        finally:
            store.close()
