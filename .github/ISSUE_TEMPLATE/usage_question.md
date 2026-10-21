name: 使用问题
about: 安装、建图、检索、MCP/客户端接入等使用咨询
labels: question
body:
  - type: textarea
    id: usage
    attributes:
      label: 想做什么 / What you are trying to do
      description: 命令、查询词、期望结果；MCP 接入请附客户端与配置片段（隐去敏感信息）
    validations:
      required: true
  - type: textarea
    id: docs
    attributes:
      label: 已查阅 / Docs already checked
      placeholder: README / docs/knowledge-graph.md / docs/clients.md 的哪一节没有解答你的问题
