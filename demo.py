"""Record a scripted local tool workflow, with no model or network requests."""

import argparse
from pathlib import Path
import sys

from agent_tracecheck.recording import TraceRecorder


NOTES = {"release": "Review contract changes before upgrading agent tools."}


def lookup_note(note_id: str) -> str:
    """Read one note from an in-memory dictionary."""
    return NOTES[note_id]


def count_words(text: str) -> int:
    """Count words in a local string."""
    return len(text.split())


def record_workflow(path: Path, scenario: str) -> dict:
    errors = 0
    with TraceRecorder(path) as recorder:
        text = recorder.call("lookup_note", {"note_id": "release"},
                             lambda: lookup_note("release"))
        word_count = recorder.call("count_words", {"text": text}, lambda: count_words(text))
        if scenario == "retry":
            for _ in range(3):
                try:
                    recorder.call("lookup_note", {"note_id": "missing"},
                                  lambda: lookup_note("missing"))
                except KeyError:
                    errors += 1  # Intentional failures for the diagnostic example.
    return {"calls": 2 + errors, "errors": errors, "word_count": word_count}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="new JSONL trace path; existing files are refused")
    parser.add_argument("--scenario", choices=("healthy", "retry"), default="healthy")
    args = parser.parse_args(argv)
    try:
        summary = record_workflow(args.trace, args.scenario)
    except OSError as error:
        print(f"demo: {error}", file=sys.stderr)
        return 2
    print(f"Recorded {summary['calls']} local calls and {summary['errors']} intentional errors.")
    print("This is a scripted tool workflow, not an LLM agent or model benchmark.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
