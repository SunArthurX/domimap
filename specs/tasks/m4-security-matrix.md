# m4-security-matrix：UI 写入安全 + 框架能力矩阵（M4.2，AC-R08-02/09-02）

- R08-02：UI 增受守卫写入口 POST /api/note/save（仅回环 Host+Origin/Referer 校验通过才写，KnowledgeStore 幂等）；负例：恶意文档 `<script>` 经 /api/search 返回 JSON 不执行；跨站 Origin 写入 403；页面用 textContent 渲染。
- R09-02：docs/capability-matrix.md 逐构造声明 支持/部分/未知（含实测依据）；修复多 provider RPC（同接口两个 @DubboService → 对消费者连 AMBIGUOUS 边到全部 provider，不默取其一）；动态 SQL（<if>/<foreach> 内表）实测。
