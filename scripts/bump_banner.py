# -*- coding: utf-8 -*-
"""
从 banner-dark.svg / banner-light.svg 重新合成 assets/banner.svg。

这里只负责「生成文件」，不碰 README 里的地址。
README 的地址由 scripts/pin_banner_sha.py 维护（固定 commit SHA），
因为 jsdelivr 对 @main 的分支解析缓存不可靠，详见那个脚本的说明。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_banner.py")], check=True)


if __name__ == "__main__":
    main()
