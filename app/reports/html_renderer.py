"""HTML rendering of the trade brief — minimal, server-rendered."""

from __future__ import annotations

import html

from app.reports.markdown_renderer import render_brief
from app.reports.trade_report import TradeBrief


def render_brief_html(brief: TradeBrief) -> str:
    md = render_brief(brief)
    body = html.escape(md)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Macro Options Scout</title>
<link rel="stylesheet" href="/static/style.css"></head>
<body><pre class="brief">{body}</pre></body></html>"""
