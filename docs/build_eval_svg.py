#!/usr/bin/env python3
"""Render the `walegal-demo eval` metric table into a terminal-styled SVG.

Produces docs/eval.svg from the REAL output of the evaluation harness.
"""

from __future__ import annotations

import html
import io
from contextlib import redirect_stdout
from pathlib import Path

from walegal_demo.cli import main as cli_main

# palette (shared with build_demo_svg.py)
BG, BAR = "#0d1117", "#161b22"
DEFAULT, HEADER, GREEN, FAIL, DIM = "#c9d1d9", "#58a6ff", "#3fb950", "#f85149", "#6e7681"
FONT = ('font-family="ui-monospace,SFMono-Regular,Consolas,'
        '\'Liberation Mono\',Menlo,monospace"')
FS, CW, LH = 13.5, 13.5 * 0.602, 21
PAD_X, BAR_H, PAD_TOP = 18, 34, 48


def capture_eval() -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(["eval"])
    return buf.getvalue()


def segments(line: str) -> list[tuple[str, str, bool]]:
    """Return (text, color, bold) segments for one output line."""
    stripped = line.strip()
    if stripped and set(stripped) == {"-"}:
        return [(line, DIM, False)]
    if line.startswith("METRIC"):
        return [(line, HEADER, True)]
    if line.startswith("OVERALL"):
        col = GREEN if "ALL METRICS PASS" in line else FAIL
        return [(line, col, True)]
    if line.startswith("Ran "):
        return [(line, DIM, False)]
    # metric rows: paint PASS green / FAIL red, rest default
    out: list[tuple[str, str, bool]] = []
    i = 0
    while i < len(line):
        if line.startswith("PASS", i):
            out.append(("PASS", GREEN, True)); i += 4
        elif line.startswith("FAIL", i):
            out.append(("FAIL", FAIL, True)); i += 4
        else:
            if out and out[-1][1] == DEFAULT and not out[-1][2]:
                out[-1] = (out[-1][0] + line[i], DEFAULT, False)
            else:
                out.append((line[i], DEFAULT, False))
            i += 1
    return out


def build(text: str) -> str:
    lines = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip() != ""]
    max_chars = max(len(ln) for ln in lines)
    width = int(PAD_X * 2 + max_chars * CW) + 8
    height = int(PAD_TOP + (len(lines) + 1) * LH + 14)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="walegal-demo eval metric table">',
        f'<rect width="{width}" height="{height}" rx="9" fill="{BG}"/>',
        f'<rect width="{width}" height="{BAR_H}" rx="9" fill="{BAR}"/>',
        f'<rect y="{BAR_H-9}" width="{width}" height="9" fill="{BAR}"/>',
        '<circle cx="19" cy="17" r="6" fill="#ff5f56"/>',
        '<circle cx="39" cy="17" r="6" fill="#ffbd2e"/>',
        '<circle cx="59" cy="17" r="6" fill="#27c93f"/>',
        f'<text x="{width/2}" y="22" text-anchor="middle" {FONT} font-size="12" '
        f'fill="{DIM}">walegal-demo eval — gold-set metrics</text>',
    ]
    # prompt line first
    y = PAD_TOP + FS
    parts.append(
        f'<text x="{PAD_X}" y="{y:.0f}" {FONT} font-size="{FS}" xml:space="preserve">'
        f'<tspan fill="{GREEN}">$ </tspan>'
        f'<tspan fill="{DEFAULT}">python -m walegal_demo eval</tspan></text>'
    )
    y += LH
    for ln in lines:
        spans = "".join(
            f'<tspan fill="{c}"{" font-weight=\"bold\"" if b else ""}>{html.escape(t)}</tspan>'
            for t, c, b in segments(ln) if t
        )
        parts.append(
            f'<text x="{PAD_X}" y="{y:.0f}" {FONT} font-size="{FS}" '
            f'xml:space="preserve">{spans}</text>'
        )
        y += LH
    parts.append("</svg>")
    return "\n".join(parts)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "eval.svg"
    out.write_text(build(capture_eval()), encoding="utf-8")
    print("wrote", out)
