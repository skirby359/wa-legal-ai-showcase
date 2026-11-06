#!/usr/bin/env python3
"""Render the README's terminal images from the REAL output of the CLI.

    PYTHONPATH=src python docs/build_svgs.py

Each image runs one `walegal-demo` command in-process, captures what it prints,
and draws it as a terminal window, so the pictures cannot drift from the code.
"""

from __future__ import annotations

import html
import io
import re
from contextlib import redirect_stdout
from pathlib import Path

from walegal_demo.cli import main as cli_main

# ---- palette (GitHub-dark-ish) ----
BG, BAR = "#0d1117", "#161b22"
DEFAULT, HEADER, GREEN, RED, FAIL = "#c9d1d9", "#58a6ff", "#3fb950", "#ff7b72", "#f85149"
WARN, NOTE, DIM = "#f0883e", "#e3b341", "#6e7681"

FONT = ('font-family="ui-monospace,SFMono-Regular,Consolas,'
        '\'Liberation Mono\',Menlo,monospace"')
FS = 13.5          # font size
CW = FS * 0.602    # monospace advance width
LH = 21            # line height
PAD_X, BAR_H = 18, 34
PAD_TOP = BAR_H + 14
WRAP = 96          # wrap width in characters (None = no wrapping)

BOLD = ' font-weight="bold"'
Segment = tuple[str, str, bool]  # text, colour, bold

SCENES = [
    {
        "file": "demo.svg",
        "title": "walegal-demo — anti-hallucination gate",
        "argv": ["query", "What is unlawful widget operation?", "--hallucinate"],
        "comment": "# the fabricated 'State v. Fabricated' was stripped — it never reaches the user",
    },
    {
        "file": "negative-history.svg",
        "title": "walegal-demo — negative-history note",
        "argv": ["query", "Is network-based control of a widget operation?", "--cite-overruled"],
        "comment": "# the overruled case is kept, with a warning the reader cannot miss",
    },
    {
        "file": "agent.svg",
        "title": "walegal-demo — agent mode",
        "argv": ["query", "What is unlawful widget operation?", "--agent", "--trace",
                 "--hallucinate"],
        "comment": "# the audit sent the invented citation back; the revision dropped it",
    },
    {
        "file": "eval.svg",
        "title": "walegal-demo eval — gold-set metrics",
        "argv": ["eval"],
        "wrap": None,
    },
]

RED_SPANS = ["State v. Fabricated, 404 Wn.2d 1 (2099)", "State v. Fabricated",
             "404 Wn.2d 1 (2099)", "404 Wn.2d 1"]
NOTE_PATTERN = re.compile(r"\[negative history: [^\]]+\]")


def capture(argv: list[str]) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli_main(argv)
    return buf.getvalue()


def paint(text: str, base: str) -> list[Segment]:
    """Colour the hallucinated citation red and the negative-history note amber."""
    spans = [(m.start(), m.end(), NOTE) for m in NOTE_PATTERN.finditer(text)]
    i = 0
    while i < len(text):
        hit = next((s for s in RED_SPANS if text.startswith(s, i)), None)
        if hit:
            spans.append((i, i + len(hit), RED))
            i += len(hit)
        else:
            i += 1
    spans.sort()
    out: list[Segment] = []
    pos = 0
    for start, end, colour in spans:
        if start < pos:
            continue
        if start > pos:
            out.append((text[pos:start], base, False))
        out.append((text[start:end], colour, False))
        pos = end
    if pos < len(text):
        out.append((text[pos:], base, False))
    return out


def style(line: str, state: dict) -> list[Segment]:
    """Segments for one line of CLI output."""
    s = line.strip()
    if line.startswith("==="):
        state["after_rule"] = False
        return [(line, HEADER, True)]
    if s == "---":
        state["after_rule"] = True
        return [(line, DIM, False)]
    if state.get("after_rule"):
        return [(line, DIM, False)]
    if line.startswith("METRIC") or line.startswith("Ran "):
        return [(line, HEADER if line.startswith("METRIC") else DIM, line.startswith("METRIC"))]
    if line.startswith("OVERALL"):
        return [(line, GREEN if "ALL METRICS PASS" in line else FAIL, True)]
    if s and set(s) == {"-"}:
        return [(line, DIM, False)]
    if line.startswith("  - "):
        return [(line, WARN, False)]
    if re.match(r"\s+\d+\. ", line):  # agent trace step
        m = re.match(r"(\s+\d+\. )(\w+\s+)(.*)", line)
        return [(m.group(1), DIM, False), (m.group(2), DIM, False), (m.group(3), DEFAULT, False)]
    if s.startswith("-> "):
        return [(line, DIM, False)]
    if line.startswith("citations checked"):
        out: list[Segment] = []
        for part in re.split(r"(FAILED|PASSED)", line):
            colour = FAIL if part == "FAILED" else GREEN if part == "PASSED" else DEFAULT
            out.append((part, colour, part in ("FAILED", "PASSED")))
        return out
    if re.search(r"\b(PASS|FAIL)\b", line):  # metric row
        out = []
        for part in re.split(r"\b(PASS|FAIL)\b", line):
            colour = GREEN if part == "PASS" else FAIL if part == "FAIL" else DEFAULT
            out.append((part, colour, part in ("PASS", "FAIL")))
        return out
    return paint(line, DEFAULT)


def wrap(segments: list[Segment], width: int | None) -> list[list[Segment]]:
    """Greedy word wrap that keeps each word's colour and the line's indent."""
    if width is None or sum(len(t) for t, _, _ in segments) <= width:
        return [segments]
    first = segments[0][0]
    lead = len(first) - len(first.lstrip(" "))
    segments = [(first[lead:], *segments[0][1:]), *segments[1:]]
    words: list[Segment] = []
    for text, colour, bold in segments:
        for piece in re.split(r"( )", text):
            if piece:
                words.append((piece, colour, bold))
    lines: list[list[Segment]] = [[(" " * lead, DEFAULT, False)]]
    used = lead
    for word in words:
        if used + len(word[0]) > width and used > lead + 2 and word[0] != " ":
            while lines[-1] and lines[-1][-1][0] == " ":
                lines[-1].pop()
            lines.append([(" " * (lead + 2), DEFAULT, False)])
            used = lead + 2
        if word[0] == " " and used == lead + 2 and len(lines) > 1 and len(lines[-1]) == 1:
            continue  # no space at the start of a continuation line
        lines[-1].append(word)
        used += len(word[0])
    return lines


def build(scene: dict) -> str:
    width_chars = scene.get("wrap", WRAP)
    args = [f'"{a}"' if " " in a else a for a in scene["argv"]]
    prompt = "python -m walegal_demo " + " ".join(args)
    logical: list[list[Segment]] = [[("$ ", GREEN, False), (prompt, DEFAULT, False)]]
    state: dict = {}
    for line in capture(scene["argv"]).splitlines():
        logical.append(style(line, state) if line.strip() else [])
    if scene.get("comment"):
        logical += [[], [(scene["comment"], GREEN, False)]]

    phys: list[list[Segment]] = []
    for segs in logical:
        phys.extend(wrap(segs, width_chars) if segs else [[]])

    max_chars = max((sum(len(t) for t, _, _ in ln) for ln in phys), default=40)
    width = int(PAD_X * 2 + max_chars * CW) + 8
    height = int(PAD_TOP + len(phys) * LH + 14)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(scene["title"])}">',
        f'<rect width="{width}" height="{height}" rx="9" fill="{BG}"/>',
        f'<rect width="{width}" height="{BAR_H}" rx="9" fill="{BAR}"/>',
        f'<rect y="{BAR_H - 9}" width="{width}" height="9" fill="{BAR}"/>',
        '<circle cx="19" cy="17" r="6" fill="#ff5f56"/>',
        '<circle cx="39" cy="17" r="6" fill="#ffbd2e"/>',
        '<circle cx="59" cy="17" r="6" fill="#27c93f"/>',
        f'<text x="{width / 2}" y="22" text-anchor="middle" {FONT} font-size="12" '
        f'fill="{DIM}">{html.escape(scene["title"])}</text>',
    ]
    y = PAD_TOP + FS
    for line in phys:
        if line:
            spans = "".join(
                f'<tspan fill="{c}"{BOLD if b else ""}>{html.escape(t)}</tspan>'
                for t, c, b in line if t
            )
            parts.append(f'<text x="{PAD_X}" y="{y:.0f}" {FONT} font-size="{FS}" '
                         f'xml:space="preserve">{spans}</text>')
        y += LH
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    for scene in SCENES:
        out = here / scene["file"]
        out.write_text(build(scene), encoding="utf-8")
        print("wrote", out.name)
