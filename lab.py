"""Run a bounded, scripted failure-recovery lab without a model or paid API."""

import argparse
import html
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "lab-fixtures"


class LabError(ValueError):
    """The lab configuration or a required diagnostic process is invalid."""


class LabBudgetError(LabError):
    """A completed fixture run exceeded the lab's declared trace budgets."""


def _dependencies():
    try:
        from agent_tracecheck.recording import TraceRecorder
        from context_budgetpack import build_bundle, verify_bundle, write_bundle
        from context_budgetpack.core import load_plan
        from tool_mockbox import MockToolbox, MockToolError, UnexpectedCall
        from tool_mockbox.report import render_report
    except ImportError as error:
        raise LabError("Install the optional lab dependencies described in README before running lab.py") from error
    return TraceRecorder, build_bundle, verify_bundle, write_bundle, load_plan, MockToolbox, MockToolError, UnexpectedCall, render_report


def call_with_retry(toolbox, recorder, *, max_attempts):
    """Retry only scripted temporary errors; reject mismatches immediately."""
    from tool_mockbox import MockToolError, UnexpectedCall

    if type(max_attempts) is not int or not 1 <= max_attempts <= 10:
        raise LabError("max_attempts must be an integer from 1 to 10")
    arguments = {"note_id": "release"}
    for attempt in range(1, max_attempts + 1):
        try:
            return recorder.call("lookup_note", arguments,
                                 lambda: toolbox.call("lookup_note", arguments))
        except UnexpectedCall:
            raise  # A fixture mismatch, unknown tool or exhausted sequence is not retryable.
        except MockToolError as error:
            if error.code != "temporary" or attempt == max_attempts:
                raise


def _write(path, text):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def _diagnose(trace, output_format):
    # Use the installed CLI, rather than duplicating the checker in this example.
    command = [sys.executable, "-m", "agent_tracecheck", str(trace),
               "--max-calls", "3", "--max-errors", "2", "--repeat-threshold", "3",
               "--format", output_format]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=30)
    if result.returncode not in (0, 1):
        raise LabError(f"Trace checker could not read the recorded trace: {result.stderr.strip()}")
    return result.returncode, result.stdout


def render_trace_viewer(report):
    """A starter-owned HTML view of the installed checker's JSON diagnostics."""
    escape = lambda value: html.escape(str(value), quote=True)
    summary = report["summary"]
    findings = "".join(
        f'<tr><td>{escape(item["severity"])}</td><td><code>{escape(item["code"])}</code></td><td>{escape(item["message"])}</td></tr>'
        for item in report["findings"])
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Agent CI starter · Recovery trace</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f7fb;color:#20344b;font:16px/1.65 system-ui,sans-serif}}main{{max-width:1040px;margin:auto;padding:40px 24px}}h1{{font-size:36px;line-height:1.15}}p{{max-width:850px}}.card{{background:white;border:1px solid #d9e2ee;border-radius:12px;padding:22px;margin:24px 0;overflow:auto}}.metrics{{display:flex;gap:35px;flex-wrap:wrap}}strong{{font-size:28px}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;padding:13px;border-bottom:1px solid #d9e2ee;vertical-align:top}}a{{color:#245fa1}}code{{overflow-wrap:anywhere}}footer{{color:#566a80;font-size:13px}}
</style></head><body><main><p>AGENT CI STARTER / SCRIPTED RECOVERY LAB</p><h1>Recovery keeps a record.<br>恢复成功，失败记录仍然保留。</h1>
<p>The default fixture is designed to fail twice before succeeding; another fixture or a lower attempt cap may stop earlier. A successful final response does not remove earlier errors. These findings describe recorded calls, not model quality. / 默认脚本预设两次失败后成功；替换脚本或降低尝试上限可能提前停止。最终恢复不会抹去此前的失败记录。</p>
<section class="card metrics"><div><strong>{summary['calls']}</strong><br>Calls / 调用</div><div><strong>{summary['errors']}</strong><br>Errors / 失败</div><div><strong>{summary['pending']}</strong><br>Pending / 未完成</div><div><strong>{summary['findings']}</strong><br>Findings / 诊断</div></section>
<nav><a href="trace.jsonl">Raw trace</a> · <a href="trace-report.md">Checker Markdown</a> · <a href="trace-report.json">Checker JSON</a> · <a href="fixture-run.html">Fixture events</a> · <a href="context/report.html">Context selection</a> · <a href="lab-summary.json">Lab summary</a></nav>
<section class="card"><h2>Recorded-call findings / 调用诊断</h2><table><thead><tr><th>Level</th><th>Code</th><th>Finding</th></tr></thead><tbody>{findings or '<tr><td colspan="3">No findings under the selected budgets.</td></tr>'}</tbody></table></section>
<footer>This HTML viewer belongs to the starter. Diagnostics come from the installed agent-tracecheck CLI with a 3-call, 2-error budget. Warnings remain visible. The example does not call a model, a live service or a paid API. Only synthetic fixture data is used.</footer></main></body></html>
'''


def run_lab(output, *, scenario=None, max_attempts=3):
    """Create new artifacts, recording fixture failure and propagating its error."""
    if type(max_attempts) is not int or not 1 <= max_attempts <= 10:
        raise LabError("max_attempts must be an integer from 1 to 10")
    (TraceRecorder, build_bundle, verify_bundle, write_bundle, load_plan,
     MockToolbox, MockToolError, UnexpectedCall, render_fixture_report) = _dependencies()
    source_root = FIXTURES / "workspace"
    context, manifest = build_bundle(load_plan(FIXTURES / "context-plan.json"), source_root, max_bytes=1600)
    toolbox = MockToolbox.from_file(scenario or FIXTURES / "retry-scenario.json", no_wait=True)
    target = Path(output)
    target.mkdir(parents=True, exist_ok=False)
    write_bundle(context, manifest, target / "context")
    if not verify_bundle(target / "context", source_root)["ok"]:
        raise LabError("The freshly generated synthetic context failed source verification")

    failure = None
    result = None
    with TraceRecorder(target / "trace.jsonl") as recorder:
        try:
            result = call_with_retry(toolbox, recorder, max_attempts=max_attempts)
        except MockToolError as error:
            # Preserve evidence for a failed run, then propagate the original
            # error below. This includes UnexpectedCall; it is never retried.
            failure = error

    fixture_report = toolbox.report()
    _write(target / "fixture-run.json", json.dumps(fixture_report, ensure_ascii=False, indent=2) + "\n")
    _write(target / "fixture-run.html", render_fixture_report(fixture_report))
    diagnostic_status, diagnostic_json = _diagnose(target / "trace.jsonl", "json")
    _, diagnostic_markdown = _diagnose(target / "trace.jsonl", "markdown")
    diagnostic_report = json.loads(diagnostic_json)
    _write(target / "trace-report.json", diagnostic_json)
    _write(target / "trace-report.md", diagnostic_markdown)
    _write(target / "trace-report.html", render_trace_viewer(diagnostic_report))
    counts = fixture_report["summary"]
    summary = {"schema_version": 1, "kind": "scripted_local_failure_recovery",
               "outcome": "failed" if failure else "recovered",
               "attempts": counts["calls"], "retries": max(0, counts["calls"] - 1),
               "max_attempts": max_attempts, "result": result,
               "failure": None if failure is None else {"code": failure.code, "message": failure.message},
               "context_budget": manifest["budget"], "fixture_summary": counts,
               "trace_summary": diagnostic_report["summary"],
               "trace_budgets": {"max_calls": 3, "max_errors": 2, "repeat_threshold": 3},
               "trace_budget_exit": diagnostic_status,
               "artifacts": {"context": "context/report.html", "fixture": "fixture-run.html",
                             "trace": "trace.jsonl", "diagnostics": "trace-report.html"}}
    _write(target / "lab-summary.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    if failure is not None:
        raise failure
    if diagnostic_status:
        raise LabBudgetError("The recorded run exceeded the lab's trace budgets; inspect the exported diagnostics")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new output directory; existing paths are refused")
    parser.add_argument("--scenario", type=Path, help="optional local replacement fixture for failure tests")
    parser.add_argument("--max-attempts", type=int, default=3, help="bounded attempts, from 1 to 10; default: 3")
    args = parser.parse_args(argv)
    try:
        from tool_mockbox import MockToolError
    except ImportError:
        print("lab: Install the optional lab dependencies described in README before running lab.py", file=sys.stderr)
        return 2
    try:
        summary = run_lab(args.output, scenario=args.scenario, max_attempts=args.max_attempts)
    except LabBudgetError as error:
        print(f"lab: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, ImportError, subprocess.SubprocessError) as error:
        print(f"lab: {error}", file=sys.stderr)
        return 2
    except MockToolError as error:
        # Fixture errors keep their specific type/code in the API; the command
        # reports a failed run without disguising it as a successful recovery.
        print(f"lab: fixture run failed ({error.code}); inspect the output evidence", file=sys.stderr)
        return 1
    print(f"Recovered after {summary['attempts']} scripted attempts; {summary['fixture_summary']['error']} errors remain recorded.")
    print(f"Open {str(args.output / 'trace-report.html')!r} to review the lab.")
    print("This is a scripted local failure-recovery test; no model or paid API is called.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
