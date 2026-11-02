# -*- coding: utf-8 -*-
"""
先跑 build_banner.py 合成 banner.svg，再用它的内容哈希更新 README 里的 ?v= 版本号。

内容不变则 URL 不变（CDN / camo 缓存命中），内容变才换钥匙，强制拉新图。
由 .github/workflows/bump-banner.yml 在源 SVG 或构建脚本 push 时自动触发。
"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_banner.py")], check=True)

    banner = ROOT / "assets" / "banner.svg"
    ver = hashlib.md5(banner.read_bytes()).hexdigest()[:8]

    readme = ROOT / "README.md"
    txt = readme.read_text(encoding="utf-8")
    new = re.sub(r"(assets/banner\.svg\?v=)[\w.-]+", lambda m: m.group(1) + ver, txt)
    print("%-14s -> %s" % ("banner", ver))

    if new != txt:
        readme.write_text(new, encoding="utf-8", newline="\n")
        print("README 已更新")
    else:
        print("README 无变化")


if __name__ == "__main__":
    main()
