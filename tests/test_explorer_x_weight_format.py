"""The Explorer must not print small X weights as 0."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "sigma" / "web" / "static"


def _line(source: str, prefix: str) -> str:
    start = source.index(prefix)
    return source[start:source.index("\n", start)]


def test_x_weight_rows_use_the_x_weight_formatter():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "(X weight ${fmtNum(" not in js
    assert js.count("(X weight ${fmtXWeight(") == 3


def test_x_weight_formatter_keeps_small_values_visible():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    script = "\n".join(
        [
            _line(js, "const isNum = "),
            _line(js, "const fmtNum = "),
            _line(js, "const fmtXWeight = "),
            "const small = [4e-5, 0.2 / 2800, 0.0004].map(fmtXWeight);",
            "const large = [0.1875, 48, 0].map(v => [fmtXWeight(v), fmtNum(v)]);",
            "console.log(JSON.stringify({small, large, nan: fmtXWeight(NaN)}));",
        ]
    )
    result = json.loads(
        subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
    )
    assert result["small"] == ["4.00e-5", "7.14e-5", "4.00e-4"]
    # At or above 0.001 (and for 0) the display is unchanged from fmtNum.
    assert all(new == old for new, old in result["large"])
    assert result["nan"] == "—"
