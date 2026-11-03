# 工作区规则

## 运行空间
pwd 相对 `.agent/`。绝对路径可用。无沙箱。

## 输出超限
`output over length <路径>`：正文故意不给。报告已折成 100 列存于该路径，切片读（`sed -n '1,50p' <路径>`），别 cat 全文——又超限，又多一个文件。

## 技能契约
`skills/*.py` 要有 `desc` 和 `run`，且 `desc` 键 == `run` 形参，否则加载即报错，不留到运行时伪装成 `empty command`。
`desc` 扁平：参数名 → JSON Schema 片段，外加一个 `required` 列表；main.py 负责翻成 tool schema。
模块 docstring = 工具说明。

## 文案
注释中文。给模型的报错与输出：英文，词数最少。仅当会误导时才写长，如 `bad enum`（防 `pythan` 被读成"环境坏了"）。

## 上游
config.json 给 host/port 与 default-llm；模型名问 `/v1/models`。
`enable_thinking` 必须嵌在 `chat_template_kwargs`，顶层无效。
thinking 默认开：首字 ~5s。关则工具轮次静默 ~2min。
