# Java/框架能力矩阵（R09-02，2026-10-16 实测）

逐构造声明 支持/部分/未知；依据=测试名。不为覆盖率默连边；未知显式可见。

| 构造 | 声明 | 依据 |
|---|---|---|
| Spring 路由（@*Mapping+类前缀） | 支持 | test_golden TestSpringRoute |
| MyBatis 静态 SQL→表/列 | 支持 | test_golden TestMyBatis（WRITES/READS） |
| MyBatis 动态 SQL（<if>/<foreach> 内表） | 支持 | test_m4_matrix test_dynamic_sql_tables_extracted |
| Dubbo RPC 跨仓对齐（单 provider） | 支持 | test_p1 TestCrossRepoRPC |
| RPC 多 provider（同接口多实现） | 支持（AMBIGUOUS 全连，不默取其一） | test_m4_matrix test_multi_provider_all_linked_ambiguous |
| RocketMQ（@RocketMQMessageListener+template 发送） | 支持 | test_golden TestRocketMQ |
| 通用 MQ（@KafkaListener/@RabbitListener/@JmsListener 多主题） | 支持 | test_p1 TestGenericMQ |
| MQ 集群/角色区分 | 未知（不声明：解析不到集群语义，不默连） | — |
| JPA（@Entity/@Table/@Column→表列+MAPS_TO） | 支持 | test_p1 TestJPA |
| 跨端（fetch/axios→Controller 按 URL+method） | 支持 | test_golden TestCrossEnd |
| 方法重载（argc 签名独立；dispatch 歧义 AMBIGUOUS） | 支持 | test_precision TestOverload |
| 字段别名（声明类型解析接收者） | 支持 | test_precision TestFieldAlias |
| 匿名类/lambda（不假归属，保守跳过） | 支持（保守语义） | test_precision TestEmptyAndNested |
| 参数类型级 dispatch/数据流 | 未知（AST 候选见 parse-trial.md，失败样本驱动再启） | — |
| 运行时根因/观测 | 未知（静态分析不承诺） | — |

未知项原则：不伪装为已支持；真实语料 Topic=0 的 RocketMQ 真实形态缺口为已登记待修项（handoff）。
