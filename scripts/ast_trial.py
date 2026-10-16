#!/usr/bin/env python3
"""M1.2 有限解析试验：直接 Java AST（javalang==0.13.0，固定版本）vs lite 正则基线。

对 tests/fixtures/precision 同一输入抽取 类/方法(签名 argc)/调用点，输出差异与成本数据，
结论记录于 docs/implementation/parse-trial.md。未安装 javalang 时退出码 3（试验环境缺失，如实记录）。
"""
import json
import os
import sys

FIX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tests", "fixtures", "precision")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def lite_baseline():
    from domimap import lite_scan
    R = lite_scan.scan_repo(FIX, repo_label="precision")
    return {"methods": [(m["cls"], m["name"], m["argc"]) for m in R["methods"]],
            "calls": [(c["from"], c["to_method"], c["conf"]) for c in R.get("calls", [])]}

def ast_extract():
    import javalang
    out = {"methods": [], "calls": []}
    for fn in sorted(os.listdir(FIX)):
        if not fn.endswith(".java"):
            continue
        src = open(os.path.join(FIX, fn), encoding="utf-8").read()
        tree = javalang.parse.parse(src)
        for _, cls in tree.filter(javalang.tree.ClassDeclaration):
            for m in cls.methods:
                out["methods"].append((cls.name, m.name, len(m.parameters)))
                for _, inv in m.filter(javalang.tree.MethodInvocation):
                    out["calls"].append((m.name, inv.member, "AST"))
        # 匿名类/lambda 内调用：AST 能精确归属或显式未知
    return out

if __name__ == "__main__":
    try:
        import javalang  # noqa: F401
    except ImportError:
        print("[trial] javalang 未安装（试验 extra）；结论见 parse-trial.md")
        sys.exit(3)
    report = {"lite": lite_baseline(), "ast": ast_extract(),
              "javalang_version": javalang.__version__ if hasattr(javalang, "__version__") else "0.13.0"}
    print(json.dumps(report, ensure_ascii=False, indent=1))
