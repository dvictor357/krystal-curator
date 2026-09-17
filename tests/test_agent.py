"""Local-LLM addon, offline: the loop against a scripted model, the server guard rails,
the compact tool views, the number check, the config section. No llama-server here."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from krystal_curator import net, vault_eval
from krystal_curator import vault_review as vr
from krystal_curator.agent import AgentError, LlamaServer, Session, llm, tasks, tools
from krystal_curator.agent.llm import Tool
from krystal_curator.cli import main
from krystal_curator.config import Agent, Config, load
from krystal_curator.vaults import _attach_strategies, _parse_vault

FIX = Path(__file__).parent / "fixtures" / "vault_review"


# ---- a scripted model -----------------------------------------------------------------


class Scripted:
    """Stands in for `llm.Client`: returns the next scripted step, records the schema."""

    def __init__(self, steps: list[dict[str, Any]], finish: str = "stop") -> None:
        self.steps = list(steps)
        self.schemas: list[dict[str, Any]] = []
        self.messages: list[list[dict[str, str]]] = []
        self.model = "fake.gguf"
        self.finish = finish

    def complete(self, messages, schema):
        self.schemas.append(schema)
        self.messages.append([dict(m) for m in messages])
        if not self.steps:
            raise AgentError("agent: script exhausted")
        step = dict(self.steps.pop(0))
        step["_usage"] = {"prompt_tokens": 100, "completion_tokens": 20}
        step["_finish"] = self.finish
        return step


def _tools(calls: list[tuple[str, dict]] | None = None) -> list[Tool]:
    calls = calls if calls is not None else []

    def echo(**kw):
        calls.append(("echo", kw))
        return {"echoed": kw, "tvl": 12345, "apr": 56.7}

    def boom(**kw):
        calls.append(("boom", kw))
        raise RuntimeError("feed down (token=SECRETSECRETSECRET)")

    return [
        Tool("echo", "echo the args", {"x": {"type": "string"}}, echo, required=["x"]),
        Tool("boom", "always fails", {}, boom),
    ]


FINAL = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


def _call(tool: str, **args) -> dict[str, Any]:
    return {"thought": f"call {tool}", "action": {"tool": tool, "args": args}}


def _final(answer: str) -> dict[str, Any]:
    return {"thought": "done", "action": {"final": {"answer": answer}}}


def test_loop_calls_tool_then_answers():
    calls: list = []
    client = Scripted([_call("echo", x="hi"), _final("tvl is 12,345 and apr 56.7%")])
    run = llm.run(client, role="r", task="t", tools=_tools(calls), final_schema=FINAL, max_steps=3)
    assert run.stopped == "final" and run.final == {"answer": "tvl is 12,345 and apr 56.7%"}
    assert calls == [("echo", {"x": "hi"})] and run.tool_calls == 1
    assert run.unverified == []  # both numbers came from the tool
    # the tool result went back as a user message the model can read
    assert any(m["content"].startswith("RESULT of echo:") for m in client.messages[1])
    assert (
        client.messages[0][0]["role"] == "system"
        and "echo(x: string)" in client.messages[0][0]["content"]
    )


def test_unverified_numbers_are_listed():
    client = Scripted([_call("echo", x="a"), _final("tvl 12345 but also 99,999 and 3 items")])
    run = llm.run(client, role="r", task="t", tools=_tools(), final_schema=FINAL)
    assert run.unverified == ["99,999"]  # 12345 seen, 3 too small to count


def test_tool_failure_is_data_not_a_crash_and_is_redacted(monkeypatch):
    net.register_secret("SECRETSECRETSECRET")
    client = Scripted([_call("boom"), _final("unknown")])
    run = llm.run(client, role="r", task="t", tools=_tools(), final_schema=FINAL)
    assert run.stopped == "final"
    assert "RuntimeError" in run.steps[0].result and "SECRET" not in run.steps[0].result


def test_identical_call_is_not_executed_twice():
    calls: list = []
    client = Scripted([_call("echo", x="a"), _call("echo", x="a"), _final("ok")])
    run = llm.run(client, role="r", task="t", tools=_tools(calls), final_schema=FINAL)
    assert len(calls) == 1
    assert "identical to step 1" in run.steps[1].result


def test_budget_exhausted_forces_a_final_only_schema():
    client = Scripted(
        [_call("echo", x="1"), _call("echo", x="2"), _call("echo", x="3"), _final("forced")]
    )
    run = llm.run(client, role="r", task="t", tools=_tools(), final_schema=FINAL, max_steps=2)
    assert run.stopped == "forced_final" and run.final == {"answer": "forced"}
    assert run.steps[2].error.startswith("tool budget exhausted")
    last = client.schemas[-1]["properties"]["action"]
    assert "anyOf" not in last and "final" in last["properties"]  # no tool option left
    assert client.messages[-1][-1]["content"] == llm.FORCE_FINAL


def test_same_tool_looping_forces_the_answer_early():
    client = Scripted(
        [_call("echo", x="1"), _call("echo", x="2"), _call("echo", x="3"), _final("done")]
    )
    run = llm.run(client, role="r", task="t", tools=_tools(), final_schema=FINAL, max_steps=8)
    assert run.stopped == "forced_final" and run.tool_calls == 3
    assert "called 3×" in run.steps[2].error


def test_model_error_ends_the_run_with_the_reason():
    client = Scripted([])
    run = llm.run(client, role="r", task="t", tools=_tools(), final_schema=FINAL)
    assert run.stopped == "error" and "script exhausted" in run.error and run.final is None


def test_step_cut_by_max_tokens_is_an_error():
    client = Scripted([{"thought": "…", "action": {}}], finish="length")
    run = llm.run(client, role="r", task="t", tools=_tools(), final_schema=FINAL)
    assert run.stopped == "error" and "max_tokens" in run.error


def test_step_schema_shapes():
    s = llm.step_schema(_tools(), FINAL)
    options = s["properties"]["action"]["anyOf"]
    assert [o["properties"].get("tool", {}).get("const") for o in options] == ["echo", "boom", None]
    assert options[0]["properties"]["args"]["required"] == ["x"]
    only = llm.step_schema([], FINAL)
    assert only["properties"]["action"]["properties"]["final"] is FINAL


def test_context_compaction_keeps_the_newest_result():
    big = "x" * 5000
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": f"RESULT of a:\n{big}"},
        {"role": "assistant", "content": "{}"},
        {"role": "user", "content": f"RESULT of b:\n{big}"},
    ]
    llm._compact(msgs)
    assert len(msgs[1]["content"]) < 700 and "compacted" in msgs[1]["content"]
    assert len(msgs[3]["content"]) > 5000


# ---- server guard rails ------------------------------------------------------------------


def _health(monkeypatch, status: int, body: dict | None = None):
    def fake_get(url, **kw):
        assert url.endswith("/health")
        return httpx.Response(status, json=body or {}, request=httpx.Request("GET", url))

    monkeypatch.setattr(net, "get", fake_get)


def test_server_refuses_when_addon_is_off():
    with pytest.raises(AgentError, match="enabled = true"):
        LlamaServer(Agent(enabled=False)).ensure()


def test_server_attaches_to_a_healthy_base_url(monkeypatch):
    _health(monkeypatch, 200, {"status": "ok"})
    srv = LlamaServer(Agent(enabled=True, base_url="http://127.0.0.1:9999/"))
    assert srv.ensure() == "http://127.0.0.1:9999" and not srv.spawned


def test_server_reports_a_dead_base_url(monkeypatch):
    _health(monkeypatch, 503, {"status": "loading"})
    with pytest.raises(AgentError, match="no llama-server answering"):
        LlamaServer(Agent(enabled=True, base_url="http://127.0.0.1:9999")).ensure()


def test_server_needs_a_model_to_spawn(tmp_path):
    with pytest.raises(AgentError, match="model = path"):
        LlamaServer(Agent(enabled=True)).ensure()
    with pytest.raises(AgentError, match="model not found"):
        LlamaServer(Agent(enabled=True, model=str(tmp_path / "nope.gguf"))).ensure()


def test_server_needs_the_binary(tmp_path):
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"GGUF")
    with pytest.raises(AgentError, match="not found; brew install"):
        LlamaServer(
            Agent(enabled=True, model=str(gguf), llama_server="no-such-binary-xyz")
        ).ensure()


# ---- tool views ----------------------------------------------------------------------------


def _review() -> vr.Review:
    detail = json.loads((FIX / "detail.json").read_text())
    rv = vr.Review(fetched_at="", chain_id=4663, address=detail["vaultAddress"].lower(), url="u")
    rv.vault = _parse_vault(detail, owned=False)
    _attach_strategies(rv.vault, detail)
    rv.settings = vr.parse_settings(json.loads((FIX / "settings.json").read_text()))
    plans = json.loads((FIX / "plans.json").read_text())
    rv.plans = [vr.parse_plan(r) for r in plans.get("data") or []]
    rv.plan_stats = vr.plan_stats(rv.plans, None)
    rv.perf["24h"] = vr.parse_perf("24h", json.loads((FIX / "perf_24h.json").read_text()))
    rv.served = {"detail": "ok", "settings": "ok"}
    return rv


def test_compact_review_fits_the_tool_budget_and_keeps_the_verdict():
    rv = _review()
    ev = vault_eval.evaluate(rv)
    c = tools.compact_review(rv, ev)
    text = json.dumps(c, default=str)
    assert len(text) < 2 * llm.TOOL_RESULT_CHARS  # trimmed once more by the loop if needed
    assert c["rule_verdict"]["verdict"] == ev.verdict
    assert {x["key"] for x in c["checks"]} == {x.key for x in ev.checks}
    assert c["settings"]["instructions"] == rv.settings.instructions[: tools.INSTRUCTIONS_CHARS]
    assert c["vault"]["address"] == rv.address and "closed_by_pair" in c


def test_toolbox_uses_the_seeded_review_instead_of_fetching(monkeypatch):
    rv = _review()
    ev = vault_eval.evaluate(rv)
    monkeypatch.setattr(vr, "fetch_review", lambda *a, **k: pytest.fail("fetched"))
    box = tools.Toolbox(Config(), chain_id=4663, wallet="")
    box.seed_review(rv, ev)
    out = box.t_vault_review(rv.address.upper())
    assert out["rule_verdict"]["verdict"] == ev.verdict
    names = [t.name for t in box.tools()]
    assert names == ["limits", "leaderboard", "vault_review", "pool", "my_positions"]
    assert box.t_my_positions() == {"error": "no wallet configured (KRYSTAL_WALLET)"}
    assert box.t_limits()["max_positions"] == vault_eval.DEFAULT_LIMITS.max_positions


# ---- tasks + rendering + report ------------------------------------------------------------


def test_session_review_seeds_and_renders(monkeypatch, tmp_path):
    rv = _review()
    ev = vault_eval.evaluate(rv)
    final = {
        "reading": "The owner farms USDG pairs with 10% ranges.",
        "agrees_with_rule_verdict": False,
        "disagreement": "fees are steady",
        "what_to_copy": ["harvest daily"],
        "what_to_change": ["range 10% -> 20%"],
        "adapted_instructions": "Keep ranges at 20% total.",
        "evidence": ["minimum_range_pct 10.0"],
        "confidence": "medium",
    }
    client = Scripted(
        [_call("vault_review", address=rv.address), {"thought": "ok", "action": {"final": final}}]
    )
    cfg = Config()
    cfg.agent = Agent(enabled=True, base_url="http://x")
    s = Session(cfg, chain_id=4663, wallet="")
    monkeypatch.setattr(s, "client", lambda: client)
    monkeypatch.setattr(vr, "fetch_review", lambda *a, **k: pytest.fail("fetched"))
    run = s.review(rv, ev)
    assert run.stopped == "final" and run.tool_calls == 1
    assert "vault_review" in client.messages[0][0]["content"]
    assert rv.address in client.messages[0][1]["content"]  # the task names the vault

    report = tasks.AgentReport(run)
    md = report.to_markdown()
    assert "## Agent reading — fake.gguf (1 tool calls" in md
    assert "agrees with the rule verdict: **no**" in md and "fees are steady" in md
    assert "### Worth copying" in md and "harvest daily" in md
    assert "Keep ranges at 20% total." in md and "<details>" in md
    assert report.to_dict()["final"] == final

    mdp, jsp = vr.write_review(rv, tmp_path, evaluation=ev, agent=report)
    assert "## Agent reading" in mdp.read_text()
    assert json.loads(jsp.read_text())["agent"]["stopped"] == "final"


def test_run_markdown_without_an_answer():
    run = llm.AgentRun(task="t", model="m", stopped="error", error="model call failed")
    assert "- no answer: model call failed" in tasks.run_markdown(run)


# ---- config + cli --------------------------------------------------------------------------


def test_agent_config_section(tmp_path, monkeypatch):
    (tmp_path / "config.toml").write_text(
        '[agent]\nenabled = true\nmodel = "~/models/x.gguf"\nport = 9000\nreasoning_budget = 300\n'
    )
    cfg = load(tmp_path / "config.toml")
    assert cfg.agent.enabled and cfg.agent.port == 9000 and cfg.agent.reasoning_budget == 300
    assert not cfg.agent.model.startswith("~") and cfg.agent.model.endswith("/models/x.gguf")
    assert Config().agent.enabled is False


def test_cli_ask_refuses_when_addon_is_off(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["ask", "anything"]) == 1
    assert "enabled = true" in capsys.readouterr().out
