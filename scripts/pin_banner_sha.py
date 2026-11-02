# -*- coding: utf-8 -*-
"""
把 README 里引用的本地资源地址从 @main 换成固定的 commit SHA。

为什么要这么做：jsdelivr 对 `@main` 这种分支引用会缓存「分支 -> commit」的解析结果，
这个缓存不受 ?v= 影响，也不一定被 purge 清掉。于是内容明明更新了，
CDN 却一直吐旧图，GitHub 的 camo 又把旧图缓存到新 URL 下，问题就锁死了。
换成 commit SHA 之后引用不可变，缓存永远命中正确的那一份。

每个资源各自取「最后一次改动它的那个提交」——这样把 README 指向它，
后续再提交 README 不会改变它，不会自己触发自己。

用法：
    python scripts/pin_banner_sha.py
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

ASSETS = [
    "assets/banner.svg",
    "assets/name-dark.svg",
    "assets/name-light.svg",
]


def sha_for(path):
    out = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", path],
        cwd=ROOT, capture_output=True, text=True,
    )
    return out.stdout.strip()


def main():
    txt = README.read_text(encoding="utf-8")
    new = txt

    for path in ASSETS:
        sha = sha_for(path)
        name = Path(path).name
        if not sha:
            print("%-16s 还没有提交记录，跳过" % name)
            continue
        pattern = re.compile(
            r"https://cdn\.jsdelivr\.net/gh/Charles766/Charles766@[^/\"]+/assets/" + re.escape(name)
        )
        new, n = pattern.subn(
            "https://cdn.jsdelivr.net/gh/Charles766/Charles766@" + sha + "/assets/" + name, new
        )
        print("%-16s -> %s  (%d 处)" % (name, sha[:8], n))

    if new != txt:
        README.write_text(new, encoding="utf-8", newline="\n")
        print("README 已更新")
    else:
        print("README 无变化")


if __name__ == "__main__":
    main()
