"""Run the browser-side tests as part of the one test command.

app.js holds the half of this tool where meeting work is actually typed, so it
needs tests as much as the store does. They run under node against a DOM small
enough to keep in one file (tests/js/harness.mjs) — no npm, nothing installed,
in keeping with the stdlib-only rule. Skipped, not failed, where node is absent:
the Python side must stay runnable on a bare cluster account.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

JS_DIR = Path(__file__).resolve().parent / "js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


@pytest.mark.parametrize("suite", sorted(p.name for p in JS_DIR.glob("*.test.mjs")))
def test_js_suite(suite):
    proc = subprocess.run([NODE, "--test", str(JS_DIR / suite)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
