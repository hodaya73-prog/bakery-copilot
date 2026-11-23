"""Runs the Node checks for static/render.js. Skipped when Node is not installed (CI's runners have it)."""
import shutil
import subprocess

import pytest

from app.config import ROOT

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_the_reply_renderer_passes_its_checks():
    result = subprocess.run([NODE, str(ROOT / "tests" / "js" / "render_check.js")], capture_output=True, text=True,
                            encoding="utf-8", timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
