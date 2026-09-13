from krystal_curator.vaults import _parse_vault, parse_strategy

STRATEGY = {
    "strategyId": 97503463,
    "chainId": 4663,
    "protocol": {"key": "uniswapv4", "name": "Uniswap V4"},
    "lpValue": 4877.0,
    "feeGenerated": 7.98,
    "feesPending": [{"quotes": {"usd": {"value": 5.48}}}, {"quotes": {"usd": {"value": 2.5}}}],
    "pnl": -121.17,
    "roi": -2.42,
    "apr": 0.23,
    "status": "IN_RANGE",
    "minPrice": 2321.6,
    "maxPrice": 2869.8,
    "currentPoolPrice": 2489.5,
    "ageInSecond": 172800,
    "initialDepositValue": 4998.0,
    "tokens": [{"symbol": "ETH"}, {"symbol": "USDG"}],
    "pool": {
        "id": "0xbac3aa3b91584a53a579b3c999a56756e954e59247e497bad1d25a4334bde551",
        "poolAddress": "0x8366A39cc670b4001a1121b8f6a443a643e40951",
    },
}


def test_parse_strategy():
    p = parse_strategy(STRATEGY, "Mr. Farmer")
    assert p.vault == "Mr. Farmer" and p.pair == "ETH/USDG" and p.protocol == "uniswapv4"
    assert p.pool_address.startswith("0xbac3aa3b") and p.pool_alt.startswith("0x8366a39c")
    assert p.in_range and abs(p.fee_pending - 7.98) < 1e-9
    assert abs(p.fee_claimed) < 1e-9 and abs(p.fees_total - 7.98) < 1e-9  # generated == pending
    assert 1.9 < p.age_days < 2.1
    rp = p.range_pos
    assert rp is not None and 0.29 < rp < 0.32


def test_parse_vault_and_track_record():
    v = _parse_vault(
        {
            "chainId": 4663,
            "vaultAddress": "0xAB",
            "name": "Mr. Farmer",
            "vaultType": "autofarm",
            "tvl": 6007.5,
            "pnl": 39.0,
            "apr": 3.54,
            "earning24h": 29.6,
            "earning30d": 887.0,
            "riskScore": "HIGH",
            "ageInSecond": 86400 * 9,
            "userPerformance": {
                "value": 6007.5,
                "totalDepositValue": 16566.0,
                "totalWithdrawValue": 11617.0,
            },
        },
        owned=True,
    )
    assert v.address == "0xab" and v.owned and abs(v.age_days - 9) < 1e-9
    assert v.url.endswith("/vaults/4663/0xab")
    assert v.win_rate is None
    win = parse_strategy({**STRATEGY, "status": "CLOSED", "pnl": 10}, v.name)
    loss = parse_strategy({**STRATEGY, "status": "CLOSED", "pnl": -4}, v.name)
    v.closed = [win, loss, win]
    assert abs(v.win_rate - 2 / 3) < 1e-9 and abs(v.closed_pnl - 16) < 1e-9
