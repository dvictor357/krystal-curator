"""End-to-end TUI tests on a recorded top_pools payload (no network)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from textual.widgets import DataTable, OptionList

from krystal_curator import api
from krystal_curator import tui as tui_mod
from krystal_curator.models import Pool
from krystal_curator.store import Store

FIXTURE = Path(__file__).parent / "fixtures" / "top_pools_robinhood.json"


@pytest.fixture
def app(tmp_path, monkeypatch):
    rows = json.loads(FIXTURE.read_text())["result"]
    pools = [Pool.from_public(x) for x in rows]
    monkeypatch.setattr(api, "fetch_pools", lambda chain_id, **kw: list(pools))
    monkeypatch.setattr(tui_mod, "fetch_vaults", lambda *a, **k: [])
    # no DexScreener / logo downloads in tests
    monkeypatch.setattr(tui_mod.TokenMeta, "fetch", lambda self, chain_id, addrs: {})
    monkeypatch.setattr(tui_mod.TokenMeta, "logo_path", lambda self, url: None)
    monkeypatch.setattr(tui_mod.FlowCache, "fetch", lambda self, chain_id, addrs: {})
    a = tui_mod.CuratorApp(chain_id=4663, refresh_seconds=0, image_mode="off")
    a.store = Store(tmp_path / "t.sqlite3")
    a.monitor.store = a.store
    a.meta._dir = tmp_path
    return a


def _plain(widget) -> str:
    """Text of a Static whose content is a rich renderable (Table / Text / Group)."""
    from rich.console import Console

    r = widget.render()
    r = getattr(r, "_renderable", r)  # Textual ≥ 8 wraps rich renderables in a RichVisual
    con = Console(width=200, record=True, file=io.StringIO())
    con.print(r)
    return con.export_text()


async def _loaded(app, pilot):
    for _ in range(40):
        await pilot.pause(0.1)
        if app.rows:
            return
    raise AssertionError("table never populated")


@pytest.mark.asyncio
async def test_screener_loads_and_filters(app):
    async with app.run_test(size=(220, 50)) as pilot:
        await _loaded(app, pilot)
        n_balanced = len(app.rows)
        assert n_balanced > 0
        assert all(r.pool.has_token("USDG") for r in app.rows)
        app.action_profile("degen")  # profiles moved off the digit keys (palette / settings)
        await pilot.pause(0.2)
        assert len(app.rows) >= n_balanced  # degen is the loosest profile
        await pilot.press("u")
        await pilot.pause(0.2)
        assert app.quote is None
        app.action_profile("conservative")
        await pilot.pause(0.2)
        assert app.profile.key == "conservative"
        assert "PROFILE:CONSERVATIVE" in str(app.main.query_one("#topbar").render())
        # the digits now navigate: 4 = track (no vaults → warning, stays), 1 = screener
        await pilot.press("4")
        await pilot.pause(0.2)
        assert type(app.screen).__name__ == "Screen"


@pytest.mark.asyncio
async def test_sorting_and_cursor_persistence(app):
    async with app.run_test(size=(220, 50)) as pilot:
        await _loaded(app, pilot)
        await pilot.press("down", "down")
        await pilot.pause(0.1)
        picked = app._selected().pool.address
        app._set_sort("TVL")
        await pilot.pause(0.2)
        tvls = [r.pool.tvl for r in app.rows]
        assert tvls == sorted(tvls, reverse=True)
        assert app._selected().pool.address == picked  # cursor followed the pool
        await pilot.press("S")
        await pilot.pause(0.2)
        assert [r.pool.tvl for r in app.rows] == sorted(tvls)


@pytest.mark.asyncio
async def test_find_size_and_links(app):
    async with app.run_test(size=(220, 50)) as pilot:
        await _loaded(app, pilot)
        first = app.rows[0].pool.pair.split("/")
        needle = next(s for s in first if s != "USDG")
        await pilot.press("slash")
        await pilot.press(*needle.lower())
        await pilot.pause(0.3)
        assert app.rows and all(needle in r.pool.pair for r in app.rows)
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert app.find_text == ""
        await pilot.press("dollar_sign")
        box = app.main.query_one("#size")
        box.value = "20000"
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert app.position_size == 20000
        assert all(r.sim and abs(r.sim.size - 20000) < 1e-9 for r in app.rows)
        await pilot.press("l")
        await pilot.pause(0.2)
        # no DexScreener in tests → status message, no modal
        assert type(app.screen).__name__ == "Screen"


@pytest.mark.asyncio
async def test_watchlist_and_csv(app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    async with app.run_test(size=(220, 50)) as pilot:
        await _loaded(app, pilot)
        await pilot.press("asterisk")
        await pilot.pause(0.2)
        assert app._selected().watched
        await pilot.press("W")
        await pilot.pause(0.2)
        assert len(app.rows) == 1
        await pilot.press("W", "e")
        await pilot.pause(0.3)
        files = list((tmp_path / "exports").glob("*.csv"))
        assert len(files) == 1 and files[0].read_text().count("\n") == len(app.rows) + 1


@pytest.mark.asyncio
async def test_positions_screen_without_wallet_warns(app):
    async with app.run_test(size=(220, 50)) as pilot:
        await _loaded(app, pilot)
        app.wallet = None
        await pilot.press("2")
        await pilot.pause(0.2)
        assert type(app.screen).__name__ == "Screen"
        assert "KRYSTAL_WALLET" in str(app.main.query_one("#status").render())


@pytest.mark.asyncio
async def test_header_click_sorts(app):
    async with app.run_test(size=(220, 50)) as pilot:
        await _loaded(app, pilot)
        table = app.main.query_one("#table", DataTable)
        idx, col = next(
            (i, c) for i, c in enumerate(table.ordered_columns) if c.key.value == "FEE24"
        )
        table.post_message(DataTable.HeaderSelected(table, col.key, idx, col.label))
        await pilot.pause(0.3)
        assert app.sort_col == "FEE24"
        fees = [r.pool.s24h.fee for r in app.rows]
        assert fees == sorted(fees, reverse=True)
        assert OptionList  # imported for completeness of the modal API


@pytest.mark.asyncio
async def test_positions_screen_renders_detail(app, monkeypatch):
    """Regression: the detail pane referenced self.config on the wrong object."""
    import time

    from krystal_curator.positions import Position
    from krystal_curator.vaults import Vault

    def fake_vaults(wallet, chain_id=None):
        v = Vault(
            chain_id=4663,
            address="0xv",
            name="V",
            vault_type="autofarm",
            owned=True,
            tvl=6000,
            pnl=0,
            apr=0,
            fee_generated=0,
            earning_24h=0,
            earning_30d=0,
            risk="",
            age_days=1,
            my_value=6000,
            my_deposit=6000,
            my_withdrawn=0,
        )
        pool = app.pools[0] if app.pools else None
        v.positions = [
            Position(
                id="v:1",
                chain_id=4663,
                pool_address=pool.address if pool else "0x",
                protocol="uniswapv4",
                token0="ETH",
                token1="USDG",
                status="IN_RANGE",
                value=4880,
                deposit=5000,
                withdrawn=0,
                pnl=-100,
                roi_pct=-2,
                il=0,
                fee_pending=8,
                fee_claimed=0,
                reward_pending=0,
                fee_apr=0.2,
                total_apr=0.2,
                min_price=2322,
                max_price=2870,
                current_price=2493,
                opened_ts=int(time.time() - 86400),
                vault="V",
            )
        ]
        return [v]

    monkeypatch.setattr(tui_mod, "fetch_vaults", fake_vaults)
    app.wallet = "0x000000000000000000000000000000000000dEaD"
    async with app.run_test(size=(230, 60)) as pilot:
        await _loaded(app, pilot)
        await pilot.press("2")
        for _ in range(30):
            await pilot.pause(0.1)
            if type(app.screen).__name__ == "PositionsScreen" and app.vaults:
                break
        await pilot.pause(0.3)
        assert app.screen.query_one("#pos_table").row_count == 1
        body = str(app.screen.query_one("#pos_detail").render())
        assert "ROTATE" in body or "KRYSTAL SETUP" in body or body  # rendered without raising
        await pilot.press("x")
        await pilot.pause(0.3)
        assert type(app.screen).__name__ in ("RotationModal", "PositionsScreen")


@pytest.mark.asyncio
async def test_reconcile_column_and_status(app, monkeypatch):
    from textual.widgets import DataTable

    from krystal_curator.models import Stat

    rows = json.loads(FIXTURE.read_text())["result"]
    pools = [Pool.from_public(x) for x in rows]
    other = []
    for p in pools[:10]:
        o = Pool.from_public({})
        o.address, o.protocol, o.source = p.address, p.protocol, "chain"
        o.tvl = p.tvl * 1.5  # 50 % apart on every matched pool
        o.s24h = Stat(volume=p.s24h.volume, fee=p.s24h.fee)
        other.append(o)
    monkeypatch.setattr(api, "fetch_reference_pools", lambda chain_id, **kw: list(other))
    app.config.reconcile = True
    async with app.run_test(size=(240, 50)) as pilot:
        await _loaded(app, pilot)
        assert app.recon is not None and app.recon.other == "chain"
        assert app.recon.flagged == len(app.recon.by_address) > 0
        table = app.main.query_one("#table", DataTable)
        matched = [r for r in app.rows if r.recon]
        assert matched
        cell = table.get_cell(matched[0].pool.address + matched[0].pool.protocol, "SRCΔ")
        assert str(cell) == "+50%"
        assert "vs chain:" in str(app.main.query_one("#status").render())
        app._set_sort("SRCΔ")
        await pilot.pause(0.2)
        assert app.rows[0].recon is not None  # worst disagreement sorts first


@pytest.mark.asyncio
async def test_leaderboard_screen_ranks_and_reviews(app, monkeypatch, tmp_path):
    """L opens the public-vault leaderboard; tab flips to owners; enter reviews the
    highlighted vault through vault_review + vault_eval and keeps the verdict."""
    from krystal_curator import vault_eval, vault_review
    from krystal_curator.vaults import _parse_vault

    pages = json.loads((Path(__file__).parent / "fixtures" / "vault_list.json").read_text())
    vaults = [_parse_vault(d, owned=False) for pg in pages for d in pg["data"]]
    monkeypatch.setattr(tui_mod, "fetch_public_vaults", lambda chain_id, **kw: list(vaults))
    reviewed: list[str] = []

    ev = vault_eval.Evaluation(
        verdict="avoid",
        reasons=["min_range_platform: minimumRange 10% (platform control)"],
        performance=vault_eval.Performance(),
        checks=[],
        evidence=vault_eval.Evidence(),
        limits=vault_eval.DEFAULT_LIMITS,
    )

    def fake_review(chain_id, address, **kw):
        reviewed.append(address)
        return vault_review.Review(fetched_at="", chain_id=chain_id, address=address, url="")

    monkeypatch.setattr(vault_review, "fetch_review", fake_review)
    monkeypatch.setattr(vault_eval, "evaluate", lambda rv: ev)
    monkeypatch.chdir(tmp_path)

    async with app.run_test(size=(240, 60)) as pilot:
        await _loaded(app, pilot)
        await pilot.press("3")
        for _ in range(30):
            await pilot.pause(0.1)
            if type(app.screen).__name__ == "LeaderboardScreen" and app.board:
                break
        await pilot.pause(0.3)
        table = app.screen.query_one("#lb_table", DataTable)
        assert table.row_count == 6 and app.board.total == 6
        first = str(table.get_row_at(0)[0])
        assert first in ("Naabu2", "Es RH bank", "Vault Es raptor")  # candidates first
        assert "candidate" in _plain(app.screen.query_one("#lb_detail"))

        await pilot.press("c")  # candidates only
        await pilot.pause(0.2)
        assert table.row_count == 3
        await pilot.press("tab")  # owners
        await pilot.pause(0.2)
        assert table.border_title.startswith("OWNERS")
        assert table.row_count == len(app.board.owners) >= 3
        await pilot.press("tab")
        await pilot.pause(0.2)

        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause(0.1)
            if app.reviews:
                break
        assert len(reviewed) == 1 and reviewed[0] in app.reviews
        body = _plain(app.screen.query_one("#lb_detail"))
        assert "avoid" in body and "minimumRange" in body
        await pilot.press("enter")  # cached: no second fetch
        await pilot.pause(0.2)
        assert len(reviewed) == 1

        await pilot.press("w")
        await pilot.pause(0.3)
        written = list((tmp_path / "reports").glob("vault_review_*.md"))
        assert len(written) == 1
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert type(app.screen).__name__ != "LeaderboardScreen"


@pytest.mark.asyncio
async def test_settings_screen_saves_and_applies(app, monkeypatch, tmp_path):
    """`,` opens the form; ctrl+s writes config.toml and takes the live fields over."""
    monkeypatch.chdir(tmp_path)
    async with app.run_test(size=(160, 50)) as pilot:
        await _loaded(app, pilot)
        await pilot.press("comma")
        await pilot.pause(0.3)
        assert type(app.screen).__name__ == "SettingsScreen"
        assert app.screen.query_one("#set_profile").value == "balanced"
        app.screen.query_one("#set_size").value = "12345"
        app.screen.query_one("#set_profile").value = "aggressive"
        app.screen.query_one("#set_agent_enabled").value = True
        app.screen.query_one("#set_agent_max_steps").value = "x"  # invalid: stays open
        await pilot.press("ctrl+s")
        await pilot.pause(0.3)
        assert type(app.screen).__name__ == "SettingsScreen"
        assert "agent.max_steps" in _plain(app.screen.query_one("#set_status"))
        app.screen.query_one("#set_agent_max_steps").value = "5"
        await pilot.press("ctrl+s")
        for _ in range(20):
            await pilot.pause(0.1)
            if type(app.screen).__name__ != "SettingsScreen":
                break
        assert app.position_size == 12345 and app.profile.key == "aggressive"
        assert app.config.agent.enabled and app.config.agent.max_steps == 5
        text = (tmp_path / "config.toml").read_text()
        assert 'profile = "aggressive"' in text and "max_steps = 5" in text
        assert app.config.source == tmp_path / "config.toml"
        await pilot.press("comma")
        await pilot.pause(0.3)
        await pilot.press("escape")  # cancel: nothing changes
        await pilot.pause(0.2)
        assert type(app.screen).__name__ != "SettingsScreen"


@pytest.mark.asyncio
async def test_nav_keys_help_and_palette(app):
    async with app.run_test(size=(200, 50)) as pilot:
        await _loaded(app, pilot)
        await pilot.press("3")
        await pilot.pause(0.3)
        assert type(app.screen).__name__ == "LeaderboardScreen"
        await pilot.press("3")  # already there: no second push
        await pilot.pause(0.2)
        assert len(app.screen_stack) == 2
        await pilot.press("comma")
        await pilot.pause(0.3)
        assert type(app.screen).__name__ == "SettingsScreen" and len(app.screen_stack) == 2
        await pilot.press("1")  # an Input has focus: the digit is typed, not navigation
        await pilot.pause(0.2)
        assert type(app.screen).__name__ == "SettingsScreen"
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert type(app.screen).__name__ == "Screen"
        await pilot.press("question_mark")
        await pilot.pause(0.3)
        assert type(app.screen).__name__ == "HelpModal"
        assert "command palette" in _plain(app.screen.query_one("#help_box"))
        await pilot.press("escape")
        await pilot.pause(0.2)
        await pilot.press("colon")
        await pilot.pause(0.4)
        assert type(app.screen).__name__ == "CommandPalette"
        await pilot.press(*"profile: degen")
        await pilot.pause(0.6)
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.1)
            if app.profile.key == "degen":
                break
        assert app.profile.key == "degen"


class _FakeSession:
    def __init__(self, final):
        self.final = final
        self.asked: list[str] = []
        self._client = None

    def ask(self, q):
        from krystal_curator.agent.llm import AgentRun, Step

        self.asked.append(q)
        run = AgentRun(task=q, model="fake.gguf", stopped="final", final=self.final)
        run.steps = [Step("t", "leaderboard", {"top": 3}, "{}", elapsed_s=0.5)]
        return run

    def review(self, rv, ev):
        from krystal_curator.agent.llm import AgentRun

        return AgentRun(
            task="r",
            model="fake.gguf",
            stopped="final",
            final={
                "reading": "farms USDG",
                "agrees_with_rule_verdict": False,
                "disagreement": "fees steady",
                "what_to_copy": ["harvest"],
                "what_to_change": ["range 10 -> 20"],
                "adapted_instructions": "x",
                "evidence": [],
                "confidence": "low",
            },
        )

    def close(self):
        pass


@pytest.mark.asyncio
async def test_agent_screen_asks_through_the_session(app, monkeypatch):
    app.config.agent.enabled = True
    fake = _FakeSession(
        {"answer": "28 candidates of 295", "evidence": ["leaderboard"], "confidence": "high"}
    )
    monkeypatch.setattr(app, "agent", lambda: fake)
    async with app.run_test(size=(200, 50)) as pilot:
        await _loaded(app, pilot)
        await pilot.press("5")
        await pilot.pause(0.3)
        assert type(app.screen).__name__ == "AgentScreen"
        box = app.screen.query_one("#agent_input")
        box.value = "how many candidates?"
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause(0.1)
            if not app.screen.busy:
                break
        assert fake.asked == ["how many candidates?"]
        entries = [_plain(w) for w in app.screen.query(".agent_entry")]
        assert any("28 candidates of 295" in e for e in entries)
        assert any("leaderboard(top=3)" in e for e in entries)
        assert "1 tool calls" in _plain(app.screen.query_one("#agent_status"))


@pytest.mark.asyncio
async def test_agent_screen_when_addon_is_off(app):
    async with app.run_test(size=(200, 50)) as pilot:
        await _loaded(app, pilot)
        await pilot.press("5")
        await pilot.pause(0.3)
        assert type(app.screen).__name__ == "AgentScreen"
        assert "addon is off" in _plain(app.screen.query(".agent_entry").first())


@pytest.mark.asyncio
async def test_leaderboard_agent_reading(app, monkeypatch, tmp_path):
    from krystal_curator import vault_eval, vault_review
    from krystal_curator.vaults import _parse_vault

    pages = json.loads((Path(__file__).parent / "fixtures" / "vault_list.json").read_text())
    vaults = [_parse_vault(d, owned=False) for pg in pages for d in pg["data"]]
    monkeypatch.setattr(tui_mod, "fetch_public_vaults", lambda chain_id, **kw: list(vaults))
    ev = vault_eval.Evaluation(
        verdict="watch",
        reasons=["x"],
        performance=vault_eval.Performance(),
        checks=[],
        evidence=vault_eval.Evidence(),
        limits=vault_eval.DEFAULT_LIMITS,
    )
    monkeypatch.setattr(
        vault_review,
        "fetch_review",
        lambda c, a, **k: vault_review.Review(fetched_at="", chain_id=c, address=a, url=""),
    )
    monkeypatch.setattr(vault_eval, "evaluate", lambda rv: ev)
    app.config.agent.enabled = True
    monkeypatch.setattr(app, "agent", lambda: _FakeSession({}))
    monkeypatch.chdir(tmp_path)
    async with app.run_test(size=(240, 60)) as pilot:
        await _loaded(app, pilot)
        await pilot.press("3")
        for _ in range(30):
            await pilot.pause(0.1)
            if app.board:
                break
        await pilot.pause(0.3)
        await pilot.press("a")  # rule review fetched first, then the agent reading
        for _ in range(30):
            await pilot.pause(0.1)
            if app.agent_runs:
                break
        assert len(app.agent_runs) == 1 and len(app.reviews) == 1
        body = _plain(app.screen.query_one("#lb_detail"))
        assert "disagrees" in body and "change: range 10 -> 20" in body
        await pilot.press("w")
        await pilot.pause(0.3)
        md = next((tmp_path / "reports").glob("*.md")).read_text()
        assert "## Agent reading" in md and "fees steady" in md
