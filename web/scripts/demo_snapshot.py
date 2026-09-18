"""Regenerate the explicitly-labelled public demo from the repository's test fixture.
Run from the repository root: uv run --extra web web/scripts/demo_snapshot.py
"""

import json
from pathlib import Path

from krystal_curator.models import Pool
from krystal_curator.profiles import PROFILES
from krystal_curator.web_api import pool_rows

root = Path(__file__).resolve().parents[2]
data = json.loads((root / "tests/fixtures/top_pools_robinhood.json").read_text())
rows = data.get("result", data) if isinstance(data, dict) else data
pools = [Pool.from_public(row) for row in rows]
snapshot = {key: pool_rows(pools, key, "USDG", 10000) for key in PROFILES}
(root / "web/lib/demo.json").write_text(json.dumps(snapshot, indent=2) + "\n")
