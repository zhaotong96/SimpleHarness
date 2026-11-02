import subprocess
import sys
from pathlib import Path

desc = {
    "type": {
        "type": "string",
        "enum": ["bash", "python", "powershell", "cmd"]
    },
    "cmd":{
        "type": "string"
    },
    "pwd": {
        "type": "string",
        "default": "."
    },
    "required": ["type", "cmd"]
}

AGENT = Path(__file__).resolve().parent.parent / ".agent"
MAX_CHARS = 4000


def run(type="bash", cmd="", pwd="."):
    argv = {
        "bash": ("bash", "-lc"),
        "python": (sys.executable, "-c"),
        "powershell": ("powershell", "-NoProfile", "-Command"),
        "cmd": ("cmd", "/c"),
    }.get(type)
    if argv is None:
        return "错误: type 不在允许的枚举里"

    workdir = (AGENT / pwd).resolve()
    if not workdir.is_relative_to(AGENT):
        return "错误: pwd 越出了运行空间 .agent"
    workdir.mkdir(parents=True, exist_ok=True)

    try:
        p = subprocess.run(
            [*argv, cmd],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except FileNotFoundError:
        return f"错误: 找不到解释器 {argv[0]}"
    except subprocess.TimeoutExpired:
        return "错误: 执行超过 60s 被终止"

    report = f"exit={p.returncode} pwd={workdir}\n"
    for label, body in (("stdout", p.stdout), ("stderr", p.stderr)):
        body = (body or "").strip()
        if len(body) > MAX_CHARS:
            body = body[:MAX_CHARS] + f"\n...[已截断, 原长 {len(body)} 字符]"
        report += f"--- {label} ---\n{body}\n"
    return report
