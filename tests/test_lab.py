"""Exercise the optional lab through installed tools and observable artifacts."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import lab


ROOT = Path(__file__).resolve().parents[1]
HAS_LAB = all(importlib.util.find_spec(name) is not None for name in
              ("context_budgetpack", "tool_mockbox", "agent_tracecheck"))


@unittest.skipUnless(HAS_LAB, "Optional lab dependencies are not installed")
class LabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.output = self.base / "new-lab"

    def process(self, *arguments):
        return subprocess.run([sys.executable, *map(str, arguments)], cwd=ROOT,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                              capture_output=True, text=True, encoding="utf-8", timeout=30)

    def run_lab(self, *arguments):
        return self.process("lab.py", "--output", self.output, *arguments)

    def fixture(self, steps):
        path = self.base / "scenario.json"
        path.write_text(json.dumps({"schema_version": 1, "tools": [
            {"name": "lookup_note", "steps": steps}]}), encoding="utf-8")
        return path

    def error_step(self, code="temporary", arguments=None):
        return {"arguments": arguments or {"note_id": "release"}, "status": "error",
                "error": {"code": code, "message": "Synthetic fixture failure"}}

    def summary(self):
        return json.loads((self.output / "lab-summary.json").read_text(encoding="utf-8"))

    def test_recovery_keeps_all_failures_and_exports_real_diagnostics(self):
        result = self.run_lab()
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = self.summary()
        self.assertEqual((summary["attempts"], summary["retries"], summary["outcome"]), (3, 2, "recovered"))
        self.assertEqual(summary["result"]["note_id"], "release")
        self.assertEqual(summary["fixture_summary"]["error"], 2)
        self.assertEqual(summary["trace_summary"]["calls"], 3)
        self.assertEqual(summary["trace_summary"]["errors"], 2)
        self.assertEqual(summary["trace_summary"]["pending"], 0)
        self.assertEqual(summary["trace_budget_exit"], 0)
        expected = {"context/context.md", "context/manifest.json", "context/report.html", "fixture-run.json",
                    "fixture-run.html", "trace.jsonl", "trace-report.json", "trace-report.md",
                    "trace-report.html", "lab-summary.json"}
        self.assertEqual({path.relative_to(self.output).as_posix() for path in self.output.rglob("*") if path.is_file()}, expected)
        fixture = json.loads((self.output / "fixture-run.json").read_text(encoding="utf-8"))
        self.assertEqual([event["status"] for event in fixture["events"]], ["error", "error", "ok"])
        events = [json.loads(line) for line in (self.output / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(events), 6)
        self.assertEqual([event["status"] for event in events if event["type"] == "tool_result"], ["error", "error", "ok"])
        self.assertNotIn("Synthetic temporary failure", (self.output / "trace.jsonl").read_text(encoding="utf-8"))
        diagnostics = json.loads((self.output / "trace-report.json").read_text(encoding="utf-8"))
        codes = {finding["code"] for finding in diagnostics["findings"]}
        self.assertTrue({"tool_error", "error_retry", "repeated_call"} <= codes)
        self.assertIn("Identical tool and arguments were called after an observed error", (self.output / "trace-report.md").read_text(encoding="utf-8"))
        self.assertIn("error_retry", (self.output / "trace-report.html").read_text(encoding="utf-8"))
        verified = self.process("-m", "context_budgetpack", "verify", self.output / "context",
                                "--root", ROOT / "lab-fixtures/workspace", "--format", "json")
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertTrue(json.loads(verified.stdout)["ok"])
        strict = self.process("-m", "agent_tracecheck", self.output / "trace.jsonl", "--max-errors", "0", "--format", "json")
        self.assertEqual(strict.returncode, 1, strict.stderr)
        self.assertIn("error_budget", {item["code"] for item in json.loads(strict.stdout)["findings"]})

    def test_existing_output_is_preserved(self):
        self.assertEqual(self.run_lab().returncode, 0)
        before = {str(path.relative_to(self.output)): path.read_bytes() for path in self.output.rglob("*") if path.is_file()}
        repeated = self.run_lab()
        self.assertEqual(repeated.returncode, 2)
        after = {str(path.relative_to(self.output)): path.read_bytes() for path in self.output.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_invalid_fixture_is_rejected_before_output_creation(self):
        invalid = self.base / "invalid.json"
        invalid.write_text('{"schema_version":', encoding="utf-8")
        result = self.run_lab("--scenario", invalid)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(self.output.exists())

    def test_unexpected_arguments_do_not_retry_even_with_large_attempt_limit(self):
        scenario = self.fixture([self.error_step(arguments={"note_id": "different"})])
        result = self.run_lab("--scenario", scenario, "--max-attempts", "10")
        self.assertEqual(result.returncode, 1, result.stderr)
        summary = self.summary()
        self.assertEqual((summary["attempts"], summary["retries"]), (1, 0))
        self.assertEqual(summary["failure"]["code"], "arguments_mismatch")
        self.assertEqual(summary["fixture_summary"]["rejected"], 1)

    def test_unexpected_call_type_is_propagated_by_api(self):
        from tool_mockbox import UnexpectedCall
        scenario = self.fixture([self.error_step(arguments={"note_id": "different"})])
        with self.assertRaises(UnexpectedCall) as raised:
            lab.run_lab(self.output, scenario=scenario, max_attempts=10)
        self.assertEqual(raised.exception.code, "arguments_mismatch")
        self.assertEqual(self.summary()["attempts"], 1)

    def test_non_temporary_failure_is_not_retried(self):
        scenario = self.fixture([self.error_step(code="permanent"), self.error_step()])
        result = self.run_lab("--scenario", scenario)
        self.assertEqual(result.returncode, 1)
        summary = self.summary()
        self.assertEqual(summary["attempts"], 1)
        self.assertEqual(summary["failure"]["code"], "permanent")

    def test_attempt_cap_stops_before_success_and_keeps_evidence(self):
        result = self.run_lab("--max-attempts", "2")
        self.assertEqual(result.returncode, 1)
        summary = self.summary()
        self.assertEqual(summary["outcome"], "failed")
        self.assertEqual((summary["attempts"], summary["retries"]), (2, 1))
        self.assertEqual(summary["fixture_summary"]["ok"], 0)
        self.assertEqual(summary["failure"]["code"], "temporary")

    def test_exhausted_sequence_is_not_retried_until_attempt_cap(self):
        scenario = self.fixture([self.error_step()])
        result = self.run_lab("--scenario", scenario, "--max-attempts", "10")
        self.assertEqual(result.returncode, 1)
        summary = self.summary()
        self.assertEqual(summary["attempts"], 2)
        self.assertEqual(summary["failure"]["code"], "sequence_exhausted")

    def test_attempt_bounds_are_checked_before_output_creation(self):
        for value in ("0", "11", "-1", "1.5"):
            with self.subTest(value=value):
                result = self.run_lab("--max-attempts", value)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.output.exists())

    def test_final_success_does_not_bypass_trace_budgets(self):
        scenario = self.fixture([self.error_step(), self.error_step(), self.error_step(),
                                 {"arguments": {"note_id": "release"}, "status": "ok", "result": "synthetic success"}])
        result = self.run_lab("--scenario", scenario, "--max-attempts", "4")
        self.assertEqual(result.returncode, 1, result.stderr)
        summary = self.summary()
        self.assertEqual(summary["outcome"], "recovered")
        self.assertEqual(summary["attempts"], 4)
        self.assertEqual(summary["trace_budget_exit"], 1)
        self.assertNotIn("Traceback", result.stderr)

    def test_trace_viewer_escapes_diagnostic_content(self):
        report = {"summary": {"calls": 1, "errors": 1, "pending": 0, "findings": 1},
                  "findings": [{"severity": "warning", "code": "<script>", "message": '<img src=x onerror="example">'}]}
        rendered = lab.render_trace_viewer(report)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img", rendered)


if __name__ == "__main__":
    unittest.main()
