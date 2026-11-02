# -*- coding: utf-8 -*-
"""
把 README 里 banner 的地址从 @main 换成固定的 commit SHA。

为什么要这么做：jsdelivr 对 `@main` 这种分支引用会缓存「分支 -> commit」的解析结果，
这个缓存不受 ?v= 影响，也不一定被 purge 清掉。于是内容明明更新了，
CDN 却一直吐旧图，GitHub 的 camo 又把旧图缓存到新 URL 下，问题就锁死了。
换成 commit SHA 之后引用不可变，缓存永远命中正确的那一份。

用法：
    python scripts/pin_banner_sha.py [sha]
不给 sha 时用 `git log -1 --format=%H -- assets/banner.svg` 自己算，
也就是「最后一次改动 banner.svg 的那个提交」——这样把 README 指向它，
后续再提交 README 不会改变它，不会自己触发自己。
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
BANNER = "assets/banner.svg"

URL_RE = re.compile(
    r"https://cdn\.jsdelivr\.net/gh/Charles766/Charles766@[^/\"]+/assets/banner\.svg(\?v=[\w.-]+)?"
)


def banner_sha():
    out = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", BANNER],
        cwd=ROOT, capture_output=True, text=True,
    )
    sha = out.stdout.strip()
    if not sha:
        raise SystemExit("拿不到 banner.svg 的提交号（是不是不在 git 仓库里？）")
    return sha


def main():
    sha = sys.argv[1] if len(sys.argv) > 1 else banner_sha()
    txt = README.read_text(encoding="utf-8")
    new_url = "https://cdn.jsdelivr.net/gh/Charles766/Charles766@" + sha + "/assets/banner.svg"
    new, n = URL_RE.subn(new_url, txt)
    print("banner sha -> %s  (%d 处)" % (sha, n))
    if n and new != txt:
        README.write_text(new, encoding="utf-8", newline="\n")
        print("README 已更新")
    else:
        print("README 无变化")


if __name__ == "__main__":
    main()
