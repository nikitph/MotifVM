from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .audit import export_audit_pack
from .adversarial import run_adversarial
from .eval import run_evaluation
from .graph import compare_states
from .reporting import load_state, render_report
from .runtime import run_task
from .storage import ensure_store, read_json, write_json
from .verify_pack import verify_pack


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="motifvm")
    parser.add_argument("--root", default=".", help="Workspace root. Defaults to current directory.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Parse/diagnose/plan/execute/verify/commit a task or state file.")
    run.add_argument("input", help="Natural language request or path to a TaskAST/CognitiveState JSON file.")
    run.add_argument("--domain", default=None, help="Domain profile name, e.g. dccb_audit.")
    run.add_argument("--input", action="append", dest="input_files", help="Input artifact path. Can be repeated.")
    run.add_argument("--llm", choices=["mock", "deepseek"], default=None, help="Use a structured LLM provider.")
    run.add_argument("--dry-run", action="store_true", help="Plan only; do not execute passes.")
    run.add_argument("--verbose", action="store_true", help="Print pass execution progress.")
    run.add_argument("--json", action="store_true", help="Print the resulting state JSON.")

    run_task_cmd = sub.add_parser("run-task", help="Alias for run.")
    run_task_cmd.add_argument("input")
    run_task_cmd.add_argument("--domain", default=None)
    run_task_cmd.add_argument("--input", action="append", dest="input_files")
    run_task_cmd.add_argument("--llm", choices=["mock", "deepseek"], default=None)
    run_task_cmd.add_argument("--dry-run", action="store_true")
    run_task_cmd.add_argument("--verbose", action="store_true")
    run_task_cmd.add_argument("--json", action="store_true")

    report = sub.add_parser("report", help="Render a report for the current or specified state.")
    report.add_argument("state", nargs="?", default=None, help="Optional state JSON path.")
    report.add_argument("--graph", action="store_true", help="Include graph node details.")
    report.add_argument("--json", action="store_true", help="Print raw state JSON.")

    export = sub.add_parser("export-audit", help="Export a portable audit pack for a commit.")
    export.add_argument("commit_id", help="Commit ID, or 'current'.")
    export.add_argument("--output", default=None, help="Output directory. Defaults to audit_pack/<commit-id>.")

    compare = sub.add_parser("compare-runs", help="Compare two committed states.")
    compare.add_argument("commit_a")
    compare.add_argument("commit_b")
    compare.add_argument("--json", action="store_true")

    evaluate = sub.add_parser("eval", help="Run the MotifVM evaluation harness.")
    evaluate.add_argument("--expected", default=None, help="Expected outcomes JSON. Defaults to eval/expected.json.")

    adversarial = sub.add_parser("adversarial", help="Run adversarial evaluation suite.")
    adversarial.add_argument("--expected", default=None)

    verify = sub.add_parser("verify-pack", help="Verify an exported audit pack.")
    verify.add_argument("pack")
    verify.add_argument("--json", action="store_true")

    init = sub.add_parser("init", help="Initialize .motifvm directories.")
    init.add_argument("--domain", default=None)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    try:
        if args.command == "init":
            store = ensure_store(root)
            print(f"Initialized {store}")
            return
        if args.command in {"run", "run-task"}:
            state = run_task(
                args.input,
                root=root,
                domain=args.domain,
                input_files=args.input_files,
                llm_provider=args.llm,
                dry_run=args.dry_run,
                verbose=args.verbose,
            )
            if args.json:
                print(json.dumps(state, indent=2, sort_keys=True))
            else:
                output_path = ensure_store(root) / "state" / "current.json"
                commit = state.get("parentCommit") or "uncommitted"
                print(f"State: {state['status']} ({commit})")
                print(f"Wrote: {output_path}")
                final = next(
                    (
                        artifact.get("content", {}).get("text")
                        for artifact in state.get("artifacts", [])
                        if artifact.get("type") == "final_output"
                    ),
                    None,
                )
                if final:
                    print(final)
            return
        if args.command == "report":
            state = load_state(root, args.state)
            if args.json:
                print(json.dumps(state, indent=2, sort_keys=True))
            else:
                print(render_report(state, show_graph=args.graph))
            return
        if args.command == "export-audit":
            output = Path(args.output).resolve() if args.output else None
            target = export_audit_pack(root, args.commit_id, output)
            print(f"Exported audit pack: {target}")
            return
        if args.command == "compare-runs":
            store = ensure_store(root)
            a = read_json(store / "state" / "commits" / f"{args.commit_a}.json")
            b = read_json(store / "state" / "commits" / f"{args.commit_b}.json")
            diff = compare_states(a, b)
            if args.json:
                print(json.dumps(diff, indent=2, sort_keys=True))
            else:
                print(f"Terminal: {diff['terminalStatus']['a']} -> {diff['terminalStatus']['b']}")
                print(f"Reason: {diff['terminalReason']['a']} -> {diff['terminalReason']['b']}")
                print(f"Invariant diffs: {len(diff['invariants'])}")
                print(f"Claim additions: {', '.join(diff['claims']['added']) or 'none'}")
                print(f"Artifact additions: {', '.join(diff['artifacts']['added']) or 'none'}")
            return
        if args.command == "eval":
            expected = Path(args.expected).resolve() if args.expected else None
            target = run_evaluation(root, expected)
            print(f"Evaluation outputs written to {target}")
            return
        if args.command == "adversarial":
            expected = Path(args.expected).resolve() if args.expected else None
            target = run_adversarial(root, expected)
            print(f"Adversarial outputs written to {target}")
            return
        if args.command == "verify-pack":
            ok, issues = verify_pack(Path(args.pack))
            if args.json:
                print(json.dumps({"ok": ok, "issues": issues}, indent=2, sort_keys=True))
            elif ok:
                print("Audit pack verified")
            else:
                for issue in issues:
                    print(f"{issue['check']}: {issue['message']}")
            if not ok:
                raise SystemExit(1)
            return
        parser.error(f"Unsupported command: {args.command}")
    except Exception as exc:
        print(f"motifvm: error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
