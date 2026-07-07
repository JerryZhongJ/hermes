#!/usr/bin/env python3
"""Tests for the agent annotator."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE = "annotator.annotate"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"


def valid_annotation(file_name: str) -> dict:
    loc = {
        "file": file_name,
        "start": {"line": 1, "column": 9},
        "end": {"line": 1, "column": 19},
    }
    return {
        "static shapes": {
            "Point": {
                "properties": [
                    {"name": "x", "type": "number"},
                    {"name": "y", "type": "number"},
                ]
            }
        },
        "shape guards": [],
        "type guards": [],
        "shape bindings": [
            {
                "target range": loc,
                "bind after": loc,
                "shape": "Point",
            }
        ],
    }


class AnnotateTest(unittest.TestCase):
    def run_annotator(self, tmp: Path, agent_code: str, extra_args=None):
        input_path = tmp / "input.js"
        output_path = tmp / "annotations.json"
        stats_path = tmp / "stats.json"
        input_path.write_text("var o = {x:1, y:2};\nprint(o.x);\n", encoding="utf-8")

        cmd = [
            sys.executable,
            "-m",
            MODULE,
            str(input_path),
            "-o",
            str(output_path),
            "--stats",
            str(stats_path),
            "--config",
            str(tmp / "default-config.json"),
        ]
        (tmp / "default-config.json").write_text(
            json.dumps({"agent": "codex"}), encoding="utf-8"
        )
        if extra_args:
            cmd.extend(extra_args)

        proc = self.run_with_fake_codex_sdk(tmp, cmd, agent_code)
        return proc, output_path, stats_path

    def run_annotator_with_config(self, tmp: Path, agent_code: str, config: dict):
        input_path = tmp / "input.js"
        output_path = tmp / "annotations.json"
        stats_path = tmp / "stats.json"
        config_path = tmp / "config.json"
        input_path.write_text("var o = {x:1, y:2};\nprint(o.x);\n", encoding="utf-8")
        config_path.write_text(json.dumps(config), encoding="utf-8")

        cmd = [
            sys.executable,
            "-m",
            MODULE,
            str(input_path),
            "-o",
            str(output_path),
            "--stats",
            str(stats_path),
            "--config",
            str(config_path),
        ]

        proc = self.run_with_fake_codex_sdk(tmp, cmd, agent_code)
        return proc, output_path, stats_path

    def run_with_fake_codex_sdk(
        self, tmp: Path, cmd: list[str], agent_code: str
    ) -> subprocess.CompletedProcess[str]:
        sdk_dir = tmp / "sdk"
        generated_dir = sdk_dir / "openai_codex" / "generated"
        generated_dir.mkdir(parents=True)
        (sdk_dir / "openai_codex" / "__init__.py").write_text(
            "import os\n"
            "from enum import Enum\n"
            "from types import SimpleNamespace\n"
            "\n"
            "class ApprovalMode(Enum):\n"
            "    deny_all = 'deny_all'\n"
            "\n"
            "class Sandbox(Enum):\n"
            "    workspace_write = 'workspace-write'\n"
            "\n"
            "class CodexConfig:\n"
            "    def __init__(self, cwd=None, env=None):\n"
            "        self.cwd = cwd\n"
            "        self.env = env\n"
            "\n"
            "class Stream:\n"
            "    def __aiter__(self):\n"
            "        return self\n"
            "    async def __anext__(self):\n"
            "        from openai_codex.generated.v2_all import DynamicToolCallThreadItem, ItemCompletedNotification, ThreadTokenUsageUpdatedNotification, TurnCompletedNotification\n"
            "        if not hasattr(self, 'index'):\n"
            "            self.index = 0\n"
            "        self.index += 1\n"
            "        if self.index == 1:\n"
            "            usage = {'total': {'input_tokens': 7, 'output_tokens': 3}}\n"
            "            payload = ThreadTokenUsageUpdatedNotification('turn-1', usage)\n"
            "            return SimpleNamespace(payload=payload)\n"
            "        if self.index == 2:\n"
            "            item = DynamicToolCallThreadItem('item-1', 'Write')\n"
            "            payload = ItemCompletedNotification(SimpleNamespace(root=item), 'turn-1')\n"
            "            return SimpleNamespace(payload=payload)\n"
            "        if self.index == 3:\n"
            "            turn = SimpleNamespace(id='turn-1', status='completed', error=None)\n"
            "            payload = TurnCompletedNotification(turn)\n"
            "            return SimpleNamespace(payload=payload)\n"
            "        raise StopAsyncIteration\n"
            "    async def aclose(self):\n"
            "        pass\n"
            "\n"
            "class Turn:\n"
            "    id = 'turn-1'\n"
            "    def stream(self):\n"
            "        return Stream()\n"
            "\n"
            "class Thread:\n"
            "    def __init__(self, config):\n"
            "        self.config = config\n"
            "    async def turn(self, prompt):\n"
            "        globals()['LAST_PROMPT'] = prompt\n"
            "        old_cwd = os.getcwd()\n"
            "        old_env = dict(os.environ)\n"
            "        os.chdir(self.config.cwd)\n"
            "        os.environ.clear()\n"
            "        os.environ.update(self.config.env)\n"
            "        try:\n"
            f"            exec({agent_code!r})\n"
            "        finally:\n"
            "            os.chdir(old_cwd)\n"
            "            os.environ.clear()\n"
            "            os.environ.update(old_env)\n"
            "        return Turn()\n"
            "\n"
            "class AsyncCodex:\n"
            "    def __init__(self, config):\n"
            "        globals()['CODEX_CONFIG'] = config\n"
            "    async def __aenter__(self):\n"
            "        return self\n"
            "    async def __aexit__(self, exc_type, exc, tb):\n"
            "        return False\n"
            "    async def thread_start(self, **kwargs):\n"
            "        globals()['THREAD_START_KWARGS'] = kwargs\n"
            "        return Thread(globals()['CODEX_CONFIG'])\n",
            encoding="utf-8",
        )
        (generated_dir / "__init__.py").write_text("", encoding="utf-8")
        (generated_dir / "v2_all.py").write_text(
            "class AgentMessageDeltaNotification: pass\n"
            "class AgentMessageThreadItem: pass\n"
            "class CollabAgentToolCallThreadItem: pass\n"
            "class CommandExecutionThreadItem: pass\n"
            "class McpToolCallThreadItem: pass\n"
            "class UserMessageThreadItem: pass\n"
            "class WebSearchThreadItem: pass\n"
            "\n"
            "class DynamicToolCallThreadItem:\n"
            "    def __init__(self, id, tool):\n"
            "        self.id = id\n"
            "        self.tool = tool\n"
            "        self.arguments = {}\n"
            "        self.status = 'completed'\n"
            "        self.content_items = []\n"
            "        self.duration_ms = 0\n"
            "\n"
            "class ItemCompletedNotification:\n"
            "    def __init__(self, item, turn_id):\n"
            "        self.item = item\n"
            "        self.turn_id = turn_id\n"
            "\n"
            "class ThreadTokenUsageUpdatedNotification:\n"
            "    def __init__(self, turn_id, token_usage):\n"
            "        self.turn_id = turn_id\n"
            "        self.token_usage = token_usage\n"
            "\n"
            "class TurnCompletedNotification:\n"
            "    def __init__(self, turn):\n"
            "        self.turn = turn\n",
            encoding="utf-8",
        )
        (sdk_dir / "openai_codex" / "models.py").write_text(
            "class Notification: pass\n"
            "class NotificationPayload: pass\n",
            encoding="utf-8",
        )
        env = dict(os.environ)
        path_entries = [str(sdk_dir), str(SRC_ROOT)]
        if env.get("PYTHONPATH"):
            path_entries.append(env["PYTHONPATH"])
        python_path = os.pathsep.join(path_entries)
        env["PYTHONPATH"] = python_path
        return subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            cwd=PROJECT_ROOT,
            env=env,
        )

    def test_success_writes_output_and_stats(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ann = json.dumps(valid_annotation("input.js"))
            event = json.dumps(
                {
                    "type": "message",
                    "message": {"usage": {"input_tokens": 7, "output_tokens": 3}},
                    "content": [{"type": "tool_use", "name": "Write"}],
                }
            )
            code = (
                "import sys;"
                "sys.stdin.read();"
                f"open('annotation.json','w').write({ann!r});"
                f"print({event!r})"
            )

            proc, output_path, stats_path = self.run_annotator(tmp, code)

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(output_path.exists())
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
            self.assertIn("agent_metrics", stats)
            self.assertNotIn("event_log_path", stats)
            self.assertNotIn("error_log_path", stats)
            self.assertNotIn("stdout_path", stats)
            self.assertNotIn("stderr_path", stats)
            self.assertEqual(stats["agent_metrics"]["usage"]["total_tokens"], 10)
            self.assertEqual(stats["agent_metrics"]["tool_counts"]["Write"], 1)
            self.assertEqual(set(stats), {"duration_seconds", "agent_metrics"})

    def test_config_provides_agent_model_and_env(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ann = json.dumps(valid_annotation("input.js"))
            code = (
                "import os,sys;"
                "sys.stdin.read();"
                "assert os.environ['TEST_MODEL_KEY'] == 'secret-value';"
                f"open('annotation.json','w').write({ann!r})"
            )

            proc, output_path, stats_path = self.run_annotator_with_config(
                tmp,
                code,
                {
                    "agent": "codex",
                    "model": "configured-model",
                    "env": {"TEST_MODEL_KEY": "secret-value"},
                    "codex_config": {"model_provider": "test-provider"},
                },
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(output_path.exists())
            self.assertNotIn("secret-value", stats_path.read_text(encoding="utf-8"))

    def test_agent_env_inherits_only_proxy_vars(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ann = json.dumps(valid_annotation("input.js"))
            code = (
                "import os,sys;"
                "sys.stdin.read();"
                "assert os.environ['https_proxy'] == 'http://proxy.example:8080';"
                "assert 'TEST_PARENT_ENV' not in os.environ;"
                f"open('annotation.json','w').write({ann!r})"
            )

            old_proxy = os.environ.get("https_proxy")
            old_parent = os.environ.get("TEST_PARENT_ENV")
            os.environ["https_proxy"] = "http://proxy.example:8080"
            os.environ["TEST_PARENT_ENV"] = "parent-value"
            try:
                proc, output_path, _ = self.run_annotator_with_config(
                    tmp,
                    code,
                    {"agent": "codex"},
                )
            finally:
                if old_proxy is None:
                    os.environ.pop("https_proxy", None)
                else:
                    os.environ["https_proxy"] = old_proxy
                if old_parent is None:
                    os.environ.pop("TEST_PARENT_ENV", None)
                else:
                    os.environ["TEST_PARENT_ENV"] = old_parent

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
