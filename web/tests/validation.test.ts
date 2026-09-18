import { test } from "node:test";
import assert from "node:assert/strict";
import {
  feeLabel,
  protocolLabel,
  safeLogo,
  splitPair,
  tokenGlyph,
  tokenTone,
  uniquePairs,
} from "../lib/pair.ts";
import { validPoolId, validSettings } from "../lib/validation.ts";
test("reject invalid wallet, network/source combinations and nonfinite simulation sizes", () => {
  const good = {
    profile: "balanced",
    chain: 4663,
    source: "krystal",
    size: 10000,
    wallet: "",
  };
  assert.ok(validSettings(good));
  assert.equal(validSettings({ ...good, size: Infinity }), false);
  assert.equal(validSettings({ ...good, chain: 1, source: "chain" }), false);
  assert.equal(validSettings({ ...good, wallet: "not-an-address" }), false);
  assert.ok(validPoolId("4663:uniswapv4:0x" + "a".repeat(64)));
  assert.equal(validPoolId("4663:uniswapv4:0xabc"), false);
});
test("pair helpers split symbols, label protocols, and refuse non-https logos", () => {
  assert.deepEqual(
    splitPair({ pair: "WETH/USDG", token0: "WETH", token1: "USDG" }),
    ["WETH", "USDG"],
  );
  assert.deepEqual(splitPair({ pair: "A/B" }), ["A", "B"]);
  assert.deepEqual(splitPair({ pair: "solo" }), ["solo", "?"]);
  assert.equal(protocolLabel("uniswapv3"), "Uniswap v3");
  assert.equal(protocolLabel("ramsescl"), "Ramses CL");
  assert.equal(protocolLabel("ramsesv2"), "ramses v2");
  assert.equal(feeLabel(0.3), "0.3%");
  assert.equal(feeLabel(0.05), "0.05%");
  assert.equal(feeLabel(1), "1%");
  assert.equal(feeLabel(0), "");
  assert.equal(feeLabel(Number.NaN), "");
  assert.equal(tokenGlyph("USDG"), "US");
  assert.equal(tokenGlyph("ANTHROPICX1L"), "AN");
  assert.equal(tokenTone("USDG"), "tone-stable");
  assert.equal(tokenTone("WETH"), "tone-eth");
  assert.equal(
    safeLogo("https://cdn.example/logo.png"),
    "https://cdn.example/logo.png",
  );
  assert.equal(safeLogo("http://insecure.example/logo.png"), "");
  assert.equal(safeLogo("javascript:alert(1)"), "");
  const rows = uniquePairs(
    [
      { pair: "WETH/USDG", protocol: "uniswapv3", feeTier: 0.3 },
      { pair: "WETH/USDG", protocol: "uniswapv3", feeTier: 0.3 },
      { pair: "WETH/USDG", protocol: "uniswapv4", feeTier: 0.3 },
    ] as never,
    6,
  );
  assert.equal(rows.length, 2);
});
