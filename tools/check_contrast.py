#!/usr/bin/env python3
"""Check that the text/background colour pairs of core/static/core/base.css meet WCAG AA (4.5:1 for text, 3:1 for
form-control borders). Reads the --color-* tokens from the stylesheet. Exit status 1 when a pair fails.

    python tools/check_contrast.py
"""
import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / 'core' / 'static' / 'core' / 'base.css'

# (foreground token, background token, minimum ratio). Keep in step with the way base.css uses the tokens.
PAIRS = [
    ('text', 'bg', 4.5), ('text', 'surface', 4.5), ('text-muted', 'bg', 4.5), ('text-muted', 'surface', 4.5),
    ('heading', 'bg', 4.5), ('heading', 'surface', 4.5), ('link', 'bg', 4.5), ('link', 'surface', 4.5),
    ('on-primary', 'primary', 4.5), ('on-primary', 'primary-hover', 4.5), ('primary', 'bg', 4.5),
    ('secondary-text', 'secondary-bg', 4.5), ('text', 'border', 4.5),
    ('on-danger', 'danger', 4.5), ('on-danger', 'danger-hover', 4.5),
    ('danger-text', 'danger-bg', 4.5), ('success-text', 'success-bg', 4.5), ('warning-text', 'warning-bg', 4.5),
    ('border-strong', 'bg', 3.0), ('secondary-text', 'border', 4.5), ('success-border', 'bg', 3.0),
    ('warning-border', 'bg', 3.0), ('danger', 'bg', 3.0),
]


def tokens(css_text):
    return {name: value.lower() for name, value in re.findall(r'--color-([a-z-]+):\s*(#[0-9a-fA-F]{6})', css_text)}


def luminance(hex_colour):
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def check(css_text=None):
    """Return a list of (fg, bg, ratio, minimum, ok) and the tokens used by no pair."""
    toks = tokens(css_text if css_text is not None else CSS.read_text())
    results = []
    for fg, bg, minimum in PAIRS:
        r = ratio(toks[fg], toks[bg])
        results.append((fg, bg, round(r, 2), minimum, r >= minimum))
    used = {t for fg, bg, _ in PAIRS for t in (fg, bg)}
    return results, sorted(set(toks) - used)


def main():
    results, unused = check()
    failed = [r for r in results if not r[4]]
    for fg, bg, r, minimum, ok in results:
        print(f'{"ok  " if ok else "FAIL"} {fg:15} on {bg:15} {r:6.2f}:1 (needs {minimum}:1)')
    if unused:
        print('tokens not covered by a pair (decorative only):', ', '.join(unused))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
