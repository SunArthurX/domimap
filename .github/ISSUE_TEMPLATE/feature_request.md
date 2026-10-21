name: 功能建议
about: 提出新能力或改进
labels: enhancement
body:
  - type: textarea
    id: problem
    attributes:
      label: 想解决的问题 / Problem to solve
      description: 你在什么场景下被什么卡住了（先说场景，再说方案）
    validations:
      required: true
  - type: textarea
    id: proposal
    attributes:
      label: 建议的做法 / Proposed approach
