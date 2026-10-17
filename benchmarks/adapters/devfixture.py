"""契约测试合成工作区：3 仓小语料，覆盖中文/空格/重复/同名/空仓契约维度。

不用于评分，只用于适配器行为契约（错误分类、记账、映射、去重）。
"""
import os

ALPHA_ORDER_SERVICE = """package com.alpha.order;

public class OrderService {
    private PriceService priceService;

    /** ZQXW_UNIQUE_TOKEN_9 alpha-only marker */
    public void changePrice(long orderId, long newPrice) {
        priceService.validate(newPrice);
    }
}
"""

ALPHA_ORDER_SERVICE_CN = """package com.alpha.order;

// 中文内容文件：库存预警消费重试
public class StockAlertConsumer {
    public void onMessage(String payload) {
        retryWithBackoff(payload);
    }

    private void retryWithBackoff(String payload) {
    }
}
"""

ALPHA_DOC = """# 迁移说明 v1

回滚方案：先停写入，再执行 downgrade.sql。
适用版本：2.x。
"""

ALPHA_DUP = "重复内容样本：同一事实出现在两个文件中，用于验证跨文件去重契约。\n"

ALPHA_SPACES = """最终报表 final report
订单金额校验入口位于 OrderService.changePrice。
"""

BETA_ORDER_SERVICE = """package com.beta.order;

// 与 alpha 同类同名：同名歧义契约
public class OrderService {
    public void changePrice(long orderId, long newPrice) {
        auditTrail.record(orderId);
    }
}
"""

BETA_PRICE = """package com.beta.order;

public class PriceService {
    void validate(long price) {
    }
}
"""

BETA_LONG_PREFIX = """长输出样本 %03d
关键词 ZQLONG_TOKEN 出现于此文件，用于验证 top5 截断与原始输出保存。
"""


def build_fixture(base):
    """在 base 下建 3 仓，返回 (repos, layout)。layout 供测试断言使用。"""
    alpha = os.path.join(base, "repo-alpha")
    beta = os.path.join(base, "repo-beta")
    empty = os.path.join(base, "repo-empty")
    for path in (alpha, beta, empty):
        os.makedirs(os.path.join(path, "src"), exist_ok=True)

    def put(root, rel, content):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(content)

    put(alpha, "src/OrderService.java", ALPHA_ORDER_SERVICE)
    put(alpha, "src/库存预警消费者.java", ALPHA_ORDER_SERVICE_CN)
    put(alpha, "docs/migration.md", ALPHA_DOC)
    put(alpha, "docs/dup-a.txt", ALPHA_DUP)
    put(alpha, "docs/dup-b.txt", ALPHA_DUP)
    put(alpha, "docs/report final.md", ALPHA_SPACES)
    put(beta, "src/OrderService.java", BETA_ORDER_SERVICE)
    put(beta, "src/PriceService.java", BETA_PRICE)
    for i in range(12):
        put(beta, "notes/long-%03d.txt" % i, BETA_LONG_PREFIX % i)

    from .base import RepoEntry
    repos = [RepoEntry("repo-alpha", alpha), RepoEntry("repo-beta", beta),
             RepoEntry("repo-empty", empty)]
    layout = {"alpha_files": 7, "beta_files": 14, "empty": True}
    return repos, layout
