"""Verify the starter through installed tools and actual process exit codes."""

import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agent_tracecheck import analyze_trace
from agent_tracecheck.cli import load_trace

import demo


ROOT = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trace = Path(self.temp.name) / "trace.jsonl"

    def run_process(self, *arguments):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        return subprocess.run([sys.executable, *map(str, arguments)], cwd=ROOT, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=20)

    def test_healthy_workflow_records_two_successful_calls_and_passes_budget(self):
        result = self.run_process("demo.py", self.trace)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = analyze_trace(load_trace(self.trace.read_text(encoding="utf-8")))
        self.assertEqual(report["summary"]["calls"], 2)
        self.assertEqual(report["summary"]["errors"], 0)
        self.assertEqual(report["summary"]["pending"], 0)
        check = self.run_process("-m", "agent_tracecheck", self.trace, "--max-calls", "4")
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_retry_workflow_is_recorded_but_fails_diagnostic_budgets(self):
        result = self.run_process("demo.py", self.trace, "--scenario", "retry")
        self.assertEqual(result.returncode, 0, result.stderr)
        check = self.run_process("-m", "agent_tracecheck", self.trace, "--format", "json")
        self.assertEqual(check.returncode, 1, check.stderr)
        report = json.loads(check.stdout)
        self.assertEqual(report["summary"]["calls"], 5)
        self.assertEqual(report["summary"]["errors"], 3)
        self.assertTrue(any(item["code"] == "repeated_call" for item in report["findings"]))

    def test_existing_trace_is_preserved(self):
        self.trace.write_text("keep this file", encoding="utf-8")
        result = self.run_process("demo.py", self.trace)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.trace.read_text(encoding="utf-8"), "keep this file")

    def test_baseline_and_candidate_contracts_pass(self):
        result = self.run_process("-m", "mcp_changecheck", "contracts/baseline.json",
                                  "contracts/candidate.json", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["changes"], [])

    def test_intentionally_breaking_contract_fails_and_can_be_inspected(self):
        result = self.run_process("-m", "mcp_changecheck", "contracts/baseline.json",
                                  "contracts/breaking.json", "--format", "json")
        self.assertEqual(result.returncode, 1, result.stderr)
        changes = json.loads(result.stdout)["changes"]
        self.assertTrue(any(item["severity"] == "breaking" for item in changes))
        inspect_result = self.run_process("-m", "mcp_changecheck", "contracts/baseline.json",
                                          "contracts/breaking.json", "--fail-on", "never")
        self.assertEqual(inspect_result.returncode, 0, inspect_result.stderr)

    def test_candidate_contract_parameter_names_match_demo_functions(self):
        candidate = json.loads((ROOT / "contracts/candidate.json").read_text(encoding="utf-8"))
        functions = {function.__name__: function for function in (demo.lookup_note, demo.count_words)}
        self.assertEqual({tool["name"] for tool in candidate["tools"]}, set(functions))
        for tool in candidate["tools"]:
            with self.subTest(tool=tool["name"]):
                parameters = inspect.signature(functions[tool["name"]]).parameters
                self.assertEqual(set(tool["inputSchema"]["properties"]), set(parameters))
                required = {name for name, value in parameters.items()
                            if value.default is inspect.Parameter.empty}
                self.assertEqual(set(tool["inputSchema"]["required"]), required)
