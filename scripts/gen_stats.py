# -*- coding: utf-8 -*-
"""
生成 stats-dark.svg / stats-light.svg（刻度栏的活数据卡）。
由 GitHub Actions 每天/手动触发，或本地运行（需能访问 api.github.com）。
数据来自 GitHub API：public_repos / total commits / following / 入驻年份。
"""
import os, json, re, hashlib, subprocess, xml.etree.ElementTree as ET

USER = (os.environ.get("STATS_USER") or os.environ.get("GITHUB_ACTOR") or "Charles766").strip()
W, H = 495, 195

def api(path):
    # gh 优先（Actions 里有 GITHUB_TOKEN，限额高）；否则 curl（本地走代理 / 直连自适应）
    hdr = "Accept: application/vnd.github+json"
    try:
        p = subprocess.run(["gh", "api", "-H", hdr, path],
                           capture_output=True, text=True, timeout=45)
        if p.returncode == 0 and p.stdout.strip():
            return json.loads(p.stdout)
    except Exception:
        pass
    r = subprocess.run(["curl", "-sL", "-k", "-m", "30", "-H", hdr,
                        "https://api.github.com/" + path],
                       capture_output=True, text=True, timeout=45)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}

user = api("users/%s" % USER)
commits = api("search/commits?q=author:%s" % USER)

public_repos = user.get("public_repos", 0) or 0
following = user.get("following", 0) or 0
created = (user.get("created_at") or "2021-01-01")[:4]
tc = commits.get("total_count") if isinstance(commits, dict) else None
total_commits = tc if isinstance(tc, int) else "?"

metrics = [
    ("REPOS",     str(public_repos), "#B9A0F0", "#8B6FD6"),
    ("COMMITS",   str(total_commits), "#F2A0B5", "#D96C8E"),
    ("FOLLOWING", str(following), "#B9A0F0", "#8B6FD6"),
    ("SINCE",     created, "#F2A0B5", "#D96C8E"),
]

def card(bg, title_col, label_col, tick_col, num_cols):
    cx = [W * (i + 0.5) / 4 for i in range(4)]
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img">']
    s.append('  <title>still moving</title>')
    s.append(f'  <desc>GitHub stats for {USER}: {public_repos} repos, {total_commits} commits, {following} following, since {created}.</desc>')
    s.append(f'  <rect x="0" y="0" width="{W}" height="{H}" rx="14" fill="{bg}"/>')
    s.append(f'  <text x="24" y="42" font-family="Georgia, \'Playfair Display\', serif" font-size="22" font-weight="600" fill="{title_col}">still moving</text>')
    s.append(f'  <text x="24" y="60" font-family="Georgia, serif" font-size="11" letter-spacing="1.5" fill="{label_col}" opacity="0.8">还在动的，都算数</text>')
    for i, (lab, num, dcol, lcol) in enumerate(metrics):
        x = cx[i]; col = num_cols[i]
        for k in range(5):
            tx = x - 22 + k * 11; th = 6 + k * 2.2; op = 0.30 + k * 0.12
            s.append(f'  <rect x="{tx:.1f}" y="{74 - th:.1f}" width="2.4" height="{th:.1f}" rx="1.2" fill="{tick_col}" opacity="{op:.2f}"/>')
        s.append(f'  <text x="{x:.1f}" y="122" text-anchor="middle" font-family="Georgia, \'Playfair Display\', serif" font-size="34" font-weight="600" fill="{col}">{num}</text>')
        s.append(f'  <text x="{x:.1f}" y="148" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="11.5" letter-spacing="1.2" fill="{label_col}">{lab}</text>')
    s.append('</svg>')
    return "\n".join(s) + "\n"

dark = card("#171226", "#F2A0B5", "#A8A2B8", "#B9A0F0", [m[2] for m in metrics])
light = card("#FDF7FA", "#D96C8E", "#5B5568", "#8B6FD6", [m[3] for m in metrics])

for fn, content in [("assets/stats-dark.svg", dark), ("assets/stats-light.svg", light)]:
    open(fn, "w", encoding="utf-8", newline="\n").write(content)
    ET.fromstring(content)
    print(fn, "ok", len(content), "bytes |", public_repos, total_commits, following, created)

# 用内容 hash 更新 README 里 stats 图的版本号（内容不变则 URL 不变，CDN 命中）
ver = hashlib.md5((dark + light).encode("utf-8")).hexdigest()[:8]
try:
    with open("README.md", encoding="utf-8") as f:
        txt = f.read()
    new = re.sub(r"(assets/stats-dark\.svg\?v=)[\w.-]+", lambda m: m.group(1) + ver, txt)
    new = re.sub(r"(assets/stats-light\.svg\?v=)[\w.-]+", lambda m: m.group(1) + ver, new)
    if new != txt:
        with open("README.md", "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
        print("README stats 版本号 ->", ver)
except FileNotFoundError:
    pass
