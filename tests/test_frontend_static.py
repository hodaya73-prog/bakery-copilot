"""The UI loads nothing from other sites and has no inline script (SecurityProblems.md SP-11, SP-01)."""
import re

from app.config import ROOT

HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")


def test_the_page_loads_no_script_style_or_image_from_another_site():
    remote = re.findall(r"""(?:src|href)\s*=\s*["']\s*(?:https?:)?//[^"']+""", HTML, re.I)

    assert remote == []


def test_the_page_has_no_inline_script_or_inline_handlers():
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", HTML, re.I)  # every script tag has a src
    assert not re.search(r"\son[a-z]+\s*=", HTML, re.I)  # no onclick=, onerror=, ...
    assert " style=" not in HTML  # the policy forbids inline style attributes


def test_the_safe_renderer_loads_before_the_app():
    assert HTML.index("/static/render.js") < HTML.index("/static/app.js")


def test_the_app_no_longer_uses_the_third_party_markdown_library():
    assert "marked" not in HTML and "marked" not in APP_JS


def test_replies_go_through_the_safe_renderer_and_invoice_fields_are_escaped():
    assert "SafeMarkdown.render" in APP_JS
    row = [line for line in APP_JS.splitlines() if "invoice-rows" in line and "innerHTML" in line][0]
    for field in ("r.invoice_date", "r.currency", "r.status"):
        assert f"escapeHtml({field}" in row or f"escapeHtml(String({field}" in row, field
