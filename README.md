# SimpleHarness
最简易的harness, 为了最节省token
不是为了省钱, 是为了本地稠密模型可用

## 默认
默认状态无参启动拉起一个http服务

## 万物皆技能
`skills/` 路径下只放`.py`文件
文件名就是技能名
每个`.py`自包含技能描述和执行入口

## 架构边界
harness只提供最基础接口支持
Agent的业务功能全部在前端实现
目录`.agent/`下包含`conversation/`,`sessions/`,`logs/`,`AGENTS.md`
shell技能真实执行且不做沙箱隔离（预期设计，单机单用户场景，网络边界由只监听127.0.0.1保障）

## 会话与账本持久化
- 工作态（`.agent/conversation/<timestamp>.json`）：全量消息快照，随轮次更新并在用量达 80% 时压缩裁剪，用于恢复前端与提供当前窗口上下文。
- 账本流（`.agent/sessions/<timestamp>.jsonl`）：仅追加（append-only）的不可变事件账本，逐条保留历史提问、思考、工具调用与回复，不受 80% 压缩影响，用于离线追溯与全量审计。
- 分支对话树（Git Graph）：账本节点附带 id 与 parent 指针构成 DAG，前端左侧侧边栏可视化呈现历史分支；点击任意历史节点即可 checkout 恢复该快照，发起新提问自动分叉生成新分支。
- 保证轮次完整：长耗时工具调用期间若客户端断开，服务端在整轮结束时仍通过原子替换（唯一临时名 + `os.replace`）完整存盘。
- 零内存黑箱：服务端不保留全局会话状态，只提供文件读写，格式与 OpenAI messages 原生同构。

## 系统提示
`AGENTS.md`就是system段, 排在最前: `AGENTS.md` -> 技能清单 -> 用户对话正文
技能清单由启动时遍历`skills/`生成, 文件名即技能名, `desc`即说明
`AGENTS.md`不写死有哪些技能
`AGENTS.md`必须纯英文

## 上下文
用量显示在页面底栏, 达到`n_ctx`的80%时压缩历史

## 消息内容
上游已声明`multimodal`和`image`/`video`输入
`messages`的content是原样透传的, 数组形式不会被`main.py`破坏
缺的是前端入口: 图片要编码成`image_url`的content part才能进来

## 上游
`config.json`声明节点配置（host、api-key 与 current-llm），模型名启动时优先从 server.model 读取或问 `/models`
`enable_thinking`必须嵌在`chat_template_kwargs`里, 放顶层会被llama.cpp忽略
thinking开时首字约5s; 关时不吐reasoning增量, 工具轮次期间可静默约2min

## 已定
日志和对话不做清理
`max-output`按字符算, 不改字节
shell不做沙箱隔离, 真实执行
正经测试时另开`tests/`, 现在不开
`timeout`上限进config, 默认60分钟
markdown渲染要做
前端表现类问题(角色标签之类)不再询问, 直接定
