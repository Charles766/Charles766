#!/usr/bin/env python3
"""Fetch public repos and rewrite the block between REPOS markers in README.md."""

import json
import os
import re
import urllib.request

USER = os.environ.get("GH_USER", "Charles766")
TOKEN = os.environ.get("GH_TOKEN", "")
TOP_N = int(os.environ.get("TOP_N", "4"))

# Repos never shown in the works table.
EXCLUDE_NAMES = {
    USER.lower(),
    "github-slideshow",
}

README = "README.md"
START = "<!-- REPOS:START -->"
END = "<!-- REPOS:END -->"


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


def esc(text):
    return (text or "").replace("|", r"\|").replace("\n", " ").strip()


def build_table(repos):
    picks = [
        r
        for r in repos
        if not r["fork"]
        and not r["archived"]
        and r["name"].lower() not in EXCLUDE_NAMES
    ]

    if not picks:
        return "<sub>还没有公开的原创仓库，这一栏会自动更新。</sub>"

    picks.sort(key=lambda r: r["pushed_at"], reverse=True)
    picks.sort(key=lambda r: -r["stargazers_count"])
    picks = picks[:TOP_N]

    lines = ["| 项目 | 一句话 | 技术 |", "| :-- | :-- | :-- |"]
    for r in picks:
        desc = esc(r["description"]) or "—"
        lang = esc(r.get("language")) or "—"
        lines.append(
            f'| **[{r["name"]}]({r["html_url"]})** | {desc} | <sub>{lang}</sub> |'
        )
    return "\n".join(lines)


def main():
    table = build_table(fetch_repos())

    with open(README, encoding="utf-8") as f:
        text = f.read()

    pattern = re.compile(re.escape(START) + r"(.*?)" + re.escape(END), re.S)
    if not pattern.search(text):
        raise SystemExit(f"markers not found in {README}")

    new_text = pattern.sub(lambda _m: f"{START}\n{table}\n{END}", text)
    if new_text == text:
        print("no changes")
        return

    with open(README, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_text)
    print("works section updated")


if __name__ == "__main__":
    main()
