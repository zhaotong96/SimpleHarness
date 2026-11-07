# TODO - 一行就是一个待办 不允许罗嗦

- 等合适的时候开发读图能力 作为一个skill存在
- 等合适时候开发截图能力 作为一个skill存在
- 等合适时候鼠标能力 作为skill存在
- 等合适时候键盘 作为skill
- 等合适时候开发cdp 作为一个skill存在
- 在左侧有一条代表对话时间线的 类似 git graph的东西 每个节点可以点击(类似checkout) 从这个节点开始的对话会产生分叉(类似branch) 当然随时可以点击任何一个分叉上的任何一个节点
- Phase 2: 基于 .agent/sessions/*.jsonl 账本 parent 节点关系，在前端左侧实现类似 git graph 的对话树交互，支持任意历史节点 checkout 与分叉


---

Qoder 记录（截至 273ed4b）

- `timeout` 上限进 config，默认 60 分钟
- markdown 渲染（走 `createElement`/`textContent`，不用 `innerHTML`）
- 提问/回答加角色标签
- `.gitattributes`：目前没有任何东西真的坏，只是每次 add 刷一行警告，等你一句话
- A/B 测 AGENTS.md 是否真改变了模型行为（清空对照跑同一 prompt，每轮约 8 分钟）
- 实测多标签页是否互相覆盖同一个对话文件（现按代码推理会）
- 实测 `turns over 8` 之后再发一轮会怎样
