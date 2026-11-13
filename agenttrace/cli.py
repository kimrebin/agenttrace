"""Thin CLI over the library: each subcommand is a few library calls."""

from __future__ import annotations

import argparse
from pathlib import Path

from agenttrace.adapters.codex import load
from agenttrace.render import render_to_file, diff
from agenttrace.runner import run_codex


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agenttrace")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_replay = sub.add_parser("replay", help="render a saved trace/rollout file")
    p_replay.add_argument("path")
    p_replay.add_argument("-o", "--out", required=True)
    p_replay.add_argument("--compare", default=None,
                          help="another session file; adds a prompt-diff panel vs this trace")
    p_replay.add_argument("--link-subagents", action="store_true",
                          help="resolve and nest Codex sub-agent child sessions")

    p_diff = sub.add_parser("diff", help="diff two runs' seed prompts")
    p_diff.add_argument("a")
    p_diff.add_argument("b")
    p_diff.add_argument("-o", "--out", required=True)

    p_run = sub.add_parser("run", help="run Codex, capture, render")
    p_run.add_argument("prompt")
    p_run.add_argument("-o", "--out", required=True)

    args = parser.parse_args(argv)

    if args.cmd == "replay":
        trace = load(args.path, link_subagents=args.link_subagents)
        other = load(args.compare) if args.compare else None
        render_to_file(trace, args.out, compare_to=other)
    elif args.cmd == "diff":
        Path(args.out).write_text(diff(load(args.a), load(args.b)), encoding="utf-8")
    elif args.cmd == "run":
        render_to_file(run_codex(args.prompt), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
