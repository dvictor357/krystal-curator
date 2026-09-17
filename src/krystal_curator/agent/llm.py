"""The agent loop: one local model, our read-only tools, grammar-constrained JSON.

Every step the model returns one JSON object — `{"thought", "action"}` where the action
is either one tool call (name + arguments, each tool with its own argument schema) or
the final answer (the task's schema). llama.cpp enforces that schema token by token
(`response_format: json_schema`), so a 2B model cannot produce an unparsable step; it
can still pick a pointless tool or stop early, which the trace shows. Tool results go
back as plain user messages. Nothing here writes anywhere: tools are read-only by
construction (`tools.py`) and the loop has no side effects but the report.

Numbers in the final answer are checked against the numbers the tools returned; any
that never appeared in a tool result are listed as `unverified` — a small model
invents figures, and the report must say which ones it did not get from us.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from .. import net
from ..config import Agent
from .server import AgentError

TOOL_RESULT_CHARS = 7000  # ≈ 1,700 tokens; a compacted review fits, raw payloads never do
CONTEXT_HEADROOM = 0.75  # compact old tool results once the prompt passes this share of ctx


@dataclass(slots=True)
class Tool:
    name: str
    description: str
    params: dict[str, Any]  # JSON-schema `properties` of the arguments
    fn: Callable[..., Any]
    required: list[str] = field(default_factory=list)

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tool": {"const": self.name},
                "args": {
                    "type": "object",
                    "properties": self.params,
                    "required": self.required,
                    "additionalProperties": False,
                },
            },
            "required": ["tool", "args"],
            "additionalProperties": False,
        }

    def signature(self) -> str:
        args = ", ".join(
            f"{k}: {v.get('type', 'any')}" + ("" if k in self.required else "?")
            for k, v in self.params.items()
        )
        return f"{self.name}({args}) — {self.description}"


@dataclass(slots=True)
class Step:
    thought: str
    tool: str  # "" on the final step
    args: dict[str, Any]
    result: str  # what the model saw (already trimmed), "" on the final step
    error: str = ""
    elapsed_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(slots=True)
class AgentRun:
    task: str
    model: str
    steps: list[Step] = field(default_factory=list)
    final: dict[str, Any] | None = None
    stopped: str = ""  # final / forced_final (budget gone, answer demanded) / max_steps / error
    error: str = ""
    elapsed_s: float = 0.0
    unverified: list[str] = field(default_factory=list)  # numbers not seen in any tool result

    @property
    def tool_calls(self) -> int:
        return sum(1 for s in self.steps if s.tool)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Client:
    """One chat completion against llama-server's OpenAI-compatible endpoint."""

    def __init__(self, base_url: str, cfg: Agent) -> None:
        self.base_url = base_url.rstrip("/")
        self.cfg = cfg
        self.model = ""

    def complete(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> dict[str, Any]:
        body = {
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "step", "schema": schema},
            },
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
            # thinking on/off is the only per-request control llama-server 0.4 honours
            # (a per-request `reasoning_budget` is ignored); the cap is a server flag
            "chat_template_kwargs": {"enable_thinking": self.cfg.reasoning_budget > 0},
        }
        try:
            r = net.post(
                f"{self.base_url}/v1/chat/completions",
                json=body,
                timeout=self.cfg.timeout,
                retries=0,
            )
        except net.HttpError as e:
            raise AgentError(f"agent: model call failed: {e}") from None
        if r.status_code != 200:
            raise AgentError(f"agent: model call HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        self.model = (data.get("model") or self.model).rsplit("/", 1)[-1]  # basename of a GGUF path
        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        try:
            parsed = json.loads(content)
        except ValueError:
            reasoning = (choice.get("message") or {}).get("reasoning_content") or ""
            raise AgentError(
                "agent: model returned no JSON "
                f"(finish={choice.get('finish_reason')}, completion={usage.get('completion_tokens')} "
                f"tokens, reasoning={len(reasoning)} chars): {content[:120]!r}"
            ) from None
        if not isinstance(parsed, dict):
            raise AgentError("agent: model step is not an object")
        parsed["_usage"] = usage
        parsed["_finish"] = choice.get("finish_reason") or ""
        return parsed


def step_schema(tools: list[Tool], final_schema: dict[str, Any]) -> dict[str, Any]:
    """`tools` empty ⇒ the only legal action is the final answer (the forced last step)."""
    final = {
        "type": "object",
        "properties": {"final": final_schema},
        "required": ["final"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "thought": {"type": "string", "maxLength": 400},
            "action": {"anyOf": [*[t.schema() for t in tools], final]} if tools else final,
        },
        "required": ["thought", "action"],
        "additionalProperties": False,
    }


FORCE_FINAL = (
    "Tool budget exhausted. Answer now with `final` from the results above; say what "
    "is unknown instead of calling another tool."
)
REPEAT_NOTE = "identical to step {n}; that result is unchanged — use it and answer with `final`"
SAME_TOOL_LIMIT = 3  # a fourth call of the same tool is a loop, not research: force the answer


def system_prompt(role: str, tools: list[Tool], max_steps: int) -> str:
    lines = [
        role,
        "",
        (
            "You work in steps. Each step you output one JSON object: a short `thought` and one "
            "`action`, which is either one tool call or your `final` answer. Tool results come "
            "back in the next message. You never write anything anywhere; tools only read."
        ),
        f"You have at most {max_steps} tool calls; give the final answer before that.",
        (
            "Use only numbers that appeared in tool results; if a fact is not in a tool result, "
            "say it is unknown instead of guessing. Vault addresses come from tool results "
            "(leaderboard, my_positions) or the task text — never invent one."
        ),
        "",
        "Tools:",
        *[f"- {t.signature()}" for t in tools],
    ]
    return "\n".join(lines)


def _trim(text: str, limit: int = TOOL_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 40] + f"\n…[truncated, {len(text) - limit + 40} more chars]"


_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?![\w.])")


def _forms(raw: str) -> set[str]:
    """The ways one number can be written: exact (≤ 2 decimals) and rounded to an integer.
    Magnitude < 10 is ignored: small integers are counts and ordinals, not facts."""
    try:
        x = abs(float(raw.replace(",", "")))
    except ValueError:
        return set()
    if x < 10:
        return set()
    return {f"{x:.2f}".rstrip("0").rstrip("."), f"{round(x):d}"}


def _numbers(text: str) -> set[str]:
    out: set[str] = set()
    for m in _NUM.finditer(text):
        out |= _forms(m.group())
    return out


def _walk_text(obj: Any) -> str:
    if isinstance(obj, dict):
        return " ".join(_walk_text(v) for v in obj.values())
    if isinstance(obj, list):
        return " ".join(_walk_text(v) for v in obj)
    return str(obj)


def unverified_numbers(final: dict[str, Any], seen: str) -> list[str]:
    """Numbers in the answer none of whose forms appear in any tool result."""
    have = _numbers(seen)
    out: set[str] = set()
    for m in _NUM.finditer(_walk_text(final)):
        forms = _forms(m.group())
        if forms and not forms & have:
            out.add(m.group())
    return sorted(out)


def run(
    client: Client,
    *,
    role: str,
    task: str,
    tools: list[Tool],
    final_schema: dict[str, Any],
    max_steps: int = 8,
    ctx: int = 16384,
) -> AgentRun:
    """Drive the model until it answers, hits `max_steps` tool calls, or fails."""
    by_name = {t.name: t for t in tools}
    schema = step_schema(tools, final_schema)
    final_only = step_schema([], final_schema)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt(role, tools, max_steps)},
        {"role": "user", "content": task},
    ]
    out = AgentRun(task=task, model=client.model)
    seen = ""  # every tool result the model saw, for the number check
    t0 = time.monotonic()
    calls = 0  # tool calls so far; one extra round is allowed for the final answer
    forced = False
    while calls <= max_steps:
        t1 = time.monotonic()
        try:
            reply = client.complete(messages, final_only if forced else schema)
        except AgentError as e:
            out.stopped, out.error = "error", str(e)
            break
        usage = reply.pop("_usage", {}) or {}
        finish = reply.pop("_finish", "")
        thought = str(reply.get("thought") or "")
        action = reply.get("action") or {}
        st = Step(
            thought=thought,
            tool="",
            args={},
            result="",
            elapsed_s=time.monotonic() - t1,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        )
        out.steps.append(st)
        if finish == "length" and "final" not in action and "tool" not in action:
            st.error = "step cut off by max_tokens"
            out.stopped, out.error = "error", st.error
            break
        if "final" in action:
            out.final = action["final"]
            out.stopped = "forced_final" if forced else "final"
            break
        name = str(action.get("tool") or "")
        args = action.get("args") or {}
        st.tool, st.args = name, args
        messages.append({"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)})
        if calls >= max_steps:
            # one last round where the grammar allows nothing but the final answer
            st.error = "tool budget exhausted; answer forced"
            messages.append({"role": "user", "content": FORCE_FINAL})
            forced = True
            continue
        calls += 1
        tool = by_name.get(name)
        earlier = next(
            (i for i, p in enumerate(out.steps[:-1], 1) if p.tool == name and p.args == args),
            None,
        )
        if tool is None:
            result = {"error": f"unknown tool {name!r}"}
        elif earlier is not None:  # same call again: do not spend context on a second copy
            result = {"note": REPEAT_NOTE.format(n=earlier)}
        else:
            try:
                result = tool.fn(**args)
            except Exception as e:  # noqa: BLE001 — a tool failure is data for the model, not a crash
                result = {"error": f"{type(e).__name__}: {net.redact(str(e))[:300]}"}
        text = _trim(json.dumps(result, ensure_ascii=False, default=str))
        st.result = text
        seen += "\n" + text
        messages.append({"role": "user", "content": f"RESULT of {name}:\n{text}"})
        if sum(1 for p in out.steps if p.tool == name) >= SAME_TOOL_LIMIT and not forced:
            st.error = f"{name} called {SAME_TOOL_LIMIT}×; answer forced"
            messages.append({"role": "user", "content": FORCE_FINAL})
            forced = True
        # compact before the next call: the server's count is for the last prompt, the
        # result just appended is not in it yet (≈ 3.5 chars per token on this JSON)
        est = st.prompt_tokens + st.completion_tokens + len(text) / 3.5
        if ctx and est > ctx * CONTEXT_HEADROOM:
            _compact(messages)
    if not out.stopped:
        out.stopped, out.error = "max_steps", "the agent never gave a final answer"
    out.model = client.model or out.model
    out.elapsed_s = time.monotonic() - t0
    if out.final is not None:
        out.unverified = unverified_numbers(out.final, seen)
    return out


def _compact(messages: list[dict[str, str]]) -> None:
    """Shorten every tool result but the newest so the next step still fits the context."""
    results = [
        i
        for i, m in enumerate(messages)
        if m["role"] == "user" and m["content"].startswith("RESULT of ")
    ]
    for i in results[:-1]:
        head, _, body = messages[i]["content"].partition("\n")
        if len(body) > 600:
            messages[i]["content"] = f"{head}\n{body[:600]}…[compacted to fit the context]"
