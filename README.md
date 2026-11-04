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
目录`.agent/`下包含`conversation/`,`logs/`,`AGENTS.md`

## 系统提示
三段, 顺序固定: `system` -> 技能清单 -> `AGENTS.md` -> 用户对话正文
技能清单由启动时遍历`skills/`生成, 文件名即技能名, `desc`即说明
`AGENTS.md`不写死有哪些技能

## 上下文
用量显示在页面底栏, 达到`n_ctx`的80%时压缩历史

## 消息内容
上游已声明`multimodal`和`image`/`video`输入
`messages`的content是原样透传的, 数组形式不会被`main.py`破坏
缺的是前端入口: 图片要编码成`image_url`的content part才能进来

## 已定
日志和对话不做清理
`max-output`按字符算, 不改字节
根目录`conversation/`不ignore
正经测试时另开`tests/`, 现在不开
`timeout`上限进config, 默认60分钟
markdown渲染要做
前端表现类问题(角色标签之类)不再询问, 直接定
