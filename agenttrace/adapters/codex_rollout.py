"""Post-hoc replay of a saved Codex rollout file (`~/.codex/sessions/.../
rollout-*.jsonl`).

Rollouts changed shape across CLI versions and record the same action in
several channels, which would double-count if all were mapped:

- older sessions use `response_item` API items (function_call / custom_tool_call
  / message / reasoning) plus `event_msg` telemetry echoes (exec_command_end,
  patch_apply_end, …) of the same calls;
- newer sessions use `item_completed` wrappers (UserMessage / AgentMessage /
  CommandExecution / Reasoning / FileChange / Extension).

To avoid duplicates we pick ONE canonical channel per file: if any
`item_completed` is present we trust only that (plus error/abort), otherwise we
trust `response_item` (plus user_message/error/abort) and drop the event_msg
tool echoes. Reasoning is stored encrypted/empty, so the chain-of-thought is not
recoverable here — only commentary and the tool trace survive.
"""

from __future__ import annotations

import json
from typing import Iterable

from agenttrace.model import Trace, Turn, Event


def _text_from_content(item: dict) -> str:
    parts = []
    for chunk in item.get("content", []) or []:
        if isinstance(chunk, dict) and chunk.get("text"):
            parts.append(chunk["text"])
    return "\n".join(parts)


def _join_list(value) -> str:
    if isinstance(value, list):
        out = []
        for v in value:
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, dict) and v.get("text"):
                out.append(v["text"])
        return "\n".join(out)
    return value or ""


def _cmd_str(command) -> str:
    if isinstance(command, list):
        return " ".join(str(c) for c in command)
    return str(command or "")


def parse_rollout(lines: Iterable[str]) -> Trace:
    objs = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            objs.append(json.loads(line))
        except (ValueError, TypeError):
            objs.append({"_raw_line": line})

    item_mode = any(isinstance(o, dict) and (o.get("payload") or {}).get("type") == "item_completed"
                    for o in objs)

    trace = Trace(run_id=None, agent="codex",
                  seed={"system_prompt": None, "user_input": None},
                  turns=[], incomplete=False)
    turn = Turn(seq=0, events=[], meta={})
    trace.turns.append(turn)
    state = {"n": 0, "noted_encrypted": False}
    seen_text: set[str] = set()
    sub_seen: set[str] = set()

    def add(type: str, data: dict, raw: dict | None = None) -> None:
        turn.events.append(Event(id=f"e{state['n']}", type=type, timestamp=None,
                                 raw=raw, data=data))
        state["n"] += 1

    def add_reasoning(text: str, role: str | None) -> None:
        key = (text or "").strip()
        if key and key in seen_text:
            return
        if key:
            seen_text.add(key)
        data = {"text": text}
        if role:
            data["role"] = role
        add("reasoning", data)

    def set_user(text: str) -> None:
        if text and not trace.seed.get("user_input"):
            trace.seed["user_input"] = text

    def note_encrypted() -> None:
        if not state["noted_encrypted"]:
            add("meta", {"note": "reasoning encrypted — unavailable in rollout"})
            state["noted_encrypted"] = True

    def command_events(name: str, args: str, output: str, exit_code, call_id) -> None:
        add("tool_call", {"name": name, "arguments": args, "call_id": call_id})
        out = {"name": name, "output": output, "exit_code": exit_code, "call_id": call_id}
        if exit_code not in (None, 0):
            add("error", out)
        else:
            add("tool_result", {"output": output, "exit_code": exit_code, "call_id": call_id})

    def handle_item(it: dict) -> None:
        t = it.get("type")
        if t == "UserMessage":
            set_user(_text_from_content(it))
        elif t == "AgentMessage":
            add_reasoning(_text_from_content(it), "agent_message")
        elif t == "Reasoning":
            txt = _join_list(it.get("summary_text"))
            if txt:
                add_reasoning(txt, None)
            else:
                note_encrypted()
        elif t == "CommandExecution":
            command_events("command", _cmd_str(it.get("command")),
                           it.get("aggregated_output", ""), it.get("exit_code"),
                           it.get("id"))
        elif t == "FileChange":
            cid = it.get("id")
            paths = list((it.get("changes") or {}).keys())
            add("tool_call", {"name": "file_change", "arguments": "\n".join(paths),
                              "call_id": cid})
            ok = it.get("stdout") or it.get("stderr") or ("ok" if it.get("status") else "")
            add("tool_result", {"output": ok, "call_id": cid})
        elif t == "Extension":
            cid = it.get("id")
            results = it.get("results") or []
            out = "\n".join(r.get("snippet", "") for r in results if isinstance(r, dict))
            add("tool_call", {"name": "extension:" + str(it.get("kind")),
                              "arguments": it.get("query", ""), "call_id": cid})
            add("tool_result", {"output": out, "call_id": cid})
        elif t == "SubAgentActivity":
            # delegation to a sub-agent that runs in a separate thread/session;
            # one tool_call per child thread (call_id = child thread id) so a
            # linker can hang the child's trace under it.
            cid = it.get("agent_thread_id")
            if it.get("kind") == "started" and cid and cid not in sub_seen:
                sub_seen.add(cid)
                path = it.get("agent_path") or ""
                add("tool_call", {"name": "sub_agent:" + str(path),
                                  "arguments": str(path), "call_id": cid})
        elif t == "CollabAgentToolCall":
            add("meta", {"note": "collab: " + str(it.get("tool") or "")}, raw={"item": it})
        else:
            add("unknown", {"item_type": t}, raw={"item": it})

    def handle_error(payload: dict) -> None:
        add("error", {"message": payload.get("message", "")}, raw=payload)

    def handle_abort(payload: dict) -> None:
        add("error", {"message": "turn aborted: " + str(payload.get("reason", ""))},
            raw=payload)

    for o in objs:
        if "_raw_line" in o:
            add("unknown", {}, raw=o)
            continue
        ttype = o.get("type")
        payload = o.get("payload", {}) or {}
        ptype = payload.get("type")

        if ttype == "session_meta":
            trace.run_id = payload.get("session_id") or payload.get("id")
            bi = payload.get("base_instructions")
            trace.seed["system_prompt"] = bi.get("text") if isinstance(bi, dict) else bi
            continue
        if ttype == "turn_context":
            continue

        if item_mode:
            if ptype == "item_completed":
                handle_item(payload.get("item") or {})
            elif ptype == "error":
                handle_error(payload)
            elif ptype == "turn_aborted":
                handle_abort(payload)
            # ignore response_item / event_msg echoes in item mode
            continue

        # response-item mode
        if ptype == "agent_message":
            add_reasoning(payload.get("message", ""), "agent_message")
        elif ptype == "user_message":
            set_user(payload.get("message", ""))
        elif ptype == "message":
            role = payload.get("role")
            text = _text_from_content(payload)
            if role == "assistant":
                add_reasoning(text, "assistant")
            elif role == "user":
                set_user(text)
            # developer/system boilerplate skipped
        elif ptype == "function_call":
            add("tool_call", {"name": payload.get("name", ""),
                              "arguments": payload.get("arguments", ""),
                              "call_id": payload.get("call_id")})
        elif ptype == "function_call_output":
            add("tool_result", {"output": payload.get("output", ""),
                                "call_id": payload.get("call_id")})
        elif ptype == "custom_tool_call":
            add("tool_call", {"name": payload.get("name", ""),
                              "arguments": payload.get("input", ""),
                              "call_id": payload.get("call_id")})
        elif ptype == "custom_tool_call_output":
            add("tool_result", {"output": payload.get("output", ""),
                                "call_id": payload.get("call_id")})
        elif ptype == "web_search_call":
            q = (payload.get("action") or {}).get("query", "")
            add("tool_call", {"name": "web_search", "arguments": q,
                              "call_id": payload.get("call_id")})
        elif ptype == "reasoning":
            note_encrypted()
        elif ptype == "error":
            handle_error(payload)
        elif ptype == "turn_aborted":
            handle_abort(payload)
        elif ptype in ("token_count", "task_started", "task_complete",
                       "exec_command_end", "patch_apply_end", "web_search_end",
                       "exec_command_begin", "patch_apply_begin"):
            continue  # noise, or an event_msg echo already covered by response_item
        else:
            add("unknown", {"item_type": ptype}, raw=o)

    return trace


def parse_rollout_file(path: str) -> Trace:
    with open(path, encoding="utf-8") as f:
        return parse_rollout(f)


def _first_session_id(path: str) -> str | None:
    """The thread id a rollout file belongs to (session_meta.id, which for a
    sub-agent file is the child thread id)."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                o = json.loads(line)
                if o.get("type") == "session_meta":
                    return (o.get("payload") or {}).get("id")
                return None
    except (OSError, ValueError):
        return None
    return None


def _index_sessions(sessions_dir: str) -> dict:
    import glob
    import os
    index = {}
    for fp in glob.glob(os.path.join(sessions_dir, "**", "*.jsonl"), recursive=True):
        tid = _first_session_id(fp)
        if tid and tid not in index:
            index[tid] = fp
    return index


def link_sub_agents(trace: Trace, sessions_dir: str) -> Trace:
    """Resolve Codex sub-agent delegations: each `sub_agent:*` tool_call whose
    call_id is a child thread id is linked to that child's rollout (found in
    `sessions_dir` by session id) and nested as a sub_trace. Recurses into
    grandchildren; a visited set guards against cycles."""
    index = _index_sessions(sessions_dir)
    _link(trace, index, set())
    return trace


def _link(trace: Trace, index: dict, visited: set) -> None:
    for turn in trace.turns:
        for ev in turn.events:
            if ev.type == "tool_call" and str(ev.data.get("name", "")).startswith("sub_agent"):
                cid = ev.data.get("call_id")
                if cid and cid in index and cid not in visited:
                    visited.add(cid)
                    child = parse_rollout_file(index[cid])
                    _link(child, index, visited)
                    ev.data["sub_trace"] = child.to_dict()
