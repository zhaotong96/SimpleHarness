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
