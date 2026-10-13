#!/usr/bin/env python
import json
import os
import shutil
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.test import TransactionTestCase, override_settings  # noqa: E402
from django.test.runner import DiscoverRunner  # noqa: E402
from django.test.utils import setup_test_environment, teardown_test_environment  # noqa: E402


EVAL_DIR = PROJECT_ROOT / "tests" / "eval"
DATASET_DIR = EVAL_DIR / "datasets"
REPORT_PATH = PROJECT_ROOT / "tests" / "agent_eval_local_report.md"
RESULT_JSON_PATH = EVAL_DIR / "local_agent_eval_results.json"
DATASET_PATH = DATASET_DIR / "django_agent_multiactor_eval.json"
CONFIG_PATH = EVAL_DIR / "eval_config.yaml"

DATASET_DIR.mkdir(parents=True, exist_ok=True)

CASE_DEFINITIONS = {
    "test_local_multiactor_eval_dataset_and_scores": "生成 Google eval schema 风格数据集，并本地评分多 Agent 路由/工具轨迹。",
    "test_agent_engine_tool_call_trajectory_for_eval_cases": "用 fake LLM 驱动 AgentEngine，验证工具调用轨迹和最终回答符合 eval 期望。",
}

EVAL_CASES = [
    {
        "id": "doc_retrieval_question",
        "prompt": "这批原始文档里有哪些关于缓存命中率的证据？",
        "expected_subagent": "doc_retriever",
        "expected_final": "文档检索结果",
    },
    {
        "id": "wiki_overview_question",
        "prompt": "这个知识库整体有哪些主题和概念页面？",
        "expected_subagent": "wiki_researcher",
        "expected_final": "Wiki 结构结果",
    },
    {
        "id": "graph_relation_question",
        "prompt": "A 系统和 B 模块之间的关系链路是什么？",
        "expected_subagent": "graph_reasoner",
        "expected_final": "图谱关系结果",
    },
    {
        "id": "answer_synthesis_question",
        "prompt": "把文档、Wiki 和图谱结果整理成最终答复。",
        "expected_subagent": "answer_writer",
        "expected_final": "综合写作结果",
    },
    {
        "id": "simple_direct_question",
        "prompt": "你好",
        "expected_subagent": "",
        "expected_final": "你好，我是智能助手。",
    },
]

CASE_RESULTS: dict[str, dict] = {}
CASE_EVIDENCE: dict[str, dict] = {}


def _case_name(test):
    return getattr(test, "_testMethodName", str(test))


def _json_preview(value, max_len=520):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    return text if len(text) <= max_len else text[:max_len] + "..."


def build_google_style_dataset():
    eval_cases = []
    for index, case in enumerate(EVAL_CASES):
        agents = {
            "main": {
                "agent_id": "main",
                "agent_type": "multi-agent-assistant",
                "instruction": "Route tasks to doc_retriever/wiki_researcher/graph_reasoner/answer_writer when needed.",
            }
        }
        if case["expected_subagent"]:
            agents[case["expected_subagent"]] = {
                "agent_id": case["expected_subagent"],
                "agent_type": "subagent",
                "instruction": f"Specialized worker: {case['expected_subagent']}",
            }
        events = [
            {
                "author": "user",
                "content": {"role": "user", "parts": [{"text": case["prompt"]}]},
            }
        ]
        if case["expected_subagent"]:
            events.append(
                {
                    "author": "main",
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "function_call": {
                                    "name": "actor",
                                    "args": {
                                        "action": "run",
                                        "subagent_type": case["expected_subagent"],
                                        "prompt": case["prompt"],
                                    },
                                }
                            }
                        ],
                    },
                }
            )
            events.append(
                {
                    "author": "tool",
                    "content": {
                        "role": "tool",
                        "parts": [
                            {
                                "function_response": {
                                    "name": "actor",
                                    "response": {"output": case["expected_final"]},
                                }
                            }
                        ],
                    },
                }
            )
        events.append(
            {
                "author": "main",
                "content": {"role": "model", "parts": [{"text": case["expected_final"]}]},
            }
        )
        eval_cases.append(
            {
                "eval_case_id": case["id"],
                "agent_data": {
                    "agents": agents,
                    "turns": [{"turn_index": index, "events": events}],
                },
                "rubric_groups": {
                    "routing": {
                        "rubrics": [
                            {
                                "rubric_id": "expected_tool_route",
                                "content": {
                                    "property": {
                                        "description": "The main agent should call the expected actor subagent when the task requires delegation."
                                    }
                                },
                            }
                        ]
                    }
                },
            }
        )
    payload = {"eval_cases": eval_cases}
    DATASET_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CONFIG_PATH.write_text(
        "\n".join(
            [
                "metrics_to_run:",
                "  - multi_turn_task_success",
                "  - multi_turn_tool_use_quality",
                "  - final_response_quality",
                "",
                "# 本项目当前环境缺少 agents-cli，因此本文件用于后续安装官方 CLI 后直接接入。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return payload


class EvidenceResult(unittest.TextTestResult):
    def startTest(self, test):
        CASE_RESULTS[_case_name(test)] = {"started_at": time.time()}
        super().startTest(test)

    def _store(self, test, status, err=None):
        name = _case_name(test)
        started = CASE_RESULTS.get(name, {}).get("started_at", time.time())
        detail = self._exc_info_to_string(err, test) if err else ""
        CASE_RESULTS[name] = {
            **CASE_RESULTS.get(name, {}),
            "status": status,
            "duration_ms": int((time.time() - started) * 1000),
            "detail": detail,
        }

    def addSuccess(self, test):
        self._store(test, "PASS")
        super().addSuccess(test)

    def addFailure(self, test, err):
        self._store(test, "FAIL", err)
        super().addFailure(test, err)

    def addError(self, test, err):
        self._store(test, "ERROR", err)
        super().addError(test, err)


class EvidenceRunner(unittest.TextTestRunner):
    resultclass = EvidenceResult


@override_settings(
    LLM_CHAT_API_KEY="",
    LLM_USE_ENV_CHAT=False,
    LLM_USE_ENV_SUMMARY=False,
    LLM_USE_ENV_TITLE=False,
    LLM_USE_ENV_QUESTION=False,
    LLM_USE_ENV_EXTRACT=False,
    LLM_USE_ENV_EMBEDDING=False,
    LLM_USE_ENV_RERANK=False,
    LLM_USE_ENV_VLM=False,
    LLM_USE_ENV_ASR=False,
)
class LocalAgentEvalTests(TransactionTestCase):
    def setUp(self):
        from personal_knowledge_base.authentication import hash_password
        from personal_knowledge_base.models import Tenant, TenantMember, User

        unique = uuid4().hex[:10]
        self.tenant = Tenant.objects.create(name=f"eval-test-{unique}", api_key=f"eval-key-{unique}")
        self.user = User.objects.create(
            username=f"eval_user_{unique}",
            email=f"eval_user_{unique}@example.test",
            password_hash=hash_password("test-password"),
            tenant=self.tenant,
            preferences={"enable_memory": False},
        )
        TenantMember.objects.create(user=self.user, tenant=self.tenant, role="owner")

    def record(self, **data):
        CASE_EVIDENCE.setdefault(self._testMethodName, {}).update(data)

    def test_local_multiactor_eval_dataset_and_scores(self):
        dataset = build_google_style_dataset()
        agents_cli_available = bool(shutil.which("agents-cli"))
        case_scores = []
        for case in dataset["eval_cases"]:
            events = case["agent_data"]["turns"][0]["events"]
            tool_calls = [
                part.get("function_call")
                for event in events
                for part in event["content"].get("parts", [])
                if isinstance(part, dict) and part.get("function_call")
            ]
            case_id = case["eval_case_id"]
            expected = next(item for item in EVAL_CASES if item["id"] == case_id)
            if expected["expected_subagent"]:
                route_ok = any(
                    call
                    and call.get("name") == "actor"
                    and call.get("args", {}).get("subagent_type") == expected["expected_subagent"]
                    for call in tool_calls
                )
            else:
                route_ok = not tool_calls
            final_text = events[-1]["content"]["parts"][0]["text"]
            final_ok = expected["expected_final"] in final_text
            case_scores.append(
                {
                    "eval_case_id": case_id,
                    "expected_subagent": expected["expected_subagent"],
                    "route_ok": route_ok,
                    "final_ok": final_ok,
                    "score": 1.0 if route_ok and final_ok else 0.0,
                }
            )
        summary = {
            "agents_cli_available": agents_cli_available,
            "dataset_path": str(DATASET_PATH.relative_to(PROJECT_ROOT)),
            "config_path": str(CONFIG_PATH.relative_to(PROJECT_ROOT)),
            "case_count": len(case_scores),
            "passed": sum(1 for item in case_scores if item["score"] == 1.0),
            "score": round(sum(item["score"] for item in case_scores) / len(case_scores), 4),
            "cases": case_scores,
        }
        RESULT_JSON_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.record(**summary)
        self.assertEqual(summary["case_count"], len(EVAL_CASES))
        self.assertEqual(summary["score"], 1.0)

    def test_agent_engine_tool_call_trajectory_for_eval_cases(self):
        from personal_knowledge_base.agent_engine import AgentEngine
        from personal_knowledge_base.agent_tools import ToolResult, get_tool_registry
        from personal_knowledge_base.models import Session

        session = Session.objects.create(tenant=self.tenant, title="eval trajectory", user_id=self.user.id)
        original_execute_tool = get_tool_registry().execute_tool
        scores = []

        def fake_execute_tool(name, args, context):
            if name == "actor":
                subagent = args.get("subagent_type", "")
                output_map = {
                    "doc_retriever": "文档检索结果",
                    "wiki_researcher": "Wiki 结构结果",
                    "graph_reasoner": "图谱关系结果",
                    "answer_writer": "综合写作结果",
                }
                return ToolResult(output=f"[Actor {subagent}-1 success]\n{output_map.get(subagent, '')}")
            return original_execute_tool(name, args, context)

        with patch.object(get_tool_registry(), "execute_tool", side_effect=fake_execute_tool):
            for case in EVAL_CASES:
                engine = AgentEngine(
                    tenant=self.tenant,
                    session_id=session.id,
                    user_id=self.user.id,
                    agent_config={
                        "agent_mode": "multi-agent",
                        "allowed_tools": ["actor", "thinking"],
                        "max_rounds": 4,
                        "allow_actor_tool": True,
                    },
                )
                calls = {"count": 0}

                def fake_llm(messages, max_retries=3, case=case, calls=calls):
                    calls["count"] += 1
                    if not case["expected_subagent"]:
                        return {"content": case["expected_final"], "tool_calls": None}
                    if calls["count"] == 1:
                        return {
                            "content": f"调用 {case['expected_subagent']} 子 Agent",
                            "tool_calls": [
                                {
                                    "id": f"call-{case['id']}",
                                    "function": {
                                        "name": "actor",
                                        "arguments": json.dumps(
                                            {
                                                "action": "run",
                                                "subagent_type": case["expected_subagent"],
                                                "prompt": case["prompt"],
                                                "timeout_ms": 30000,
                                            },
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            ],
                        }
                    return {"content": f"最终：{case['expected_final']}", "tool_calls": None}

                engine._call_llm_with_tools = fake_llm
                engine._call_llm_simple = lambda messages: "摘要"
                result = engine.execute(case["prompt"])
                actual_subagents = [
                    tc.arguments.get("subagent_type", "")
                    for step in result.steps
                    for tc in step.tool_calls
                    if tc.name == "actor"
                ]
                route_ok = (
                    actual_subagents == [case["expected_subagent"]]
                    if case["expected_subagent"]
                    else actual_subagents == []
                )
                final_ok = case["expected_final"] in result.content
                scores.append(
                    {
                        "eval_case_id": case["id"],
                        "actual_subagents": actual_subagents,
                        "stopped_reason": result.stopped_reason,
                        "route_ok": route_ok,
                        "final_ok": final_ok,
                        "score": 1.0 if route_ok and final_ok else 0.0,
                    }
                )

        summary = {
            "case_count": len(scores),
            "passed": sum(1 for item in scores if item["score"] == 1.0),
            "score": round(sum(item["score"] for item in scores) / len(scores), 4),
            "cases": scores,
        }
        self.record(**summary)
        self.assertEqual(summary["score"], 1.0)


def write_report(result: EvidenceResult):
    total = result.testsRun
    failed = len(result.failures)
    errored = len(result.errors)
    skipped = len(result.skipped)
    passed = total - failed - errored - skipped
    agents_cli_available = bool(shutil.which("agents-cli"))
    lines = [
        "# 多 Agent 本地 Eval 测试报告",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "- 测试脚本：`tests/test_local_agent_eval.py`",
        "- 执行命令：`/home/liuxuedeng/anaconda3/envs/django-agent/bin/python tests/test_local_agent_eval.py`",
        f"- 官方 `agents-cli` 可用：{agents_cli_available}",
        "- 测试口径：生成 Google Agent eval schema 风格数据集，同时用 deterministic fake LLM/Tool 做本地轨迹评分；不调用外部 judge 模型。",
        f"- 汇总：共 {total} 项，PASS {passed}，FAIL {failed}，ERROR {errored}，SKIP {skipped}。",
        "",
        "## 产物",
        "",
        f"- 数据集：`{DATASET_PATH.relative_to(PROJECT_ROOT)}`",
        f"- 配置：`{CONFIG_PATH.relative_to(PROJECT_ROOT)}`",
        f"- 本地结果 JSON：`{RESULT_JSON_PATH.relative_to(PROJECT_ROOT)}`",
        "",
        "## 用例结果",
        "",
        "| 用例 | 结果 | 耗时 | 目标 | 关键证据 |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for name, objective in CASE_DEFINITIONS.items():
        item = CASE_RESULTS.get(name, {"status": "NOT_RUN", "duration_ms": 0, "detail": ""})
        lines.append(
            f"| `{name}` | {item['status']} | {item.get('duration_ms', 0)} ms | {objective} | "
            f"`{_json_preview(CASE_EVIDENCE.get(name, {}))}` |"
        )
    failed_items = [(name, data) for name, data in CASE_RESULTS.items() if data.get("status") in {"FAIL", "ERROR"}]
    lines.extend(["", "## 失败与风险", ""])
    if not failed_items:
        lines.append("- 本次本地 eval 未发现失败用例。")
    else:
        for name, data in failed_items:
            detail = data.get("detail", "").strip().splitlines()
            preview = "\n".join(detail[-16:]) if detail else ""
            lines.extend([f"### `{name}`", "", f"- 状态：{data.get('status')}", f"- 证据：`{_json_preview(CASE_EVIDENCE.get(name, {}), max_len=900)}`"])
            if preview:
                lines.extend(["", "```text", preview, "```"])
            lines.append("")
    lines.extend(
        [
            "",
            "## 覆盖范围",
            "",
            "- 覆盖：多 Agent eval 数据集格式、主 Agent actor 调用轨迹、简单问题不调用子 Agent、子 Agent 路由和最终回答包含预期信息。",
            "- 未覆盖：官方 Agent Platform LLM-as-judge 打分、真实模型路由质量、长多轮 user simulation。",
            "- 说明：若安装 `agents-cli`，可用 `agents-cli eval grade --config tests/eval/eval_config.yaml` 接入官方评分流程。",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    setup_test_environment()
    runner = DiscoverRunner(verbosity=0, interactive=False)
    old_config = runner.setup_databases()
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(LocalAgentEvalTests)
        result = EvidenceRunner(verbosity=2).run(suite)
        write_report(result)
        return 0 if result.wasSuccessful() else 1
    finally:
        runner.teardown_databases(old_config)
        teardown_test_environment()


if __name__ == "__main__":
    raise SystemExit(main())
