# m2-time-tasks：F4 时间策略收口 + kg_explore 证据 ID + 首批十条真实任务（M2.4）

- kg_explore 输出附证据 ID（Claude Code 真实会话反馈：agent 曾被迫绕道 sqlite 反查）。
- F4（AC-F4-01）：docs 支持 front-matter `valid_until/superseded_by`；资格顺序=替代排除→过期排除→as_of→日期未知按最早；衰减仅作用于排序且逐条 explain（age/decay 或 未知不衰减）；touch/复制不刷新（内容级 first_seen 已有）。
- R12（AC-R12-01）：首批十条真实任务（真实工作区语料，非夹具），每条记录可核验依据时间/适用判断/失败分类（developer-dev 标注，确认集独立另建）。
