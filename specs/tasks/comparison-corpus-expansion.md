# comparison-corpus-expansion：公共开源来源补充（测试计划第 3 步后续）

来源：计划 §4（数据集）、§1.2 P0"独立族不足则补来源"。性质：**评测基础设施**。

## 动机（cluster-report 实测）

当前 48 族只有 strict=14/conservative=12 个独立簇；且旧 599 题已覆盖全部现有 confirm 族（全部已暴露）→ **独立确认集必须整体新建**。协议要求确认集 ≥20 独立族，只能靠新增真正无关的来源满足，不得缩协议。

## 方案

- 新增公共语料根 `~/work/dm-corpus-public/`：约 20 个 depth-1 克隆的公共开源仓（中文 Java 业务系统/中间件/文档丰富库：mall 系列、JeecgBoot、RuoYi-Vue、yudao、eladmin、litemall、vhr、spring-boot-demo、hutool、Sa-Token、mybatis-plus、Guns、easyexcel、canal、shardingsphere、rocketmq、nacos、spring-petclinic 等）。
- 公共来源仅本地评测用（不 redistribution、不上传模型）；克隆记录 commit SHA（--depth 1 后取 ls-remote/HEAD）。
- split 语义升级：现有全部族（企业语料 45 + 外部 4）→ **dev/exposed**（已参与旧 599 题调参，只能作开发/回归）；新公共族 → **confirm-candidate**（未暴露，独立评测环境管理其题目/gold）。
- isolation.py main() 纳入公共根 + 新 split 值；cluster-report 增列 confirm-candidate 簇数（协议 ≥20 的核对口径，conservative）。

## 契约

1. 确认候选簇数（conservative）≥20 才达协议下限；不足则如实报告缺口，不得计入已暴露簇。
2. LICENSE/COPYING/NOTICE 等全网同字节标准文本不产生内容同一性边（新增回归测试）。
3. 公共族 manifest 含每仓 commit SHA（版本冻结证据）。
4. 现有族 split 全部改为 dev（exposed 注记），不得再冒充独立确认。

## 负例

1. 把已暴露的企业语料巨簇计入确认簇数 → 检查器按 confirm-candidate 值过滤，拒绝。
2. 用 LICENSE 相同把无关开源仓连簇 → 排除规则 + 测试。

## 实测结果（2026-10-17 真跑，27 个公共仓 depth-1 克隆于 ~/work/dm-corpus-public）

- **确认候选 27 族 → 20 个保守独立簇（conservative），达协议 ≥20 下限**（strict=38/conservative=35 为全语料含 dev 侧）。公共仓：mall 三变体、JeecgBoot、RuoYi-Vue、yudao、eladmin、litemall、vhr、spring-boot-demo、hutool、Sa-Token、mybatis-plus、Guns、easyexcel、canal、shardingsphere、rocketmq、nacos、petclinic、dubbo、skywalking、shenyu、pig、APIJSON、xxl-job、activemq。每仓 commit SHA 入 manifest（版本冻结证据）。
- **假关联治理迭代（全部有回归测试）**：.DS_Store（全机同字节）→ LICENSE/COPYING（全网同字节）→ mvnw/gradlew 包装脚本 + 隐藏目录(.mvn/.github) → 二进制资源(jar/ico/png/svg…)与 vendored 目录(bower_components/vendor) → ≥3 族共有哈希视为生态通用。残余边界边（Sa-Token↔JeecgBoot 的 layer.js、canal↔litemall 的 vue 脚手架、jeecg↔pig 的 logback 模板）保留合并=保守方向。
- **命名一致性**：公共目录统一连字符命名（首批下划线批次已 mv 统一），EXPLICIT_ASSOCIATIONS 按连字符名匹配。
- **人工关联声明**：mall/mall-swarm/mall-tiny 为同作者同业务三变体（内容边只检出 mall↔mall-swarm 408 文件，mall-tiny 改写后无逐字节同文）——EXPLICIT_ASSOCIATIONS 显式声明并给理由，防自动规则低估关联。
- split 语义已落地：现有 49 族全部 dev/exposed=true；公共 27 族 confirm-candidate；cluster-report.confirm_candidate.meets_protocol_minimum=true。
- 契约测试 15 项绿。

## 回退

单提交回滚；~/work/dm-corpus-public 可整目录删除；仓库内只留代码与 spec。
