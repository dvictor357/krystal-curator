"""End-to-end TUI tests on a recorded top_pools payload (no network)."""

from __future__ import annotations

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
        await pilot.press("4")
        await pilot.pause(0.2)
        assert len(app.rows) >= n_balanced  # degen is the loosest profile
        await pilot.press("u")
        await pilot.pause(0.2)
        assert app.quote is None
        await pilot.press("1")
        await pilot.pause(0.2)
        assert app.profile.key == "conservative"
        assert "PROFILE:CONSERVATIVE" in str(app.main.query_one("#topbar").render())


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
        await pilot.press("P")
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
        await pilot.press("P")
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
