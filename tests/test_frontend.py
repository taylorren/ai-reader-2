"""The front end's pure logic, run by Node's built-in test runner.

The app has no JS build step and no npm dependency — the browser loads these
files as plain scripts — so this needs nothing but `node`, and skips cleanly
without it, the same contract test_corpus.py has with EPUBX_CORPUS.

The unit tests live in tests/js/*.test.js and cover static/js/reader-core.js,
the module reader.js and panel.js share (REVIEW T1).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_TESTS = REPO_ROOT / "tests" / "js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def test_the_front_end_units_pass():
    """`node --test` over tests/js — no browser, no stubs beyond a stub document.

    The files are collected here rather than by a glob argument so that adding a
    test file needs no configuration, and so that an empty directory fails
    loudly instead of reporting success.
    """
    files = sorted(str(path) for path in JS_TESTS.glob("*.test.js"))
    assert files, f"no JS test files found in {JS_TESTS}"

    result = subprocess.run(
        [NODE, "--test", *files],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"node --test failed:\n{result.stdout}\n{result.stderr}")
