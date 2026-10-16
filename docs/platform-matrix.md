# 平台支持矩阵（R09-03，2026-10-16 实测记录）

| 平台 | Python | 状态 | 依据 |
|---|---|---|---|
| macOS 15 (Darwin 24.6.0, arm64) | 3.13（miniconda） | **实测通过** | make verify 129/129；干净 venv 安装 wheel + 异目录 doctor/build/query 冒烟（scripts/install_check.sh） |
| macOS | 3.11–3.13 矩阵 | 未运行（本机仅 3.13） | CI 工作流已定义（.github/workflows/ci.yml），未在远端执行过——不宣称 |
| Linux (ubuntu-latest) | 3.11/3.13 | 未运行 | 同上（CI 未执行） |
| Windows | 3.11/3.13 | 未运行 | 同上 |

原则：未运行不宣称支持；extras（docs=python-docx+pypdf、cn=jieba、mcp=mcp SDK≥2.3）在本机 3.13 实测可用，其余平台随 CI 落地后补记。
