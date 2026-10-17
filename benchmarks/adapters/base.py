"""五方比较适配框架（诊断轨）。

修复旧 formal_run.py 的四类 P0 缺陷：gold 首仓路由、静默截断、吞索引错误、
正则抽路径无记账。核心不变量：

1. ``Adapter.query`` 只接收题面文本——签名层面不存在 family/path/fact_id 等
   gold 字段，跨仓候选合并使用与题目无关的确定策略（manifest 序 round-robin）。
2. prepare 逐仓记录 ok/failed 与原因；环境故障（env_error）与产品空结果
   （product_empty）严格分类，环境缺失不得计为产品失败。
3. 每次查询独立 run_id、起止时间、状态、原始输出工件；超时与空结果区分。
"""
import hashlib
import inspect
import itertools
import json
import os
import time
import uuid
from dataclasses import dataclass, field

OK = "ok"
PRODUCT_EMPTY = "product_empty"
PRODUCT_ERROR = "product_error"
ENV_ERROR = "env_error"
ADAPTER_ERROR = "adapter_error"
TIMEOUT = "timeout"

ERROR_CLASSES = {OK, PRODUCT_EMPTY, PRODUCT_ERROR, ENV_ERROR, ADAPTER_ERROR, TIMEOUT}

# gold 泄漏防线：query 签名禁止出现这些参数名（框架级反射断言依赖此表）
FORBIDDEN_QUERY_PARAMS = {"family", "gold", "gold_path", "fact_id", "answer", "cluster"}


@dataclass
class RepoEntry:
    """公开工作区清单的一项；全部适配器看到同一清单。"""
    name: str
    root: str


@dataclass
class PrepareReport:
    system: str
    ok_repos: list = field(default_factory=list)
    failed_repos: list = field(default_factory=list)   # [{"repo","reason","detail"}]
    durations: dict = field(default_factory=dict)      # repo -> 秒
    accounting: dict = field(default_factory=dict)     # repo -> 截断/页数/字节等公开记账

    def to_dict(self):
        return {"system": self.system, "ok_repos": self.ok_repos,
                "failed_repos": self.failed_repos, "durations": self.durations,
                "accounting": self.accounting}


@dataclass
class QueryRecord:
    run_id: str
    question_id: str
    system: str
    started: float
    ended: float
    error_class: str
    top5: list = field(default_factory=list)
    raw_path: str = ""
    notes: list = field(default_factory=list)

    def to_dict(self):
        return {"run_id": self.run_id, "question_id": self.question_id,
                "system": self.system, "started": self.started, "ended": self.ended,
                "error_class": self.error_class, "top5": self.top5,
                "raw_path": self.raw_path, "notes": self.notes,
                "secs": round(self.ended - self.started, 3)}


def new_run_id():
    return "r-%s" % uuid.uuid4().hex[:16]


def round_robin_merge(per_repo_lists, dedupe=True, cap=None):
    """与题目无关的跨仓合并：按清单序取各仓第 1、第 2…个候选。

    不使用 gold 信息；同映射路径去重；cap 截断（None 表示不截断）。
    """
    merged, seen = [], set()
    for tier in itertools.zip_longest(*[list(x) for x in per_repo_lists]):
        for item in tier:
            if item is None:
                continue
            if dedupe:
                if item in seen:
                    continue
                seen.add(item)
            merged.append(item)
            if cap is not None and len(merged) >= cap:
                return merged
    return merged


class Adapter:
    """适配器基类。子类实现 _prepare/_query_one_repo/close_repo。"""

    name = "adapter"

    def __init__(self, artifact_dir):
        self.artifact_dir = artifact_dir
        self.repos = []
        self.ready_repos = []
        os.makedirs(artifact_dir, exist_ok=True)

    # -- 生命周期 -----------------------------------------------------------
    def prepare(self, repos, budget=None):
        self.repos = list(repos)
        report = PrepareReport(system=self.name)
        for repo in repos:
            if not os.path.isdir(repo.root):
                report.failed_repos.append({"repo": repo.name,
                                            "reason": "repo_dir_missing",
                                            "detail": repo.root})
                continue
            t0 = time.time()
            try:
                accounting = self._prepare_repo(repo, budget or {})
                report.ok_repos.append(repo.name)
                report.accounting[repo.name] = accounting or {}
            except Exception as error:  # 逐仓失败显式记录，绝不静默
                report.failed_repos.append({"repo": repo.name,
                                            "reason": type(error).__name__,
                                            "detail": str(error)[:400]})
            report.durations[repo.name] = round(time.time() - t0, 3)
        self.ready_repos = [r for r in repos if r.name in report.ok_repos]
        return report

    def query(self, question_id, text, budget=None):
        """唯一查询入口。签名固定为 (question_id, text, budget)——无 gold 字段。"""
        if not self.ready_repos:
            return QueryRecord(new_run_id(), question_id, self.name, time.time(), time.time(),
                               ADAPTER_ERROR, notes=["query_before_prepare_or_all_repos_failed"])
        started = time.time()
        run_id = new_run_id()
        per_repo, notes = [], []
        for repo in self.ready_repos:
            try:
                paths, repo_notes = self._query_repo(repo, text, budget or {})
                per_repo.append(paths)
                notes.extend("%s:%s" % (repo.name, n) for n in repo_notes)
            except TimeoutError as error:
                raw = self._dump_raw(run_id, question_id, {"timeout": str(error)})
                return self._record(run_id, question_id, started, TIMEOUT, [], raw,
                                    notes + ["repo %s timeout: %s" % (repo.name, error)])
            except Exception as error:
                raw = self._dump_raw(run_id, question_id,
                                     {"error": "%s: %s" % (type(error).__name__, str(error)[:400])})
                return self._record(run_id, question_id, started, PRODUCT_ERROR, [], raw,
                                    notes + ["repo %s error: %s: %s"
                                             % (repo.name, type(error).__name__, str(error)[:200])])
        merged = round_robin_merge(per_repo, dedupe=True)
        raw_path = self._dump_raw(run_id, question_id, per_repo)
        error_class = OK if merged else PRODUCT_EMPTY
        return self._record(run_id, question_id, started, error_class,
                            merged[:5], raw_path, notes)

    def close(self):
        for repo in getattr(self, "ready_repos", []):
            try:
                self.close_repo(repo)
            except Exception:
                pass

    # -- 子类接口 -----------------------------------------------------------
    def _prepare_repo(self, repo, budget):
        raise NotImplementedError

    def _query_repo(self, repo, text, budget):
        """返回 (映射为仓相对路径的候选列表, notes)。"""
        raise NotImplementedError

    def close_repo(self, repo):
        return None

    # -- 内部 ---------------------------------------------------------------
    def _record(self, run_id, question_id, started, error_class, top5, raw_path, notes):
        return QueryRecord(run_id, question_id, self.name, started, time.time(),
                           error_class, top5, raw_path, notes)

    def _dump_raw(self, run_id, question_id, per_repo):
        path = os.path.join(self.artifact_dir, "%s-%s.json" % (self.name, run_id))
        with open(path, "w", encoding="utf-8") as stream:
            json.dump({"run_id": run_id, "question_id": question_id,
                       "per_repo": per_repo}, stream, ensure_ascii=False, indent=1)
        return path

    def raw_sha256(self, raw_path):
        with open(raw_path, "rb") as stream:
            return hashlib.sha256(stream.read()).hexdigest()


def assert_no_gold_routing(adapter_cls):
    """框架级反路由断言：query 签名不得含 gold 泄漏参数。"""
    params = set(inspect.signature(adapter_cls.query).parameters)
    leaked = params & FORBIDDEN_QUERY_PARAMS
    if leaked:
        raise ValueError("query signature leaks gold routing: %s" % sorted(leaked))
    return True


def map_to_repo(raw, repo):
    """把系统输出的路径规范化为 ``仓名/仓内相对路径``；无法归属则原样返回。"""
    if not raw:
        return raw
    raw = raw.strip().strip('"').strip("'")
    root_abs = os.path.abspath(repo.root)
    candidate = raw
    if os.path.isabs(raw):
        try:
            candidate = os.path.relpath(raw, root_abs)
            if candidate.startswith(".."):
                return raw  # 绝对路径不在该仓内
        except ValueError:
            return raw
    parts = candidate.replace("\\", "/").split("/")
    if parts and parts[0] == repo.name:
        return "/".join(parts)
    return repo.name + "/" + "/".join(parts)
