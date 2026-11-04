- AGENTS.md中不要写死有什么技能, 靠启动时遍历, 把文件名作为技能名, desc作为帮助信息, 放在system后面, 顺序就是 system->所有技能信息->Agents.md , 然后就是用户对话正文, 具体措辞你自己编排
- 等合适的时候开发读图能力 作为一个skill存在
- 等合适时候开发截图能力 作为一个skill存在
- 等合适时候鼠标能力 作为skill存在
- 等合适时候键盘 作为skill
- 在左侧有一条代表对话时间线的 类似 git graph的东西 每个节点可以点击(类似checkout) 从这个节点开始的对话会产生分叉(类似branch) 当然随时可以点击任何一个分叉上的任何一个节点

---

Qoder 记录（截至 273ed4b）

## 待办

- 拼系统提示：`AGENTS.md` -> 技能清单 -> 正文（AGENTS.md 顶替 system 段，必须在最前）
- 上下文达 `n_ctx` 80% 时压缩历史
- `timeout` 上限进 config，默认 60 分钟
- markdown 渲染（走 `createElement`/`textContent`，不用 `innerHTML`）
- 提问/回答加角色标签
- `main.py:29` `timeout=30`、`main.py:69` `temperature: 0` 进 config
- `.gitattributes`：目前没有任何东西真的坏，只是每次 add 刷一行警告，等你一句话
- A/B 测 AGENTS.md 是否真改变了模型行为（清空对照跑同一 prompt，每轮约 8 分钟）
- 实测多标签页是否互相覆盖同一个对话文件（现按代码推理会）
- 实测 `turns over 8` 之后再发一轮会怎样
