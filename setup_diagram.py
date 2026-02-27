#!/usr/bin/env python3
"""
Setup script — Extracts the SVG from the block diagram HTML
and places it in the static/ folder for the dashboard.

Usage: python setup_diagram.py [path_to_smartpi_block_diagram.html]
"""

import re
import sys
import os

def extract_svg(html_path: str, output_path: str):
    """Extract the SVG element from the block diagram HTML."""
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract the SVG tag
    match = re.search(r'(<svg\b.*?</svg>)', content, re.DOTALL)
    if not match:
        print("ERROR: No <svg> element found in the HTML file.")
        sys.exit(1)

    svg = match.group(1)

    # We need to inline the CSS variables since the SVG will be standalone
    # Replace var(--xxx) with actual values from the CSS
    css_vars = {
        'var(--bg)': '#0a0e17',
        'var(--bg-block)': '#141b2d',
        'var(--bg-block-hover)': '#1a2340',
        'var(--border)': '#2a3654',
        'var(--border-highlight)': '#4a6fa5',
        'var(--text)': '#c8d6e5',
        'var(--text-dim)': '#6b7d99',
        'var(--text-bright)': '#e8f0fe',
        'var(--accent-blue)': '#4a9eff',
        'var(--accent-cyan)': '#00d4aa',
        'var(--accent-orange)': '#ff8c42',
        'var(--accent-red)': '#ff4757',
        'var(--accent-purple)': '#a55eea',
        'var(--accent-yellow)': '#ffd32a',
        'var(--accent-green)': '#26de81',
        'var(--signal-main)': '#4a9eff',
        'var(--signal-feedback)': '#ff8c42',
        'var(--signal-ff)': '#00d4aa',
        'var(--signal-learn)': '#a55eea',
        'var(--signal-diag)': '#6b7d99',
        'var(--grid)': '#0f1525',
    }

    for var, val in css_vars.items():
        svg = svg.replace(var, val)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(svg)

    print(f"✓ SVG extracted: {output_path}")
    print(f"  Size: {len(svg):,} bytes")


if __name__ == '__main__':
    html_path = sys.argv[1] if len(sys.argv) > 1 else 'smartpi_block_diagram.html'
    output_path = os.path.join('static', 'block_diagram.svg')

    if not os.path.exists(html_path):
        print(f"File not found: {html_path}")
        print("Usage: python setup_diagram.py path/to/smartpi_block_diagram.html")
        sys.exit(1)

    extract_svg(html_path, output_path)
