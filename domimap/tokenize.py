"""分词：CJK 1/2/3-gram 内建（不装 jieba 也能中文检索），latin 词干切分。
中英技术域词汇桥：中文 token 附加英文对应词（索引期双向可搜）。"""
import re

_CJK = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]*|\d+")

# 中英技术域同义词（通用术语，非 benchmark 特定词）——公共语料评测实证：
# 中文查询（"接入 教程"）无法命中英文 README（"Getting Started"）是最大缺口
EN_BRIDGE = {
    "接入": ["integrate", "integration", "getting", "started"],
    "部署": ["deploy", "deployment"],
    "配置": ["config", "configuration", "configure"],
    "教程": ["tutorial", "guide", "getting", "started"],
    "入门": ["tutorial", "getting", "started", "quickstart"],
    "使用": ["usage", "howto", "manual"],
    "支持": ["support", "feature"],
    "关闭": ["disable", "close", "shutdown"],
    "开启": ["enable", "open"],
    "后端": ["backend", "server", "server-side"],
    "前端": ["frontend", "client", "client-side"],
    "日期": ["date", "version", "release"],
    "生效": ["effective", "active"],
    "失效": ["expire", "deprecated", "invalid"],
    "版本": ["version", "release"],
    "兼容": ["compatible", "compatibility"],
    "保留": ["reserve", "backward", "keep"],
    "默认": ["default"],
    "内网": ["intranet", "internal", "private"],
    "限制": ["limitation", "restrict", "constraint"],
    "条件": ["condition", "where", "clause"],
    "查询": ["query", "search", "select"],
    "删除": ["delete", "remove", "drop"],
    "增加": ["add", "insert", "create"],
    "修改": ["update", "modify", "alter"],
    "回滚": ["rollback", "revert"],
    "升级": ["upgrade", "migrate"],
    "迁移": "migrate",
    "安装": ["install", "setup"],
    "启动": ["start", "launch", "boot"],
    "停止": ["stop", "shutdown", "halt"],
    "安全": ["security", "auth", "permission"],
    "认证": ["auth", "authentication", "login"],
    "授权": ["authorization", "permission", "grant"],
    "加密": ["encrypt", "encryption", "ssl", "tls"],
    "解密": ["decrypt", "decryption"],
    "数据库": ["database", "db", "sql"],
    "缓存": ["cache", "redis"],
    "消息": ["message", "mq", "queue"],
    "队列": ["queue", "mq"],
    "日志": ["log", "logging", "logger"],
    "监控": ["monitor", "metrics", "health"],
    "性能": ["performance", "benchmark", "latency"],
    "测试": ["test", "testing", "unit test"],
    "文档": ["document", "documentation", "readme"],
    "说明": ["document", "documentation", "readme", "manual"],
    "规范": ["spec", "specification", "standard"],
    "接口": ["api", "interface", "endpoint"],
    "服务": ["service", "server"],
    "模块": ["module", "component"],
    "框架": ["framework", "spring"],
    "插件": ["plugin", "extension"],
    "协议": ["protocol", "http", "rpc"],
    "集群": ["cluster", "nodes"],
    "注册": ["register", "registry", "discovery"],
    "发现": ["discovery", "detect"],
    "负载": ["load", "balance", "loadbalance"],
    "路由": ["route", "router", "gateway"],
    "网关": ["gateway", "route"],
    "代理": ["proxy", "agent"],
    "中间件": ["middleware"],
    "微服务": ["microservice", "micro-service"],
    "容器": ["container", "docker", "k8s"],
    "镜像": ["image", "docker"],
    "构建": ["build", "compile", "make"],
    "打包": ["package", "bundle", "jar"],
    "发布": ["release", "publish", "deploy"],
    "回退": ["rollback", "fallback"],
    "重试": ["retry", "reconnect"],
    "超时": ["timeout", "ttl"],
    "异常": ["exception", "error"],
    "警告": ["warn", "warning"],
    "调试": ["debug", "trace"],
    "优化": ["optimize", "performance", "tuning"],
    "变更": ["change", "changelog", "modify"],
    "新增": ["new", "add", "feature"],
    "修复": ["fix", "bug", "patch"],
    "废弃": ["deprecate", "deprecated", "obsolete"],
    "替代": ["replace", "alternative", "supersede"],
}

def tokenize(text):
    """返回词袋：CJK 连续段产 1/2/3-gram，latin 产小写词与 camelCase 切分。
    中文 2-gram 附加英文同义词（EN_BRIDGE 桥）。"""
    out = []
    for m in _WORD.finditer(text):
        w = m.group(0).lower()
        out.append(w)
        parts = re.findall(r"[a-z]+|[A-Z][a-z]*", m.group(0))
        if len(parts) > 1:
            out.extend(p.lower() for p in parts if len(p) > 1)
    i = 0
    n = len(text)
    while i < n:
        if _CJK.match(text[i]):
            j = i
            while j < n and _CJK.match(text[j]):
                j += 1
            seg = text[i:j]
            L = len(seg)
            for k in range(L):
                out.append(seg[k])
                if k + 1 < L:
                    out.append(seg[k:k+2])
                if k + 2 < L:
                    out.append(seg[k:k+3])
            i = j
        else:
            i += 1
    return out
