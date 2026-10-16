# m4-formats-platform：PDF/DOCX 五态 + 平台矩阵 + 并发压力（M4.3，AC-R09-01/09-03/10-01）

- R09-01：_docx_text/_pdf_text 重构为状态化抽取（ok/no-dep/corrupt/encrypted/no-text；超限沿用 coverage），修正"解析失败误标未安装"；PDF 记页数定位。
- R09-03：docs/platform-matrix.md——本机 macOS/Python 3.13 实测（make verify+安装检查）；Linux/Windows 如实记"未运行不宣称"（CI 工作流已定义）。
- R10-01：8 在途读 + 串行保存/发布的混合负载测试——无异常、无混代、写入全落、active 完整。
