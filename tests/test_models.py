def test_krystal_links_carry_the_referral_code():
    from krystal_curator.models import KRYSTAL_REF, krystal_url

    url = krystal_url("/pools/detail", chainId=4663, poolAddress="0xabc", protocol="uniswapv3")
    assert url.startswith("https://defi.krystal.app/pools/detail?")
    assert f"r={KRYSTAL_REF}" in url and "chainId=4663" in url
    assert krystal_url("/account") == f"https://defi.krystal.app/account?r={KRYSTAL_REF}"
