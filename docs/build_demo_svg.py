#!/usr/bin/env python3
"""Render the --hallucinate demo output into a terminal-styled SVG.

Produces docs/demo.svg, embedded in the README. The text mirrors the real
output of `walegal-demo query "..." --hallucinate`.
"""

from __future__ import annotations

import html
from pathlib import Path

# ---- palette (GitHub-dark-ish) ----
BG = "#0d1117"
BAR = "#161b22"
DEFAULT = "#c9d1d9"
HEADER = "#58a6ff"
GREEN = "#3fb950"
RED = "#ff7b72"
FAIL = "#f85149"
WARN = "#f0883e"
DIM = "#6e7681"

FONT = ('font-family="ui-monospace,SFMono-Regular,Consolas,'
        '\'Liberation Mono\',Menlo,monospace"')
FS = 13.5          # font size
CW = FS * 0.602    # monospace advance width
LH = 21            # line height
PAD_X = 18
BAR_H = 34
PAD_TOP = BAR_H + 14
WRAP = 92          # wrap width in chars

RAW = ("Under RCW 70.400.010, the conduct described is governed by the Widget Safety Act. "
       "Courts have generally held that this framework applies as stated in RCW 70.400.020. "
       "The leading authority on this point is State v. Fabricated, 404 Wn.2d 1 (2099).")
FINAL = ("Under RCW 70.400.010, the conduct described is governed by the Widget Safety Act. "
         "Courts have generally held that this framework applies as stated in RCW 70.400.020.")
DISCLAIMER = ("This is automated legal information, not legal advice, and may be incomplete. "
              "Verify every citation against the official source. [build demo-2026.06]")

# Each entry: (kind, text). Highlights are applied per-kind below.
LINES = [
    ("prompt", '$ python -m walegal_demo query "What is unlawful widget operation?" --hallucinate'),
    ("blank", ""),
    ("header", "=== RAW ANSWER (pre-verification, straight from the model) ==="),
    ("body", RAW),
    ("blank", ""),
    ("header", "=== VERIFICATION (Stage 6) ==="),
    ("verif", "citations checked: 4 | passed: 2 | stripped: 2 (50%)  -> FAILED"),
    ("strip", "  - stripped hallucinated citation: 404 Wn.2d 1"),
    ("strip", "  - stripped hallucinated citation: State v. Fabricated"),
    ("blank", ""),
    ("header", "=== FINAL ANSWER (what the user sees) ==="),
    ("body2", FINAL),
    ("rule", "---"),
    ("dim", DISCLAIMER),
    ("blank", ""),
    ("comment", "# the fabricated 'State v. Fabricated' was stripped — it never reaches the user"),
]

# Substrings to paint red inside body text (the hallucinated citation).
RED_SPANS = ["State v. Fabricated, 404 Wn.2d 1 (2099)", "State v. Fabricated", "404 Wn.2d 1 (2099)"]


def wrap(text: str, width: int = WRAP) -> list[str]:
    if not text:
        return [""]
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        lines.append(cur)
    return lines


def colorize(text: str, base: str, spans: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Split `text` into (segment, color) parts, painting any matched spans."""
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(text):
        hit = None
        for sub, col in spans:
            if sub and text.startswith(sub, i):
                hit = (sub, col)
                break
        if hit:
            out.append((hit[0], hit[1]))
            i += len(hit[0])
        else:
            if out and out[-1][1] == base:
                out[-1] = (out[-1][0] + text[i], base)
            else:
                out.append((text[i], base))
            i += 1
    return out


def segments_for(kind: str, text: str) -> list[tuple[str, str]]:
    if kind == "prompt":
        return [("$ ", GREEN), (text[2:], DEFAULT)]
    if kind == "header":
        return [(text, HEADER)]
    if kind in ("body", "body2"):
        spans = [(s, RED) for s in RED_SPANS] if kind == "body" else []
        return colorize(text, DEFAULT, spans)
    if kind == "verif":
        return colorize(text, DEFAULT, [("FAILED", FAIL), ("stripped: 2 (50%)", WARN)])
    if kind == "strip":
        return [(text, WARN)]
    if kind == "comment":
        return [(text, GREEN)]
    if kind == "dim":
        return [(text, DIM)]
    if kind == "rule":
        return [(text, DIM)]
    return [(text, DEFAULT)]


def build() -> str:
    # Flatten to physical lines with their segments.
    phys: list[list[tuple[str, str]]] = []
    for kind, text in LINES:
        wrap_kinds = {"body", "body2", "dim", "comment", "verif"}
        chunks = wrap(text) if kind in wrap_kinds else [text]
        for chunk in chunks:
            phys.append(segments_for(kind, chunk))

    max_chars = max((sum(len(s) for s, _ in line) for line in phys), default=40)
    width = int(PAD_X * 2 + max_chars * CW) + 8
    height = int(PAD_TOP + len(phys) * LH + 14)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="walegal-demo --hallucinate terminal output">',
        f'<rect width="{width}" height="{height}" rx="9" fill="{BG}"/>',
        f'<rect width="{width}" height="{BAR_H}" rx="9" fill="{BAR}"/>',
        f'<rect y="{BAR_H-9}" width="{width}" height="9" fill="{BAR}"/>',
        f'<circle cx="19" cy="17" r="6" fill="#ff5f56"/>',
        f'<circle cx="39" cy="17" r="6" fill="#ffbd2e"/>',
        f'<circle cx="59" cy="17" r="6" fill="#27c93f"/>',
        f'<text x="{width/2}" y="22" text-anchor="middle" {FONT} font-size="12" '
        f'fill="{DIM}">walegal-demo — anti-hallucination gate</text>',
    ]

    y = PAD_TOP + FS
    for line in phys:
        if line == [("", DEFAULT)] or (len(line) == 1 and line[0][0] == ""):
            y += LH
            continue
        spans = "".join(
            f'<tspan fill="{col}">{html.escape(seg)}</tspan>' for seg, col in line if seg
        )
        parts.append(
            f'<text x="{PAD_X}" y="{y:.0f}" {FONT} font-size="{FS}" '
            f'xml:space="preserve">{spans}</text>'
        )
        y += LH
    parts.append("</svg>")
    return "\n".join(parts)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "demo.svg"
    out.write_text(build(), encoding="utf-8")
    print("wrote", out)
