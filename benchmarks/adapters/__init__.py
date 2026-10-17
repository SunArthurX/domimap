"""五方比较适配框架（诊断轨）：防 gold 路由、错误分类、公开记账。"""
from .base import (ADAPTER_ERROR, ENV_ERROR, OK, PRODUCT_EMPTY, PRODUCT_ERROR,
                   TIMEOUT, Adapter, PrepareReport, QueryRecord, RepoEntry,
                   assert_no_gold_routing, map_to_repo, new_run_id,
                   round_robin_merge)

__all__ = ["ADAPTER_ERROR", "ENV_ERROR", "OK", "PRODUCT_EMPTY", "PRODUCT_ERROR",
           "TIMEOUT", "Adapter", "PrepareReport", "QueryRecord", "RepoEntry",
           "assert_no_gold_routing", "map_to_repo", "new_run_id",
           "round_robin_merge"]
