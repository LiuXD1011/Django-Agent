#!/usr/bin/env python
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
REPORT_PATH = PROJECT_ROOT / "tests" / "full_project_test_report.md"
RESULT_JSON_PATH = PROJECT_ROOT / "tests" / "full_project_test_results.json"


COMMANDS = [
    {
        "name": "后端与 Agent 综合测试",
        "cmd": [PYTHON, "tests/test_full_project_backend_agent.py"],
        "report": "tests/full_project_backend_agent_report.md",
    },
    {
        "name": "现有对话功能客观回归测试",
        "cmd": [PYTHON, "tests/test_chat_feature_objective.py"],
        "report": "tests/chat_feature_test_report.md",
    },
    {
        "name": "前端静态契约测试",
        "cmd": [PYTHON, "tests/test_frontend_contracts.py"],
        "report": "tests/frontend_contracts_report.md",
    },
    {
        "name": "多 Agent 本地 Eval 测试",
        "cmd": [PYTHON, "tests/test_local_agent_eval.py"],
        "report": "tests/agent_eval_local_report.md",
    },
    {
        "name": "前端生产构建",
        "cmd": ["npm", "--prefix", "frontend", "run", "build"],
        "report": "",
    },
    {
        "name": "前端 Playwright 浏览器联动测试",
        "cmd": [PYTHON, "tests/test_frontend_playwright_e2e.py"],
        "report": "tests/frontend_playwright_e2e_report.md",
    },
    {
        "name": "Python 语法编译检查",
        "cmd": [PYTHON, "-m", "compileall", "chat", "personal_knowledge_base", "models_config", "wiki", "tests"],
        "report": "",
    },
]


def run_command(item: dict) -> dict:
    start = time.time()
    proc = subprocess.run(
        item["cmd"],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    duration_ms = int((time.time() - start) * 1000)
    output = proc.stdout or ""
    return {
        "name": item["name"],
        "cmd": " ".join(item["cmd"]),
        "returncode": proc.returncode,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "duration_ms": duration_ms,
        "report": item.get("report") or "",
        "output_tail": "\n".join(output.splitlines()[-80:]),
    }


def write_report(results: list[dict]) -> None:
    passed = sum(1 for item in results if item["returncode"] == 0)
    failed = len(results) - passed
    lines = [
        "# 当前项目完整测试总报告",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 测试脚本：`tests/run_full_project_tests.py`",
        f"- 执行命令：`{PYTHON} tests/run_full_project_tests.py`",
        f"- 汇总：共 {len(results)} 组命令，PASS {passed}，FAIL {failed}。",
        "- 测试范围：后端 API、前端静态契约、前端生产构建、浏览器联动、Agent 工具/Actor、对话流式/断线恢复、本地 Agent eval、Python 语法检查。",
        "",
        "## 命令结果",
        "",
        "| 模块 | 结果 | 耗时 | 命令 | 子报告 |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for item in results:
        report = f"`{item['report']}`" if item["report"] else "-"
        lines.append(f"| {item['name']} | {item['status']} | {item['duration_ms']} ms | `{item['cmd']}` | {report} |")

    lines.extend(["", "## 失败详情", ""])
    failed_items = [item for item in results if item["returncode"] != 0]
    if not failed_items:
        lines.append("- 本轮总测试未发现失败命令。")
    else:
        for item in failed_items:
            lines.extend(
                [
                    f"### {item['name']}",
                    "",
                    f"- 返回码：{item['returncode']}",
                    f"- 子报告：`{item['report']}`" if item["report"] else "- 子报告：无",
                    "",
                    "```text",
                    item["output_tail"],
                    "```",
                    "",
                ]
            )

    lines.extend(
        [
            "## 客观边界",
            "",
            "- 测试中对外部 LLM、真实 embedding/rerank/vlm、真实 Neo4j 连接做了 mock 或未触达；这些属于环境集成测试，需要在真实部署环境另跑。",
            "- `agents-cli` 当前环境未安装，官方 Google Agent Eval CLI 未执行；已生成可接入的数据集与本地 deterministic eval 报告。",
            "- Playwright 使用 headless Chromium 和 Django live server；真实用户浏览器、慢网络、移动端手势仍建议人工验收。",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    RESULT_JSON_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    results = []
    for item in COMMANDS:
        result = run_command(item)
        results.append(result)
        write_report(results)
    return 0 if all(item["returncode"] == 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
