#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_banner.py — 把 banner-dark.svg / banner-light.svg 合成一张自带日月循环的 banner.svg

设计要点
--------
* 一个 240s 主时钟：太阳 2s 升、50s 天顶、98s 落；月亮 122s 升、170s 天顶、218s 落。
* 昼夜不是两张图，是同一张图里两个图层互相淡入淡出（98s-122s 入夜，220s-240s 出夜）。
* 日月走同一条正弦弧，用积分速度曲线实现"匀速 + 过天顶柔和停留"，
  不再用 ease-in-out（那是每段关键帧各自缓动，一圈里抖六次）。
* 月相 480s 一轮，满月/新月都落在天顶；月全食隔一个满月一次（960s），铜红缓慢浸入再退去。
"""

import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

T = 240.0            # 主时钟
A, B = 2.0, 98.0     # 太阳过境区间
APEX = (A + B) / 2.0
MOON_A, MOON_B = 104.0, 236.0   # 月亮过境：日落即全黑，隔 6 秒月亮就起；落得晚些，月落离日出更近
MOON_X1 = 908.0                 # 月亮落点收在城堡左侧，否则会被城堡挡住十几秒
MOON_YBASE, MOON_H = 290.0, 216.0   # 月亮弧线两端抬高，少走一段山后的路
MOON_APEX = (MOON_A + MOON_B) / 2.0
X0, X1 = 60.0, 1140.0
YBASE, HEIGHT = 318.0, 244.0

SUN_BASE = (882.0, 150.0)
MOON_BASE = (878.0, 120.0)

LUNATION = 480.0     # 月相周期
FULL_AT = MOON_APEX  # 满月 = 天顶
NEW_AT = FULL_AT + LUNATION / 2.0   # 下一轮天顶，正好新月


# ---------------------------------------------------------------- 工具

def fmt(v, nd=2):
    s = ("%." + str(nd) + "f") % v
    s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def pct(t, period=None):
    return fmt(t / (period or T) * 100.0, 3)


def split_svg(svg):
    m = re.search(r"<defs>(.*?)</defs>", svg, re.S)
    defs = m.group(1)
    rest = svg[m.end():]
    m2 = re.search(r"<style>(.*?)</style>", rest, re.S)
    style = m2.group(1)
    body = rest[m2.end():]
    body = body[: body.rfind("</svg>")]
    return defs, style, body


def kf_block(css, name):
    """返回 (start_index, end_index_of_closing_brace, block_text)"""
    i = css.find("@keyframes " + name + " {")
    if i < 0:
        return None
    j = css.index("{", i)
    depth, k = 0, j
    while True:
        if css[k] == "{":
            depth += 1
        elif css[k] == "}":
            depth -= 1
            if depth == 0:
                break
        k += 1
    return i, k, css[j + 1: k]


def drop_kf(css, name):
    r = kf_block(css, name)
    if r is None:
        return css
    i, k, _ = r
    return css[:i] + css[k + 1:]


def replace_kf(css, name, new_block):
    r = kf_block(css, name)
    if r is None:
        return css
    i, k, _ = r
    head = css[: i]
    tail = css[k + 1:]
    return head + "@keyframes " + name + " {" + new_block + "}" + tail


# ---------------------------------------------------------------- 弧线

def build_arc(a=None, b=None, x1=None, ybase=None, height=None, k=None):
    """按速度曲线积分，得到 u(t)，再映射到正弦弧上。a/b/x1/ybase/height 可覆盖默认值。"""
    a = A if a is None else a
    b = B if b is None else b
    xr = X1 if x1 is None else x1
    yb = YBASE if ybase is None else ybase
    hh = HEIGHT if height is None else height
    apex = (a + b) / 2.0
    k_slow, w_slow = (0.94 if k is None else k), 3.2
    N = 4000
    ts = [a + (b - a) * i / N for i in range(N + 1)]
    sp = [1.0 - k_slow * math.exp(-((t - apex) / w_slow) ** 2) for t in ts]
    cum = [0.0]
    for i in range(1, N + 1):
        cum.append(cum[-1] + (sp[i] + sp[i - 1]) * 0.5 * (b - a) / N)
    total = cum[-1]

    def u_of(t):
        if t <= a:
            return 0.0
        if t >= b:
            return 1.0
        i = (t - a) / (b - a) * N
        j = int(i)
        f = i - j
        j2 = min(j + 1, N)
        return (cum[j] + (cum[j2] - cum[j]) * f) / total

    def xy(u):
        return X0 + (xr - X0) * u, yb - hh * math.sin(math.pi * u)

    samples = [(a, u_of(a))]
    t = a
    while t + 1.0 < b:
        t += 1.0
        samples.append((t, u_of(t)))
    samples.append((b, 1.0))
    return samples, xy, u_of


def arc_keyframes(name, base, samples, xy, a=None, b=None):
    a = A if a is None else a
    b = B if b is None else b

    def line(p, x, y):
        return f"      {p}% {{ transform: translate({fmt(x - base[0])}px, {fmt(y - base[1])}px) }}"

    # 起点必须用这条弧线自己的 xy(0)，不能用全局 YBASE ——
    # 月亮的弧线两端抬到了 290，写成 318 会让它在月出那一刻凭空上跳 28px
    x_start, y_start = xy(0.0)
    lines = [line("0", x_start, y_start), line(pct(a), x_start, y_start)]
    for t, u in samples[1:-1]:
        x, y = xy(u)
        lines.append(line(pct(t), x, y))
    xe, ye = xy(1.0)
    lines.append(line(pct(b), xe, ye))
    lines.append(line("100", xe, ye))
    return "\n".join(lines)


SEGMENTS = 30          # 一次过境切 30 段，每段一个相位
PHASE_PERIOD = 480.0   # 两次过境一个循环，明暗方向左右交替
U_CLEAR = 0.12         # 月盘整个越过远山山脊时的 u（此时才算"全部出现在画面中"）


def t_of_u(samples, target):
    """在 u(t) 采样表上反查时间。"""
    for i in range(len(samples) - 1):
        t0, u0 = samples[i]
        t1, u1 = samples[i + 1]
        if u0 <= target <= u1:
            f = 0.0 if u1 == u0 else (target - u0) / (u1 - u0)
            return t0 + (t1 - t0) * f
    return samples[-1][0]


def phase_keyframes(samples, moon_a, moon_b):
    """月盘整个进入画面之后才开始换相：先是一枚完整的黑新月停一下，
    然后连续走完一轮阴晴圆缺，满月正好落在天顶，再一路亏到地平线上才归零。

    形状用两段升余弦拼接：
      升起 0→94：94·(1-cos(πx))/2
      落回 94→0：94·(1+cos(πy))/2
    两段在起点、天顶、终点三处的斜率都是 0，所以既不卡顿也不会在落山前早早黑掉。
    """
    t_start = t_of_u(samples, U_CLEAR)
    t_apex = (moon_a + moon_b) / 2.0
    t_black = moon_b - 2.0          # 快贴到地平线时才全黑

    steps = []

    def add(t, off):
        steps.append((pct(t, PHASE_PERIOD), f"transform: translateX({fmt(off)}px)"))

    add(0.0, 0.0)
    for n in range(2):
        base = 240.0 * n
        sign = 1.0 if n % 2 == 0 else -1.0
        add(base + t_start - 0.5, 0.0)
        t = t_start
        while t <= t_black + 1e-6:
            if t <= t_apex:
                x = (t - t_start) / (t_apex - t_start)
                val = (1.0 - math.cos(math.pi * x)) / 2.0
            else:
                # 下降段用 1 - y^2.2：亮度压得住，直到贴近山脊才迅速收成黑盘。
                # 天顶处斜率为 0（不突兀），末端斜率不为 0，但那会儿它已经沉到山后了。
                y = min((t - t_apex) / (t_black - t_apex), 1.0)
                val = 1.0 - y ** 2.2
            add(base + t, sign * 94.0 * val)
            t += 1.0
        add(base + t_black, 0.0)
        add(base + moon_b, 0.0)
    add(PHASE_PERIOD, 0.0)
    return "\n".join(f"      {p}% {{ {d} }}" for p, d in steps)


SUN_PERIOD = 2160.0    # 太阳的弧线要跨 9 次过境，才能做到"只有日食时才在天顶停"


def sun_arc_keyframes():
    """9 次过境写进一个 2160s 的动画。n % 3 == 0 的那三次正好是日食（50 / 770 / 1490s），
    只在这三次给天顶减速；其余六次匀速通过，不停。"""
    lines = []

    def line(t, x, y):
        return ("      %s%% { transform: translate(%spx, %spx) }"
                % (pct(t, SUN_PERIOD), fmt(x - SUN_BASE[0]), fmt(y - SUN_BASE[1])))

    lines.append(line(0.0, X0, YBASE))
    for n in range(9):
        a, b = A + 240.0 * n, B + 240.0 * n
        apex = a + 48.0
        k = 0.94 if n % 3 == 0 else 0.0
        _, xy, u_of = build_arc(a, b, k=k)

        ts, t = [], a
        while t <= b + 1e-6:
            ts.append(t)
            t += 1.0 if (k > 0 and abs(t - apex) < 14.0) else 4.0
        if ts[-1] < b:
            ts.append(b)
        for tt in ts:
            x, y = xy(u_of(tt))
            lines.append(line(tt, x, y))

        # 收尾停在落点，下一次过境的第一个采样点会自然把它拉回起点，
        # 这段位移发生在太阳不可见的时候，不需要额外补关键帧。
        lines.append(line(min(b + 0.5, SUN_PERIOD), X1, YBASE))
    lines.append(line(SUN_PERIOD, X0, YBASE))
    return "\n".join(lines)


def sun_fade_keyframes():
    steps = [("0", "opacity: 0")]
    for n in range(9):
        a, b = A + 240.0 * n, B + 240.0 * n
        steps += [(pct(a, SUN_PERIOD), "opacity: 0"),
                  (pct(a + 1.5, SUN_PERIOD), "opacity: 1"),
                  (pct(b - 1.5, SUN_PERIOD), "opacity: 1"),
                  (pct(b, SUN_PERIOD), "opacity: 0")]
    steps.append(("100", "opacity: 0"))
    return steps


ECL_PERIOD = 2160.0    # 三种食相轮流出现：全食 / 大半食 / 小半食
ECLIPSES = [
    (50.0,   0.0, "total"),     # 正午，月亮正对太阳 -> 日全食
    (770.0,  44.0, "partial"),  # 月亮从太阳上方掠过 -> 大半食
    (1490.0, 62.0, "partial"),  # 擦过边缘 -> 小半食
]


def solar_eclipse_motion():
    """eclX 暗盘沿 x 滑过太阳，y 偏移决定食分：0 全食，越大越偏。"""
    steps = [("0", "transform: translate(-104px, 0px)")]
    for C, Y, kind in ECLIPSES:
        if kind == "total":
            seq = [(C - 14, -104), (C - 6, 0), (C + 6, 0), (C + 14, 104)]
        else:
            seq = [(C - 14, -104), (C, 0), (C + 14, 104)]
        for dt, x in seq:
            steps.append((pct(dt, ECL_PERIOD), f"transform: translate({x}px, {Y}px)"))
    steps.append(("100", "transform: translate(104px, 0px)"))
    return steps


def solar_eclipse_vis():
    """暗盘只在食的过程中出现，其余时间藏起来（否则换位置时会横穿太阳）。"""
    steps = [("0", "opacity: 0")]
    for C, Y, kind in ECLIPSES:
        steps += [(pct(C - 14.5, ECL_PERIOD), "opacity: 0"),
                  (pct(C - 13.5, ECL_PERIOD), "opacity: 1"),
                  (pct(C + 13.5, ECL_PERIOD), "opacity: 1"),
                  (pct(C + 14.5, ECL_PERIOD), "opacity: 0")]
    steps.append(("100", "opacity: 0"))
    return steps


def solar_corona():
    steps = [("0", "opacity: 0")]
    C = ECLIPSES[0][0]
    steps += [(pct(C - 7, ECL_PERIOD), "opacity: 0"),
              (pct(C - 5, ECL_PERIOD), "opacity: .95"),
              (pct(C + 5, ECL_PERIOD), "opacity: .95"),
              (pct(C + 7, ECL_PERIOD), "opacity: 0")]
    steps.append(("100", "opacity: 0"))
    return steps


def solar_dim():
    """全食时天光压得最狠，半食只是略暗。"""
    steps = [("0", "opacity: 0")]
    steps += [(pct(36, ECL_PERIOD), "opacity: 0"),
              (pct(42, ECL_PERIOD), "opacity: .20"),
              (pct(44, ECL_PERIOD), "opacity: .72"),
              (pct(56, ECL_PERIOD), "opacity: .72"),
              (pct(58, ECL_PERIOD), "opacity: .20"),
              (pct(64, ECL_PERIOD), "opacity: 0"),
              (pct(756, ECL_PERIOD), "opacity: 0"),
              (pct(770, ECL_PERIOD), "opacity: .26"),
              (pct(784, ECL_PERIOD), "opacity: 0"),
              (pct(1478, ECL_PERIOD), "opacity: 0"),
              (pct(1490, ECL_PERIOD), "opacity: .13"),
              (pct(1502, ECL_PERIOD), "opacity: 0")]
    steps.append(("100", "opacity: 0"))
    return steps


# ---------------------------------------------------------------- 日食 / 月食 的符号

EXTRA_DEFS = """
    <radialGradient id="holyHalo" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#FFF6D8" stop-opacity="0.40"/>
      <stop offset="0.34" stop-color="#FFE9B4" stop-opacity="0.19"/>
      <stop offset="0.68" stop-color="#FFDD9E" stop-opacity="0.06"/>
      <stop offset="1" stop-color="#FFDD9E" stop-opacity="0"/>
    </radialGradient>
    <filter id="holyGlow" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="7" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <radialGradient id="blaze" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#FFFDF2" stop-opacity="0.95"/>
      <stop offset="0.18" stop-color="#FFF0C4" stop-opacity="0.64"/>
      <stop offset="0.42" stop-color="#FFDFA0" stop-opacity="0.33"/>
      <stop offset="0.70" stop-color="#FFC98A" stop-opacity="0.13"/>
      <stop offset="1" stop-color="#FFB878" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="coreGlow" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#FFFFFF" stop-opacity="1"/>
      <stop offset="0.45" stop-color="#FFFDF0" stop-opacity="0.86"/>
      <stop offset="0.75" stop-color="#FFEFC6" stop-opacity="0.34"/>
      <stop offset="1" stop-color="#FFE3A8" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="rimWarm" x1="0" y1="0" x2="430" y2="0" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#FFDCA8" stop-opacity="0.72"/>
      <stop offset="0.45" stop-color="#FFC88E" stop-opacity="0.36"/>
      <stop offset="1" stop-color="#FFB47A" stop-opacity="0"/>
    </linearGradient>
    <radialGradient id="groundWarm" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#FFDCA8" stop-opacity="0.72"/>
      <stop offset="0.42" stop-color="#FFC98C" stop-opacity="0.38"/>
      <stop offset="1" stop-color="#FFB87A" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="dawnWash" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#FFD9A0" stop-opacity="0.44"/>
      <stop offset="0.5" stop-color="#FFC98E" stop-opacity="0.23"/>
      <stop offset="1" stop-color="#FFB87A" stop-opacity="0"/>
    </radialGradient>
    <!-- 破晓的暖光只铺在天上，不往下糊到山体上 -->
    <linearGradient id="skyFadeGrad" x1="0" y1="150" x2="0" y2="300" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#FFFFFF"/>
      <stop offset="0.55" stop-color="#FFFFFF"/>
      <stop offset="1" stop-color="#000000"/>
    </linearGradient>
    <mask id="skyFade">
      <rect x="0" y="0" width="1200" height="340" fill="url(#skyFadeGrad)"/>
    </mask>
    <radialGradient id="holyWash" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#FFF4D4" stop-opacity="0.30"/>
      <stop offset="0.5" stop-color="#FFEBB8" stop-opacity="0.20"/>
      <stop offset="0.82" stop-color="#FFE3A6" stop-opacity="0.08"/>
      <stop offset="1" stop-color="#FFE3A6" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="pentAura" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#8E0C16" stop-opacity="0.40"/>
      <stop offset="0.55" stop-color="#6E0810" stop-opacity="0.16"/>
      <stop offset="1" stop-color="#6E0810" stop-opacity="0"/>
    </radialGradient>
    <filter id="pentGlow" x="-45%" y="-45%" width="190%" height="190%">
      <feGaussianBlur stdDeviation="5" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
"""

# 日全食：城堡上空的十字架，淡金光晕罩住整座城堡
HOLY_CROSS = """
  <g class="holyCross" opacity="0">
    <ellipse cx="990" cy="222" rx="146" ry="116" fill="url(#holyWash)"/>
    <circle cx="990" cy="142" r="196" fill="url(#holyHalo)"/>
    <g filter="url(#holyGlow)" fill="#FFF6DC">
      <rect x="981" y="28" width="18" height="116" rx="3"/>
      <rect x="933" y="66" width="114" height="18" rx="3"/>
    </g>
    <g fill="#FFFFFF" opacity="0.6">
      <rect x="986" y="33" width="8" height="106" rx="2"/>
      <rect x="938" y="71" width="104" height="8" rx="2"/>
    </g>
  </g>
"""

# 破晓：盖在夜层之上的光。不用射线 —— 三道同心的柔光就够，
# 最外一层是贴着山脊的暖色地平线，被 skyFade 压住，只亮天不亮山。
SUN_BLAZE = """
  <g class="sunBlaze" opacity="0">
    <ellipse cx="882" cy="228" rx="392" ry="96" fill="url(#dawnWash)" mask="url(#skyFade)"/>
    <circle cx="882" cy="150" r="188" fill="url(#blaze)"/>
    <circle cx="882" cy="150" r="62" fill="url(#coreGlow)"/>
  </g>
"""


# 破晓的地面暖光：太阳还没照到，光先在草地和树根上化开。
# 位置固定在左侧地平线，不跟太阳跑 —— 日出那几十秒里它就该是一整片，不是一个移动的光斑。
SUN_GROUND = """
  <g class="sunGround" opacity="0">
    <ellipse cx="205" cy="324" rx="350" ry="50" fill="url(#groundWarm)"/>
    <ellipse cx="145" cy="311" rx="180" ry="27" fill="url(#groundWarm)"/>
  </g>
"""


# 月全食：血红倒五角星，里面隐约一个黑山羊头
PENTAGRAM = """
  <g class="pentagram" opacity="0">
    <g class="pentScale">
      <circle cx="990" cy="120" r="124" fill="url(#pentAura)"/>
      <g filter="url(#pentGlow)">
        <path d="M990 216 L934.2 43.2 L1080.4 149.4 L899.6 149.4 L1045.8 43.2 Z"
              fill="none" stroke="#B3121E" stroke-width="6.5" stroke-linejoin="miter"/>
        <circle cx="990" cy="120" r="101" fill="none" stroke="#B3121E"
                stroke-width="2.4" opacity="0.5"/>
      </g>
      <g class="goatHead" opacity="0.5" transform="translate(990,120)">
        <g fill="none" stroke="#0A0407" stroke-width="7" stroke-linecap="round">
          <path d="M-13 -16 C-29 -24 -37 -40 -33 -56"/>
          <path d="M13 -16 C29 -24 37 -40 33 -56"/>
        </g>
        <path d="M-19 -6 L-33 -1 L-19 5 Z" fill="#0A0407"/>
        <path d="M19 -6 L33 -1 L19 5 Z" fill="#0A0407"/>
        <path d="M0 -24 C13 -24 21 -13 20 0 C19 13 10 24 0 34 C-10 24 -19 13 -20 0 C-21 -13 -13 -24 0 -24 Z" fill="#0A0407"/>
        <ellipse cx="-10" cy="-2" rx="4" ry="2" fill="#D0182A" opacity="0.85" transform="rotate(-14 -10 -2)"/>
        <ellipse cx="10" cy="-2" rx="4" ry="2" fill="#D0182A" opacity="0.85" transform="rotate(14 10 -2)"/>
      </g>
    </g>
  </g>
"""


# ---------------------------------------------------------------- 暗版时间轴重映射

# 旧版 128s 里：2% 月出、14% 月亮越过山脊、50% 天顶、86% 偏西、98% 月落
# 新版 240s 里：50.8% 月出、56% 越过山脊、70.8% 天顶、88% 偏西、90.8% 月落
ANCHORS = [(0.0, 50.8), (2.0, 51.0), (14.0, 56.0), (50.0, 70.8),
           (86.0, 88.0), (98.0, 90.8), (100.0, 100.0)]


def remap_p(p):
    if p <= ANCHORS[0][0]:
        return ANCHORS[0][1]
    if p >= ANCHORS[-1][0]:
        return ANCHORS[-1][1]
    for i in range(len(ANCHORS) - 1):
        a0, b0 = ANCHORS[i]
        a1, b1 = ANCHORS[i + 1]
        if a0 <= p <= a1:
            if a1 == a0:
                return b1
            return b0 + (p - a0) / (a1 - a0) * (b1 - b0)
    return p


def remap_block(block):
    """把 128s 时间轴上的百分比整体搬到 240s 上。

    关键点：原来写 `0%, 9.6% { ... }` 的，重映射后 0% 会被挪到 50.8%，
    于是这个动画就没有 0% 关键帧了。缺 0% 时浏览器会拿元素自身的属性值补位
    （opacity 默认 1、transform 默认 none），结果白天也能看见狼人、棺材、裂缝。
    所以重映射之后必须显式补回 0% / 100%。
    """
    def rep(m):
        ind, p1, p2, tail = m.group(1), m.group(2), m.group(3), m.group(4)
        n1 = remap_p(float(p1))
        if p2 is None:
            return "%s%s%%%s" % (ind, fmt(n1), tail)
        n2 = remap_p(float(p2))
        return "%s%s%%, %s%%%s" % (ind, fmt(n1), fmt(n2), tail)

    mapped = re.sub(r"^(\s*)([\d.]+)%(?:\s*,\s*([\d.]+)%)?(\s*\{)", rep, block, flags=re.M)

    pairs = []
    for chunk in mapped.split("}"):
        if "{" not in chunk:
            continue
        sel, decl = chunk.rsplit("{", 1)
        for x in re.findall(r"([\d.]+)%", sel):
            pairs.append((float(x), decl.strip()))
    if not pairs:
        return mapped
    pairs.sort(key=lambda t: t[0])
    if pairs[0][0] != 0.0:
        pairs.insert(0, (0.0, pairs[0][1]))
    if pairs[-1][0] != 100.0:
        pairs.append((100.0, pairs[-1][1]))
    return "\n" + "\n".join("      %s%% { %s }" % (fmt(p), d) for p, d in pairs) + "\n    "


DARK_TIMED = ["wolfHowl", "wolfShow", "wereShow", "crackShow", "coffinRise",
              "lidOpen", "emergeBatFly", "vampHeadTilt", "vampArmSwing",
              "vampGobletFly", "vampShow2", "vampGrow", "glowBoost"]


# ---------------------------------------------------------------- 浅色版命名空间

def prefix_css(css):
    names = set(re.findall(r"@keyframes\s+([\w-]+)", css))

    def kf(m):
        return "@keyframes l-" + m.group(1)

    css = re.sub(r"@keyframes\s+([\w-]+)", kf, css)

    def anim(m):
        head, value = m.group(1), m.group(2)
        parts = []
        for item in value.split(","):
            tok = item.strip().split()
            if tok and tok[0] in names:
                tok[0] = "l-" + tok[0]
            parts.append(" ".join(tok))
        return head + ", ".join(parts)

    css = re.sub(r"(animation\s*:\s*)([^;}]+)", anim, css)
    css = re.sub(r"\.([A-Za-z][\w-]*)", lambda m: ".l-" + m.group(1), css)
    return css


def prefix_markup(text):
    text = text.replace("url(#", "url(#l-")
    text = re.sub(r'id="([^"]+)"', lambda m: 'id="l-' + m.group(1) + '"', text)
    text = re.sub(r'href="#([^"]+)"', lambda m: 'href="#l-' + m.group(1) + '"', text)
    text = re.sub(r'class="([^"]*)"',
                  lambda m: 'class="' + " ".join("l-" + c for c in m.group(1).split()) + '"', text)
    return text


# ---------------------------------------------------------------- 主流程

def main():
    dark = (ASSETS / "banner-dark.svg").read_text(encoding="utf-8")
    light = (ASSETS / "banner-light.svg").read_text(encoding="utf-8")

    ddefs, dstyle, dbody = split_svg(dark)
    ldefs, lstyle, lbody = split_svg(light)

    samples, xy, _ = build_arc()
    moon_samples, moon_xy, _ = build_arc(MOON_A, MOON_B, MOON_X1, MOON_YBASE, MOON_H)

    # ---- 暗版：重映射月亮相关时间轴
    for nm in DARK_TIMED:
        r = kf_block(dstyle, nm)
        if r:
            dstyle = replace_kf(dstyle, nm, remap_block(r[2]))

    # ---- 浅色版：先改 SMIL 时间轴，再做命名空间隔离
    ldefs = ldefs.replace('dur="128s"', 'dur="240s"')
    lbody = lbody.replace('dur="128s"', 'dur="240s"')

    sky_specs = [
        ("#F3AACB;#FFF8FB;#F3AACB", "#F3AACB;#FFF8FB;#C98FB0;#C98FB0;#F3AACB"),
        ("#EF9EC2;#FCEEF7;#EF9EC2", "#EF9EC2;#FCEEF7;#B87AA8;#B87AA8;#EF9EC2"),
        ("#C4A6EC;#F1E7FF;#C4A6EC", "#C4A6EC;#F1E7FF;#8E7BC0;#8E7BC0;#C4A6EC"),
        ("#FFCFA8;#DCEEFB;#FFCFA8", "#FFCFA8;#DCEEFB;#FFA07A;#FFA07A;#FFCFA8"),
    ]
    for old, new in sky_specs:
        ldefs = ldefs.replace(
            '<animate attributeName="stop-color" values="%s" dur="240s" repeatCount="indefinite"/>' % old,
            '<animate attributeName="stop-color" values="%s" keyTimes="0;0.2083;0.4083;0.9167;1" dur="240s" repeatCount="indefinite"/>' % new,
        )

    ldefs = ldefs.replace(
        '<animate attributeName="stop-color" values="#CDB4EA;#D9C7F1;#CDB4EA" dur="240s" repeatCount="indefinite"/>',
        '<animate attributeName="stop-color" values="#CDB4EA;#D9C7F1;#CDB4EA" keyTimes="0;0.2083;1" dur="240s" repeatCount="indefinite"/>',
    )

    ldefs = ldefs.replace(
        '<animate attributeName="cx" values="0.05;0.28;0.50;0.72;0.95" keyTimes="0;0.25;0.5;0.75;1" dur="240s" repeatCount="indefinite"/>',
        '<animate attributeName="cx" values="0.05;0.05;0.50;0.95;0.95" keyTimes="0;0.0083;0.2083;0.4083;1" dur="240s" repeatCount="indefinite"/>',
    )
    ldefs = ldefs.replace(
        '<animate attributeName="cy" values="0.88;0.38;0.218;0.38;0.88" keyTimes="0;0.25;0.5;0.75;1" dur="240s" repeatCount="indefinite"/>',
        '<animate attributeName="cy" values="0.88;0.88;0.218;0.88;0.88" keyTimes="0;0.0083;0.2083;0.4083;1" dur="240s" repeatCount="indefinite"/>',
    )

    # 日食改 720s（每三日正午一次），全食中心对准正午 t=50
    d720 = lambda a, b: (fmt(a / 720 * 100, 3), fmt(b / 720 * 100, 3))
    lstyle = replace_kf(lstyle, "eclipseDim",
        "\n      0%%, %s%% { opacity: 0 }\n      %s%% { opacity: .16 }\n      %s%%, %s%% { opacity: .72 }\n      %s%%, 100%% { opacity: 0 }\n    "
        % (d720(38, 0)[0], d720(40, 0)[0], d720(46, 0)[0], d720(54, 0)[0], d720(62, 0)[0]))
    lstyle = replace_kf(lstyle, "eclipse",
        "\n      0%%, %s%% { transform: translate(-100px, 0) }\n      %s%%, %s%% { transform: translate(0, 0) }\n      %s%%, 100%% { transform: translate(100px, 0) }\n    "
        % (d720(38, 0)[0], d720(46, 0)[0], d720(54, 0)[0], d720(62, 0)[0]))
    lstyle = replace_kf(lstyle, "corona",
        "\n      0%%, %s%% { opacity: 0 }\n      %s%%, %s%% { opacity: .95 }\n      %s%%, 100%% { opacity: 0 }\n    "
        % (d720(46, 0)[0], d720(46, 0)[0], d720(54, 0)[0], d720(54, 0)[0]))
    lstyle = lstyle.replace("eclipseDim 384s", "eclipseDim 720s")
    lstyle = lstyle.replace("eclipse 384s", "eclipse 720s")
    lstyle = lstyle.replace("corona 384s", "corona 720s")

    lstyle = prefix_css(lstyle)
    # 旧的日食关键帧和规则已被 new_css 里 2160s 的三食相版本取代
    for _nm in ("l-eclipse", "l-eclipseDim", "l-corona"):
        lstyle = drop_kf(lstyle, _nm)
    for _cls in ("l-eclX", "l-eclDim", "l-corona"):
        lstyle = re.sub(r"\." + _cls + r"\s*\{[^}]*\}", "", lstyle)
    ldefs = prefix_markup(ldefs)
    lbody = prefix_markup(lbody)

    # 两座城堡原本差 7px 高度（夜 277 / 昼 284），交叉淡入淡出时会看出重影。
    # 统一到 280.5：各自离自己的山脊只差 3.5px，看不出来，但重影没了。
    dbody = dbody.replace("translate(990,277) scale(1.12) translate(-990,-277)",
                          "translate(990,280.5) scale(1.12) translate(-990,-280.5)")
    lbody = lbody.replace("translate(990,284) scale(1.12) translate(-990,-284)",
                          "translate(990,280.5) scale(1.12) translate(-990,-280.5)")
    lbody = lbody.replace('<g class="l-deerwalk">', '<g class="l-deerwalk dn-day">', 1)

    dstyle = drop_kf(dstyle, "duskBand")     # 新版在 new_css 里，旧的删掉避免重复定义

    # ---- 时长统一：128s -> 240s
    dstyle = dstyle.replace("128s", "240s")
    lstyle = lstyle.replace("128s", "240s")

    # ---- 暗版：月食改成"慢慢变红"
    dbody = dbody.replace(
        '<g class="wolf" transform="translate(268,304.5) scale(1.0)">',
        '<g class="dn-night">\n  <g class="wolf" transform="translate(268,304.5) scale(1.0)">', 1)
    dbody = dbody.replace('\n    <rect class="eclDimM"', '\n  </g>\n    <rect class="eclDimM"', 1)

    dbody = dbody.replace(
        '<circle class="eclMoon" cx="878" cy="120" r="46" fill="url(#copper)"/>',
        '<circle class="eclMoon" cx="878" cy="120" r="46" fill="url(#copper)" opacity="0"/>',
    )
    dbody = dbody.replace(
        '<circle class="eclMoon" cx="878" cy="120" r="46" fill="url(#copper)" opacity="0"/>\n  </g>',
        '<circle class="eclMoon" cx="878" cy="120" r="46" fill="url(#copper)" opacity="0"/>\n  </g>\n'
        '  <g clip-path="url(#moonclip)">\n'
        '    <circle class="eclDark" cx="878" cy="120" r="46" fill="#160A0E" opacity="0"/>\n  </g>',
    )

    # ---- 新 CSS
    def kfs(name, steps):
        body = " ".join(f"{p}% {{ {d} }}" for p, d in steps)
        return f"    @keyframes {name} {{ {body} }}"

    ddefs_extra = ""

    css = ["    /* ===== 统一时钟 240s：日月沿同一条弧线，只在过天顶时减速 ===== */"]
    css.append("    @keyframes arcSun {")
    css.append(sun_arc_keyframes())
    css.append("    }")
    css.append("    @keyframes arcMoon {")
    css.append(arc_keyframes("arcMoon", MOON_BASE, moon_samples, moon_xy, MOON_A, MOON_B))
    css.append("    }")

    css.append(kfs("fadeSun", sun_fade_keyframes()))

    blaze = [("0", "opacity: 0")]
    for n in range(9):
        a = A + 240.0 * n
        # 峰值挪到太阳刚越过山脊之后（a+8），而不是还在山后时就把光开到最亮，
        # 否则地平线那个角上会先糊出一团过曝的白。
        blaze += [(pct(a, SUN_PERIOD), "opacity: 0"),
                  (pct(a + 2, SUN_PERIOD), "opacity: .16"),
                  (pct(a + 5, SUN_PERIOD), "opacity: .62"),
                  (pct(a + 8, SUN_PERIOD), "opacity: 1"),
                  (pct(a + 14, SUN_PERIOD), "opacity: .86"),
                  (pct(a + 22, SUN_PERIOD), "opacity: .46"),
                  (pct(a + 30, SUN_PERIOD), "opacity: .14"),
                  (pct(a + 40, SUN_PERIOD), "opacity: 0")]
    blaze.append(("100", "opacity: 0"))
    css.append(kfs("blazeIn", blaze))
    fade_m = [(0.0, 0.0), (MOON_A, 0.0), (MOON_A + 1.5, 1.0),
              (MOON_B - 1.5, 1.0), (MOON_B, 0.0), (T, 0.0)]
    css.append(kfs("fadeMoon", [(pct(t), f"opacity: {fmt(o)}") for t, o in fade_m]))
    # 夜色浓度跟着太阳高度走，而且太阳一落到底就全黑，不再拖到月出。
    css.append(kfs("nightIn", [
        ("0", "opacity: .92"),
        (pct(4), "opacity: .90"),
        (pct(8), "opacity: .86"),      # 太阳刚越过远山，天还暗着
        (pct(12), "opacity: .74"),
        (pct(16), "opacity: .56"),
        (pct(20), "opacity: .36"),
        (pct(24), "opacity: .18"),
        (pct(28), "opacity: .05"),
        (pct(32), "opacity: 0"),
        (pct(70), "opacity: 0"),
        (pct(82), "opacity: .18"),
        (pct(88), "opacity: .45"),
        (pct(94), "opacity: .78"),
        (pct(98), "opacity: 1"),       # 日落即全黑
        (pct(216), "opacity: 1"),
        (pct(232), "opacity: .94"),
        ("100", "opacity: .92"),
    ]))
    css.append(kfs("duskBand", [
        ("0", "opacity: .9"), ("41", "opacity: .9"), ("56", "opacity: 0"),
        ("84", "opacity: 0"), ("96", "opacity: .55"), ("100", "opacity: .9"),
    ]))
    css.append("    @keyframes mphaseNew {")
    css.append(phase_keyframes(moon_samples, MOON_A, MOON_B))
    css.append("    }")
    L = LUNATION * 2        # 月食隔一个满月一次
    F = FULL_AT
    css.append(kfs("eclRed", [
        ("0", "opacity: 0"),
        (pct(F - 30, L), "opacity: 0"),
        (pct(F - 6, L), "opacity: .5"),
        (pct(F - 2, L), "opacity: 1"),
        (pct(F + 10, L), "opacity: 1"),
        (pct(F + 28, L), "opacity: .42"),
        (pct(F + 42, L), "opacity: 0"),
        ("100", "opacity: 0"),
    ]))
    css.append(kfs("eclSceneDim", [
        ("0", "opacity: 0"),
        (pct(F - 22, L), "opacity: 0"),
        (pct(F - 4, L), "opacity: .15"),
        (pct(F + 10, L), "opacity: .15"),
        (pct(F + 38, L), "opacity: 0"),
        ("100", "opacity: 0"),
    ]))
    css.append(kfs("moonDimNew", [
        ("0", "opacity: .16"), ("45", "opacity: .16"), ("60", "opacity: .10"),
        ("80", "opacity: .10"), ("95", "opacity: .16"), ("100", "opacity: .16"),
    ]))
    css.append(kfs("sunFade", [
        ("0", "opacity: 0"), ("1.5", "opacity: .45"), ("9", "opacity: .9"),
        ("20.8", "opacity: 1"), ("36", "opacity: .8"), ("41", "opacity: 0"),
        ("100", "opacity: 0"),
    ]))

    css.append("    .nightScene { animation: nightIn 240s linear infinite }")
    css.append("    .l-sunwrap { animation: arcSun 2160s linear infinite, fadeSun 2160s linear infinite }")
    css.append("    .sunBlaze { animation: arcSun 2160s linear infinite, blazeIn 2160s linear infinite }")
    css.append("    .sunGround { animation: blazeIn 2160s linear infinite }")
    css.append("    .treeRim { animation: blazeIn 2160s linear infinite }")
    css.append("    .moonArc { animation: arcMoon 240s linear infinite, fadeMoon 240s linear infinite }")
    css.append("    .l-sunwash { animation: sunFade 240s linear infinite }")
    css.append(kfs("dawnBand240", [
        ("0", "opacity: .9"), ("20.8", "opacity: 0"), ("40.8", "opacity: .9"), ("100", "opacity: .9"),
    ]))
    css.append("    .l-dawnBand { animation: dawnBand240 240s ease-in-out infinite }")
    css.append("    .duskBand { animation: duskBand 240s ease-in-out infinite }")
    css.append(kfs("eclDarken", [
        ("0", "opacity: 0"),
        (pct(F - 30, L), "opacity: 0"),
        (pct(F - 10, L), "opacity: .12"),
        (pct(F - 2, L), "opacity: .46"),
        (pct(F + 10, L), "opacity: .46"),
        (pct(F + 28, L), "opacity: .12"),
        (pct(F + 42, L), "opacity: 0"),
        ("100", "opacity: 0"),
    ]))
    css.append("    .mphase { animation: mphaseNew 480s linear infinite }")
    css.append(kfs("eclipse", solar_eclipse_motion()))
    css.append(kfs("eclXvis", solar_eclipse_vis()))
    css.append(kfs("corona", solar_corona()))
    css.append(kfs("eclipseDim", solar_dim()))
    css.append("    .l-eclX { animation: eclipse 2160s linear infinite, eclXvis 2160s linear infinite }")
    css.append("    .l-corona { animation: corona 2160s linear infinite }")
    css.append("    .l-eclDim { animation: eclipseDim 2160s linear infinite; pointer-events: none }")
    css.append("    .eclDark { animation: eclDarken 960s linear infinite }")
    css.append("    .eclMoon { animation: eclRed 960s linear infinite }")
    css.append("    .eclDimM { animation: eclSceneDim 960s linear infinite; pointer-events: none }")
    css.append("    .moonDim { animation: moonDimNew 240s linear infinite }")
    css.append(kfs("dnDay", [
        ("0", "opacity: 0"), (pct(12), "opacity: 1"), ("35", "opacity: 1"),
        ("40", "opacity: 0"), ("100", "opacity: 0"),
    ]))
    css.append(kfs("dnNight", [
        ("0", "opacity: 0"), (pct(100), "opacity: 0"), (pct(114), "opacity: 1"),
        (pct(214), "opacity: 1"), (pct(230), "opacity: 0"), ("100", "opacity: 0"),
    ]))
    css.append("    .dn-day { animation: dnDay 240s linear infinite }")
    css.append("    .dn-night { animation: dnNight 240s linear infinite }")

    # 十字架：每次日食都浮现，亮度跟着食分走 —— 全食最盛，半食只是淡淡一道，
    # 日食结束就散。这样不管看到的是哪一次食，天上都有东西。
    steps = [("0", "opacity: 0")]
    for C, Y, kind in ECLIPSES:
        peak = {"total": 1.0, "partial": 0.62}[kind]
        if Y >= 55:
            peak = 0.45
        steps += [(pct(C - 14, ECL_PERIOD), "opacity: 0"),
                  (pct(C - 6, ECL_PERIOD), "opacity: %s" % fmt(peak)),
                  (pct(C + 6, ECL_PERIOD), "opacity: %s" % fmt(peak)),
                  (pct(C + 14, ECL_PERIOD), "opacity: 0")]
    steps.append(("100", "opacity: 0"))
    css.append(kfs("holyCrossIn", steps))
    css.append("    .holyCross { animation: holyCrossIn 2160s linear infinite }")

    # 月全食的倒五角星：铜红最浓时浮现，褪色时散去
    css.append(kfs("pentIn", [
        ("0", "opacity: 0"),
        (pct(F - 24, L), "opacity: 0"),
        (pct(F - 4, L), "opacity: .8"),
        (pct(F + 8, L), "opacity: 1"),
        (pct(F + 22, L), "opacity: .8"),
        (pct(F + 38, L), "opacity: 0"),
        ("100", "opacity: 0"),
    ]))
    css.append(kfs("pentPop", [
        ("0", "transform: scale(.86)"),
        (pct(F - 24, L), "transform: scale(.86)"),
        (pct(F + 6, L), "transform: scale(1)"),
        (pct(F + 18, L), "transform: scale(1)"),
        ("100", "transform: scale(.86)"),
    ]))
    css.append("    .pentagram { animation: pentIn 960s linear infinite }")
    css.append("    .pentScale { transform-box: fill-box; transform-origin: center;"
               " animation: pentPop 960s ease-out infinite }")

    lbody = lbody + HOLY_CROSS
    dbody = dbody.replace(
        '<rect width="1200" height="340" fill="url(#vig)"/>',
        PENTAGRAM + '\n<rect width="1200" height="340" fill="url(#vig)"/>', 1)

    new_css = "\n".join(css)

    title = "山野一日"
    desc = (
        "一片会自己换日夜的山野，不随浏览器的深浅色模式切换。"
        "第 2 秒太阳自东侧山脊升起，沿弧线过天顶——正午在天顶略作停留——第 98 秒西沉。"
        "天光的浓淡跟着太阳高度走，不是按固定时长切：日出时天还暗着，只剩一层淡光，"
        "星子、窗火、狼与坟都还在；太阳升高，夜的东西一件件退去——鹿先走，夜行的一批最后才收。"
        "日落反过来：太阳往下沉，天色跟着暗，一落到山脊后面就全黑，不留尾巴。"
        "全黑之后隔六秒，第 104 秒月亮就从东边起来了——先是一枚完整的黑新月，"
        "等它整个越过远山、圆盘完整地悬在画面上，相位才开始连续地转："
        "渐渐亮成蛾眉、上弦、凸月，到天顶时正好是满月，再一路亏回新月落下；相邻两次过境明暗左右交替。"
        "月全食不是每夜都有，隔一个满月才来一次，铜红缓缓浸透月盘再退去。"
        "日食分三种，轮流出现：正午月亮正对太阳是日全食，从太阳上方掠过是大半食，擦过边缘是小半食。"
        "日食时城堡上空浮起一座发光的十字架，淡金光晕笼住整座城堡：全食最盛，半食只是淡淡一道，食尽即散。"
        "月全食时反过来，城堡上空浮起巨大的血红倒五角星，里面隐约一个黑山羊头，随铜红褪去而消失。"
        "日月都只在过天顶时减速，升起与落下保持匀速，不做停顿。周期 240 秒，首尾无缝。"
    )

    out = []
    ridge = '  <path d="M0 252 C120 214 206 244 306 218'
    assert ridge in dbody, "找不到远山山脊，破晓光没处插"
    dbody = dbody.replace(ridge, SUN_BLAZE + "\n" + ridge, 1)

    # 地面暖光放在近景地形之后、草丛之前：地面被照亮，草叶仍是暗的，才有前后。
    grass = '  <g opacity="0.97">'
    assert grass in dbody, "找不到草丛，地面暖光没处插"
    dbody = dbody.replace(grass, SUN_GROUND + "\n" + grass, 1)

    # 前景高树的暖边：草丛组里混着大松树和小草，只挑"够高"的路径复制一份描边，
    # 小草太细，描上去就糊成一团了。
    gstart = dbody.index(grass)
    gend = dbody.index("\n  </g>", gstart) + len("\n  </g>")
    tall = []
    for line in dbody[gstart:gend].splitlines():
        t = line.strip()
        if not t.startswith("<path"):
            continue
        ys = [float(m.group(2)) for m in re.finditer(r"(-?[\d.]+)[ ,](-?[\d.]+)", t)]
        if ys and min(ys) < 282:
            tall.append("    " + t)
    assert tall, "没挑到高树"

    # 描边裁在树形内部：只留内侧那一半，看上去才是"光打在树的边上"，
    # 而不是给树描了一圈粗轮廓。
    ds = []
    for t in tall:
        m = re.search(r'\sd="([^"]+)"', t)
        if m:
            ds.append('    <path d="%s"/>' % m.group(1))
    clip = ('  <clipPath id="treeRimClip">\n' + "\n".join(ds) + "\n  </clipPath>")
    rim = ('  <g class="treeRim" clip-path="url(#treeRimClip)" fill="none"\n'
           '     stroke="url(#rimWarm)" stroke-width="2.1" stroke-linejoin="round" opacity="0">\n'
           + "\n".join(tall) + "\n  </g>")
    dbody = dbody[:gend] + "\n" + rim + dbody[gend:]
    ddefs_extra = clip

    out.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 340" width="2400" height="680" role="img">')
    out.append("  <title>%s</title>" % title)
    out.append("  <desc>%s</desc>" % desc)
    out.append("  <defs>")
    out.append(ddefs)
    out.append(ldefs)
    out.append(EXTRA_DEFS)
    if ddefs_extra:
        out.append(ddefs_extra)
    out.append("  </defs>")
    out.append("  <style>")
    out.append(dstyle)
    out.append(lstyle)
    out.append(new_css)
    out.append("  </style>")
    out.append('  <g class="dayScene">')
    out.append(lbody)
    out.append("  </g>")
    out.append('  <g class="nightScene">')
    out.append(dbody)
    out.append("  </g>")
    out.append("</svg>")
    svg = "\n".join(out)

    (ASSETS / "banner.svg").write_text(svg, encoding="utf-8", newline="\n")
    print("wrote assets/banner.svg  %.1f KB" % (len(svg.encode("utf-8")) / 1024))


if __name__ == "__main__":
    main()
