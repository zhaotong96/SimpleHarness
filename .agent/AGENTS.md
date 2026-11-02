# 给在此工作区干活的 agent

## 运行空间
技能里的 pwd 以 `.agent/` 为相对基准。绝对路径照用，没有沙箱：command 本来就能执行任意命令。

## 输出超限
shell 技能回 `output over length <路径>` 时正文没给你是故意的。整份报告已折成 100 列落在该路径，
必须按行或按字节切片读（`sed -n '1,50p' logs/xxx.txt`），直接 cat 整个文件会再次超限并多生成一个文件。

## 技能契约
`skills/*.py` 必须有 `desc` 和 `run`，且 `desc` 的键与 `run` 的形参完全一致。
不一致时 main.py 加载即报错，不会等到运行时把 TypeError 伪装成 `empty command`。
`desc` 用扁平写法（参数名 → JSON Schema 片段 + 一个 `required` 列表），main.py 负责翻成 tool schema。
模块 docstring 会成为模型看到的工具说明。

## 文案
注释一律中文；给模型看的报错与输出文案一律英文、词数最少。
只有一种例外：会误导模型的才写全，例如 `bad enum`（手滑写成 pythan 时不能被读成"环境坏了"）。

## 上游
`config.json` 只给 host/port 与 default-llm，模型名启动时从 `/v1/models` 取。
`enable_thinking` 必须嵌在 `chat_template_kwargs` 里，放顶层会被 llama.cpp 忽略。
默认开着 thinking：实测首字约 5 秒就出字；关掉后工具轮次期间会静默约 2 分钟。
