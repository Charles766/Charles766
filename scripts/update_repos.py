#!/usr/bin/env python3
"""Sync the works table and the tech-stack SVG from live GitHub data.

Two outputs:
  1. README.md — the block between REPOS markers gets the top repos
  2. assets/stack-{light,dark}.svg — regenerated from real language bytes
"""

import json
import os
import re
import urllib.request
from datetime import datetime, timezone

USER = os.environ.get("GH_USER", "Charles766")
TOKEN = os.environ.get("GH_TOKEN", "")
TOP_N = int(os.environ.get("TOP_N", "4"))
LANG_N = int(os.environ.get("LANG_N", "8"))

# Repos never counted or shown.
EXCLUDE_NAMES = {
    USER.lower(),
    "github-slideshow",
}

README = "README.md"
START = "<!-- REPOS:START -->"
END = "<!-- REPOS:END -->"

FONT = "Georgia, 'Times New Roman', 'Songti SC', SimSun, serif"

PALETTE = {
    "light": {
        "card": "#FDF7FA",
        "stroke": "#F0E6EE",
        "hair": "#E8D9E4",
        "label": "#7A6E85",
        "label_en": "#A294AC",
        "pct": "#A294AC",
        "stamp": "#9C90A4",
        "colors": ["#C4567C", "#7B5FC4", "#3E8FB0"],
    },
    "dark": {
        "card": "#171226",
        "stroke": "#2A2140",
        "hair": "#32274A",
        "label": "#A69CB4",
        "label_en": "#8A7EA0",
        "pct": "#8A7EA0",
        "stamp": "#B4AAC4",
        "colors": ["#F2A0B5", "#B9A0F0", "#8FD3EC"],
    },
}


def api(url):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER,
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_repos():
    repos, page = [], 1
    while True:
        batch = api(
            f"https://api.github.com/users/{USER}/repos"
            f"?per_page=100&page={page}&sort=pushed"
        )
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def usable(repos):
    return [
        r
        for r in repos
        if not r["fork"]
        and not r["archived"]
        and r["name"].lower() not in EXCLUDE_NAMES
    ]


def esc(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_table(repos):
    picks = usable(repos)
    if not picks:
        return "<sub>还没有公开的原创仓库，这一栏会自动更新。</sub>"

    picks.sort(key=lambda r: r["pushed_at"], reverse=True)
    picks.sort(key=lambda r: -r["stargazers_count"])
    picks = picks[:TOP_N]

    lines = ["| 项目 | 一句话 | 技术 |", "| :-- | :-- | :-- |"]
    for r in picks:
        desc = esc(r["description"]).replace("|", r"\|") or "—"
        lang = esc(r.get("language")) or "—"
        lines.append(
            f'| **[{r["name"]}]({r["html_url"]})** | {desc} | <sub>{lang}</sub> |'
        )
    return "\n".join(lines)


def countable(repos):
    """Repos whose code counts toward language stats.

    Forks are included here on purpose: the works table shows only original
    work, but the stack section reflects whatever code lives in your repos.
    """
    return [
        r
        for r in repos
        if not r["archived"] and r["name"].lower() not in EXCLUDE_NAMES
    ]


def collect_languages(repos):
    """Sum bytes per language across countable repos, return [(name, pct)]."""
    totals = {}
    for r in countable(repos):
        try:
            data = api(f"https://api.github.com/repos/{USER}/{r['name']}/languages")
        except Exception:
            continue
        for lang, size in data.items():
            totals[lang] = totals.get(lang, 0) + size

    if not totals:
        return []

    ranked = sorted(totals.items(), key=lambda kv: -kv[1])[:LANG_N]
    total = sum(totals.values()) or 1
    return [(name, round(size * 100 / total)) for name, size in ranked]


def build_stack_svg(items, theme):
    p = PALETTE[theme]
    rows = max(1, (len(items) + 1) // 2)
    height = 184 + (rows - 1) * 48

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 780 {height}" '
        f'width="780" height="{height}" role="img">',
        "  <title>技术栈</title>",
        "  <desc>按各仓库代码量统计的语言占比，由 GitHub Actions 自动生成。</desc>",
        f'  <rect x="2" y="2" width="776" height="{height - 4}" rx="14" '
        f'fill="{p["card"]}" stroke="{p["stroke"]}" stroke-width="1"/>',
        f'  <text x="34" y="52" font-family="{FONT}" font-size="20" '
        f'fill="{p["label"]}">语言</text>',
        f'  <text x="34" y="72" font-family="{FONT}" font-size="9.5" '
        f'letter-spacing="2.2" fill="{p["label_en"]}">LANGUAGES</text>',
        f'  <line x1="34" y1="92" x2="746" y2="92" stroke="{p["hair"]}" '
        f'stroke-width="0.8"/>',
    ]

    if not items:
        out.append(
            f'  <text x="34" y="140" font-family="{FONT}" font-size="16" '
            f'fill="{p["label_en"]}">还没有可统计的代码</text>'
        )
    else:
        for i, (name, pct) in enumerate(items):
            col, row = i % 2, i // 2
            x = 34 + col * 370
            y = 140 + row * 48
            color = p["colors"][i % 3]
            if i % 2 == 0:
                out.append(f'  <circle cx="{x + 8}" cy="{y - 7}" r="2.9" fill="{color}"/>')
            else:
                out.append(
                    f'  <circle cx="{x + 8}" cy="{y - 7}" r="2.9" fill="none" '
                    f'stroke="{color}" stroke-width="1.2"/>'
                )
            out.append(
                f'  <text x="{x + 24}" y="{y}" font-family="{FONT}" font-size="22" '
                f'fill="{color}">{esc(name)}</text>'
            )
            out.append(
                f'  <text x="{x + 330}" y="{y}" text-anchor="end" '
                f'font-family="{FONT}" font-size="12" fill="{p["pct"]}">{pct}%</text>'
            )

    out.append(
        f'  <text x="746" y="{height - 14}" text-anchor="end" font-family="{FONT}" '
        f'font-size="9.5" letter-spacing="0.6" fill="{p["stamp"]}">'
        f'{datetime.now(timezone.utc).strftime("%Y-%m-%d")}</text>'
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def write_if_changed(path, content):
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == content:
                return False
    except FileNotFoundError:
        pass
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return True


def main():
    repos = fetch_repos()

    table = build_table(repos)
    with open(README, encoding="utf-8") as f:
        text = f.read()
    pattern = re.compile(re.escape(START) + r"(.*?)" + re.escape(END), re.S)
    if not pattern.search(text):
        raise SystemExit(f"markers not found in {README}")
    new_text = pattern.sub(lambda _m: f"{START}\n{table}\n{END}", text)
    readme_changed = new_text != text
    if readme_changed:
        with open(README, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_text)

    items = collect_languages(repos)
    svg_changed = False
    for theme in ("light", "dark"):
        path = f"assets/stack-{theme}.svg"
        if write_if_changed(path, build_stack_svg(items, theme)):
            svg_changed = True

    langs = ", ".join(f"{n} {p}%" for n, p in items) or "none"
    print(f"readme={'changed' if readme_changed else 'unchanged'} "
          f"svg={'changed' if svg_changed else 'unchanged'}")
    print(f"languages: {langs}")


if __name__ == "__main__":
    main()
