name: Bug 报告
about: 报告可复现的缺陷
labels: bug
body:
  - type: textarea
    id: what-happened
    attributes:
      label: 发生了什么 / What happened
      description: 期望行为与实际行为的对比，尽量给出可复现的最小输入
    validations:
      required: true
  - type: textarea
    id: reproduce
    attributes:
      label: 复现步骤 / Steps to reproduce
      placeholder: |
        python3 -m domimap build <目录> -o out/idx
        python3 -m domimap query "..." -g out/idx/graph.json
  - type: input
    id: version
    attributes:
      label: 版本 / Version
      placeholder: "domimap --help 显示的版本或 git commit"
  - type: input
    id: env
    attributes:
      label: 环境 / Environment
      placeholder: "macOS 15 / Ubuntu 24.04，Python 3.13（是否安装可选依赖 pypdf/python-docx）"
