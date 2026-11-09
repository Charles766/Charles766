#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_banner.py — 把 banner-dark.svg / banner-light.svg 合成一张自带日月循环的 banner.svg

设计要点
--------
* 一个 240s 主时钟：太阳 2s 升、50s 天顶、98s 落；月亮 101s 升、170s 天顶、239s 落。
  日月交替只隔 3s（98 日落 → 101 月出；239 月落 → 242 次日日出），月亮区间两端各收 3s，
  中点仍是 170，天顶/月食/夜行生物的时间轴全部不动。
* 夜色浓度由 nightIn 跟着太阳高度走：太阳 98s 一落到底即全黑，不靠两张图交叉淡入淡出。
* 日月走同一条正弦弧，用积分速度曲线实现"匀速 + 过天顶柔和停留"，
  不再用 ease-in-out（那是每段关键帧各自缓动，一圈里抖六次）。
* 月相 480s 一轮（内含两次过境）：每夜月出/月落都是新月，月盘在天空中按时间线性（均等）
  地亮到满月再亏回新月，仅天顶满月处稍停留（170±4s）；相邻两夜亮面左右交替。
  月全食窗口（150~202s，与 eclSweep 对齐）内月相锁定满月，隔一个满月一次（960s），
  铜红缓慢浸入再退去。
"""

import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

T = 240.0            # 主时钟
A, B = 2.0, 98.0     # 太阳过境区间
APEX = (A + B) / 2.0
MOON_A, MOON_B = 101.0, 239.0   # 月亮过境：日落(98)全黑后隔 3 秒月出；月落(239)后隔 3 秒日出(242)。
                                # 两端各收 3s，中点仍是 170，天顶/月食/夜行生物时间轴全部不动。
MOON_X1 = 908.0                 # 月亮落点收在城堡左侧，否则会被城堡挡住十几秒
MOON_YBASE, MOON_H = 290.0, 216.0   # 月亮弧线两端抬高，少走一段山后的路
MOON_APEX = (MOON_A + MOON_B) / 2.0
X0, X1 = 60.0, 1140.0
YBASE, HEIGHT = 318.0, 244.0

SUN_BASE = (882.0, 150.0)
MOON_BASE = (878.0, 120.0)

LUNATION = 480.0     # 月相周期
ECL = LUNATION * 2.0  # 月全食隔一个满月一次 = 960s。夜行生物必须挂在这个时钟上，
                      # 否则 240s 的夜循环会让它们每晚都出来，而不是只在月食夜。
FULL_AT = MOON_APEX  # 满月 = 天顶


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


PHASE_PERIOD = 480.0   # 两次过境一个循环，明暗方向左右交替


def phase_keyframes(samples, moon_a, moon_b):
    """月相：480s 一轮，内含两次过境，相邻两夜亮面左右交替。

    几何（已确认）：mphase 阴影圆 r=46，translateX=0 时完全盖住月盘（新月/暗），
    translateX=94 时移出裁剪（满月/亮）。

    每一夜都走同一条相位曲线：月出(moon_a)与月落(moon_b)正好是新月(val=0)，
    月盘在天空中按时间线性（均等）地亮起来、再亏回去；只在天顶满月处稍作停留
    （FULL_HOLD 半宽 4s，平台共 8s）。月食窗口(ECL_HOLD_LO/HI，与 960s 月食时钟的
    扫光 eclSweep 150~202 对齐)内把月相锁定为满月，否则月相阴影会和铜色扫光
    同时作用在月亮上——两个明暗边界打架；月食本就只在满月时发生，锁满月也站得住。
    月亮在地平线以下时 val 保持 0（画面上看不到），不影响循环接缝。
    亮面左右交替的翻转仍由 sign 负责，锁定期 |X|=94 不受符号影响。
    """
    ECL_HOLD_LO, ECL_HOLD_HI = 150.0, 202.0   # 与 eclSweepMove 窗口对齐
    FULL_HOLD = 4.0                           # 普通满月在天顶 ±4s 稍停留
    vis = moon_b - moon_a                     # 一次过境的可见时长 = 138s
    hold_lo = (MOON_APEX - FULL_HOLD) - moon_a   # 满月平台在"夜内相对时间"上的两端
    hold_hi = (MOON_APEX + FULL_HOLD) - moon_a

    def value_at(t):
        if ECL_HOLD_LO <= t <= ECL_HOLD_HI:
            return 1.0                        # 月食期间锁定满月(X=94)，不与扫光争抢
        r = (t - moon_a) % 240.0              # 夜内相对时间
        if r <= 0.0 or r >= vis:
            return 0.0                        # 月出/月落及地平线下：新月
        if r < hold_lo:
            return r / hold_lo                # 新月 -> 满月，线性均等
        if r <= hold_hi:
            return 1.0                        # 满月稍停留
        return 1.0 - (r - hold_hi) / (vis - hold_hi)   # 满月 -> 新月，线性均等

    # 偶数秒步长会漏掉月出/月落(101/239)这些奇数秒锚点，显式补进关键时间点，
    # 保证月出、月落、满月平台和月食窗口的边界都有精确关键帧，而不是靠插值近似。
    times = set(range(0, int(PHASE_PERIOD) + 1, 2))
    for extra in (moon_a, moon_b, moon_a + 240.0, moon_b + 240.0,
                  MOON_APEX - FULL_HOLD, MOON_APEX + FULL_HOLD,
                  MOON_APEX + 240.0 - FULL_HOLD, MOON_APEX + 240.0 + FULL_HOLD,
                  ECL_HOLD_LO, ECL_HOLD_HI):
        if 0.0 <= extra <= PHASE_PERIOD:
            times.add(round(float(extra), 3))
    steps = []
    for t in sorted(times):
        val = value_at(float(t))
        sign = 1.0 if ((t - 50.0) % PHASE_PERIOD) < 240.0 else -1.0
        steps.append((pct(t, PHASE_PERIOD),
                      "transform: translateX(%spx)" % fmt(sign * 94.0 * val)))
    return "\n".join("      %s%% { %s }" % (p, d) for p, d in steps)


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
    <!-- 和 #copper 同色，但钉死在用户坐标上：阴影扫过时颜色不会跟着滑块跑 -->
    <radialGradient id="copperU" cx="870.6" cy="107.1" r="66.2" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#EE9468"/>
      <stop offset="0.45" stop-color="#C2552F"/>
      <stop offset="0.8" stop-color="#8E2E1E"/>
      <stop offset="1" stop-color="#5C1913"/>
    </radialGradient>
    <!-- 月全食时月亮周围的光晕：平时那圈是冷紫的，红月亮配冷光晕对不上 -->
    <radialGradient id="glowRed" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#FFA575" stop-opacity="0.72"/>
      <stop offset="0.40" stop-color="#D2542F" stop-opacity="0.30"/>
      <stop offset="1" stop-color="#8E2A1C" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="wispGlow" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#E6FFE0" stop-opacity="0.95"/>
      <stop offset="0.28" stop-color="#7CFF9E" stop-opacity="0.72"/>
      <stop offset="0.62" stop-color="#35C46A" stop-opacity="0.26"/>
      <stop offset="1" stop-color="#1E8A46" stop-opacity="0"/>
    </radialGradient>
    <!-- 血月把夜空与地面染红的"加色"光：以天顶月亮为中心，screen 混合，只在地影全食时亮起 -->
    <radialGradient id="eclBloodGrad" cx="484" cy="92" r="660" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#FF4A22" stop-opacity="0.50"/>
      <stop offset="0.34" stop-color="#D62A14" stop-opacity="0.26"/>
      <stop offset="0.68" stop-color="#7E160A" stop-opacity="0.10"/>
      <stop offset="1" stop-color="#3A0A06" stop-opacity="0"/>
    </radialGradient>
    <filter id="eclSoft" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="1.6"/>
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

    # ---- 暗版：夜行生物统一对齐到月食窗口
    # 原来是 128s 时间轴上零散的两段，重映射到 240s 之后各自为政：
    # 狼人 130s 就变了身（那时月亮才刚升起）、吸血鬼 143s 冒出来又缩回去，
    # 和月食（150-202s）完全错位。这里整段重排成一条连贯的夜戏。
    def _rows(rows):
        # 全部按 960s 的月食周期换算，并在末尾补 100%：
        # 否则最后一个关键帧落在 25% 附近，剩下四分之三的时间会被浏览器按
        # "计算值"插值，循环接缝处会跳一下。
        pairs = [(pct(t, ECL), d) for t, d in rows]
        if not pairs or pairs[-1][0] != "100":
            pairs.append(("100", rows[-1][1]))
        return "\n" + "\n".join("      %s%% { %s }" % (p, d) for p, d in pairs) + "\n    "

    NIGHT_RETIME = {
        # 地面裂缝：月食前裂开，结束后合上
        "crackShow": [(0, "opacity: 0"), (148, "opacity: 0"), (151, "opacity: 1"),
                      (203, "opacity: 1"), (206, "opacity: 0"), (240, "opacity: 0")],
        # 棺材升起 → 停留 → 沉回
        "coffinRise": [(0, "transform: translateY(34px)"), (150, "transform: translateY(34px)"),
                       (154, "transform: translateY(0px)"), (200, "transform: translateY(0px)"),
                       (204, "transform: translateY(34px)"), (240, "transform: translateY(34px)")],
        # 棺盖掀开 → 合上
        "lidOpen": [(0, "transform: translate(0, 0) rotate(0deg)"),
                    (155, "transform: translate(0, 0) rotate(0deg)"),
                    (158, "transform: translate(-3.2px, 0px) rotate(-30deg) scaleX(.42)"),
                    (196, "transform: translate(-3.2px, 0px) rotate(-30deg) scaleX(.42)"),
                    (199, "transform: translate(0, 0) rotate(0deg)"),
                    (240, "transform: translate(0, 0) rotate(0deg)")],
        # 蝙蝠飞出
        "emergeBatFly": [(0, "transform: translate(0,0); opacity: 0"),
                         (157, "transform: translate(0,0); opacity: 0"),
                         (157.8, "transform: translate(0,0); opacity: 1"),
                         (159, "transform: translate(-7px, -15px); opacity: 1"),
                         (160.5, "transform: translate(-16px, -26px); opacity: 0"),
                         (240, "transform: translate(-16px, -26px); opacity: 0")],
        # 吸血鬼：在场，全食时抬头、举杯
        "vampShow2": [(0, "opacity: 0"), (160, "opacity: 0"), (163, "opacity: 1"),
                      (196, "opacity: 1"), (199, "opacity: 0"), (240, "opacity: 0")],
        "vampGrow": [(0, "transform: scale(.42)"), (160, "transform: scale(.42)"),
                     (163, "transform: scale(1)"), (196, "transform: scale(1)"),
                     (199, "transform: scale(.42)"), (240, "transform: scale(.42)")],
        "vampHeadTilt": [(0, "transform: rotate(0deg)"), (170, "transform: rotate(0deg)"),
                         (172, "transform: rotate(-11deg)"), (178, "transform: rotate(-11deg)"),
                         (181, "transform: rotate(0deg)"), (240, "transform: rotate(0deg)")],
        "vampArmSwing": [(0, "transform: translate(0,0) rotate(0deg)"),
                         (170, "transform: translate(0,0) rotate(0deg)"),
                         (172, "transform: translate(5px, 4.6px) rotate(10deg)"),
                         (178, "transform: translate(5px, 4.6px) rotate(10deg)"),
                         (181, "transform: translate(0,0) rotate(0deg)"),
                         (240, "transform: translate(0,0) rotate(0deg)")],
        "vampGobletFly": [(0, "transform: translate(0,0) rotate(0deg); opacity: 1"),
                          (176, "transform: translate(0,0) rotate(0deg); opacity: 1"),
                          (178, "transform: translate(9px, -14px) rotate(150deg); opacity: 0"),
                          (240, "transform: translate(9px, -14px) rotate(150deg); opacity: 0")],
        # 狼人：只在全食前后变身，其余时间还是狼
        "wereShow": [(0, "opacity: 0"), (158, "opacity: 0"), (161, "opacity: 1"),
                     (197, "opacity: 1"), (200, "opacity: 0"), (240, "opacity: 0")],
        "wolfShow": [(0, "opacity: 1"), (158, "opacity: 1"), (161, "opacity: 0"),
                     (197, "opacity: 0"), (200, "opacity: 1"), (240, "opacity: 1")],
        "wolfHowl": [(0, "transform: scale(1, 1)"), (166, "transform: scale(1, 1)"),
                     (168, "transform: scale(1.03, 1.08)"), (172, "transform: scale(1.04, 1.10)"),
                     (175, "transform: scale(1, 1)"), (240, "transform: scale(1, 1)")],
        # 窗火/星光：跟着全食起伏
        "glowBoost": [(0, "opacity: 0"), (152, "opacity: 0"), (164, "opacity: .85"),
                      (186, "opacity: .85"), (200, "opacity: 0"), (240, "opacity: 0")],
    }
    for nm, rows in NIGHT_RETIME.items():
        if kf_block(dstyle, nm):
            dstyle = replace_kf(dstyle, nm, _rows(rows))

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
    NIGHT_CAST = """
  <!-- 月食夜：坟里飘出幽灵、爬出骨架，林间浮起鬼火 -->
  <!-- 场景里本来就有三块带红十字的墓碑（x≈752 / 792 / 828），这里不再加墓碑，
       只补两个被挖开的墓穴，让幽灵和骨架有个"出处"。 -->
  <g class="graves">
    <ellipse cx="772" cy="305.2" rx="7.0" ry="2.0" fill="#2C2744"/>
    <ellipse cx="772" cy="305.5" rx="5.4" ry="1.4" fill="#0A0818"/>
    <ellipse cx="810" cy="303.4" rx="6.4" ry="1.8" fill="#2C2744"/>
    <ellipse cx="810" cy="303.7" rx="4.9" ry="1.3" fill="#0A0818"/>
  </g>
  <g transform="translate(772,304)">
    <g class="ghost" opacity="0">
      <path d="M0 -14 C6.8 -14 11.2 -8.6 11.2 -2.2 L11.2 15 C9.6 12.4 7.9 15 6.0 12.4 C4.1 15 2.3 12.4 0.4 15 C-1.5 12.4 -3.3 15 -5.2 12.4 C-7.1 15 -8.8 12.4 -11.2 15 L-11.2 -2.2 C-11.2 -8.6 -6.8 -14 0 -14 Z"
            fill="#CFE4FF" opacity="0.42"/>
      <ellipse cx="-3.9" cy="-5.2" rx="1.5" ry="2.2" fill="#171430" opacity="0.85"/>
      <ellipse cx="3.9" cy="-5.2" rx="1.5" ry="2.2" fill="#171430" opacity="0.85"/>
      <ellipse cx="0" cy="-1.2" rx="1.2" ry="1.6" fill="#171430" opacity="0.35"/>
    </g>
  </g>
  <g transform="translate(810,302)">
    <g class="skel" opacity="0">
      <circle cx="0" cy="-21" r="3.5" fill="#E7E3F4"/>
      <rect x="-1.9" y="-18.6" width="3.8" height="2.2" fill="#E7E3F4"/>
      <circle cx="-1.25" cy="-21.6" r="0.85" fill="#141126"/>
      <circle cx="1.25" cy="-21.6" r="0.85" fill="#141126"/>
      <rect x="-0.55" y="-16.6" width="1.1" height="9" fill="#E7E3F4"/>
      <path d="M-3.8 -15.0 H3.8 M-3.4 -12.8 H3.4 M-3.0 -10.6 H3.0"
            stroke="#E7E3F4" stroke-width="0.95" fill="none" stroke-linecap="round"/>
      <path d="M-3.4 -14.6 L-5.8 -9.8 M3.4 -14.6 L5.8 -9.8"
            stroke="#E7E3F4" stroke-width="0.95" fill="none" stroke-linecap="round"/>
      <path d="M-1.5 -7.8 L-2.4 -1.0 M1.5 -7.8 L2.4 -1.0"
            stroke="#E7E3F4" stroke-width="0.95" fill="none" stroke-linecap="round"/>
    </g>
  </g>
  <g class="wispGate">
    <circle class="wisp wA" cx="378" cy="289" r="2.7" fill="url(#wispGlow)"/>
    <circle class="wisp wB" cx="452" cy="296" r="2.1" fill="url(#wispGlow)"/>
    <circle class="wisp wC" cx="524" cy="286" r="2.4" fill="url(#wispGlow)"/>
    <circle class="wisp wD" cx="906" cy="292" r="2.2" fill="url(#wispGlow)"/>
    <circle class="wisp wE" cx="978" cy="287" r="2.9" fill="url(#wispGlow)"/>
  </g>
"""

    dbody = dbody.replace(
        '<g class="wolf" transform="translate(268,304.5) scale(1.0)">',
        '<g class="dn-night">\n' + NIGHT_CAST + '  <g class="wolf" transform="translate(268,304.5) scale(1.0)">', 1)
    dbody = dbody.replace('\n    <rect class="eclDimM"', '\n  </g>\n    <rect class="eclDimM"', 1)

    # 红月亮不该配一圈冷紫光晕：加一层铜红，只在全食时段亮起
    dbody = dbody.replace(
        '<circle cx="878" cy="120" r="46" fill="url(#moon)">',
        '<circle class="eclGlow" cx="878" cy="120" r="156" fill="url(#glowRed)"/>\n'
        '  <circle cx="878" cy="120" r="46" fill="url(#moon)">', 1)

    # 压暗层从冷紫改成偏暖：月全食时地面是被暗红光照着的
    dbody = dbody.replace(
        '<rect class="eclDimM" width="1200" height="340" fill="#0A0818"/>',
        '<rect class="eclDimM" width="1200" height="340" fill="#1E0508"/>\n'
        '  <rect class="eclBlood" width="1200" height="340" fill="url(#eclBloodGrad)"'
        ' style="mix-blend-mode: screen"/>', 1)

    dbody = dbody.replace(
        '<circle class="eclMoon" cx="878" cy="120" r="46" fill="url(#copper)"/>',
        '<circle class="eclMoon" cx="878" cy="120" r="46" fill="url(#copper)" opacity="0"/>',
    )
    # 月食不是"整块变红"，是一道阴影从一侧扫过去。
    # 用一块比月盘大的铜色矩形在 moonclip 里平移，被圆裁掉的就是月牙状的阴影边。
    dbody = dbody.replace(
        '<circle class="eclMoon" cx="878" cy="120" r="46" fill="url(#copper)" opacity="0"/>',
        '<circle class="eclSweep" cx="878" cy="120" r="140" fill="url(#copperU)"'
        ' filter="url(#eclSoft)"/>')

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
    # 阴影扫过：150s 从左边缘进入，166s 盖满，180s 开始退出，202s 完全离开
    css.append(kfs("eclSweepMove", [
        ("0", "transform: translateX(-190px)"),
        (pct(F - 20, L), "transform: translateX(-190px)"),
        (pct(F + 32, L), "transform: translateX(192px)"),
        ("100", "transform: translateX(192px)"),
    ]))
    css.append(kfs("eclSceneDim", [
        ("0", "opacity: 0"),
        (pct(F - 15, L), "opacity: 0"),
        (pct(F - 6, L), "opacity: .30"),
        (pct(F + 14, L), "opacity: .30"),
        (pct(F + 28, L), "opacity: 0"),
        ("100", "opacity: 0"),
    ]))
    # 血光：以天顶月亮为中心的红色"加色"光，只在地影全食时亮起。
    # 用 screen 混合，所以是往场景里"添红"，而不是把蓝调地面乘暗成紫。
    css.append(kfs("eclBloodIn", [
        ("0", "opacity: 0"),
        (pct(F - 12, L), "opacity: 0"),
        (pct(F - 4, L), "opacity: .8"),
        (pct(F + 14, L), "opacity: .8"),
        (pct(F + 24, L), "opacity: 0"),
        ("100", "opacity: 0"),
    ]))
    css.append("    .eclBlood { animation: eclBloodIn 960s linear infinite; pointer-events: none }")
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
        (pct(F - 20, L), "opacity: 0"),
        (pct(F - 10, L), "opacity: .16"),
        (pct(F - 4, L), "opacity: .62"),
        (pct(F + 10, L), "opacity: .62"),
        (pct(F + 20, L), "opacity: .16"),
        (pct(F + 32, L), "opacity: 0"),
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
    css.append("    .eclSweep { animation: eclSweepMove 960s linear infinite }")
    css.append(kfs("eclGlowIn", [
        ("0", "opacity: 0"),
        (pct(F - 20, L), "opacity: 0"),
        (pct(F - 7, L), "opacity: .95"),
        (pct(F + 19, L), "opacity: .95"),
        (pct(F + 32, L), "opacity: 0"),
        ("100", "opacity: 0"),
    ]))
    css.append("    .eclGlow { animation: eclGlowIn 960s linear infinite }")
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

    # 夜行生物整体挂到 960s 的月食时钟：它们只在月全食那一夜出现。
    # 用 animation-duration 覆盖，保留原来的缓动和循环方式。
    for _cls in ("wolfhowl", "wolf", "werewolf", "vampHead", "vampArm",
                 "vampGoblet", "vampGrow", "vamp", "crack", "coffin",
                 "coffinLid", "emergeBat", "glowBoost"):
        css.append("    .%s { animation-duration: 960s }" % _cls)

    # ---- 月食夜登场的三个新角色
    css.append(kfs("ghostDrift", [
        ("0", "transform: translate(0px, 8px); opacity: 0"),
        (pct(164, ECL), "transform: translate(0px, 8px); opacity: 0"),
        (pct(168, ECL), "transform: translate(1px, -10px); opacity: .8"),
        (pct(174, ECL), "transform: translate(-10px, -24px); opacity: .85"),
        (pct(182, ECL), "transform: translate(4px, -18px); opacity: .85"),
        (pct(190, ECL), "transform: translate(-6px, -28px); opacity: .8"),
        (pct(198, ECL), "transform: translate(2px, -6px); opacity: 0"),
        ("100", "transform: translate(2px, -6px); opacity: 0"),
    ]))
    css.append(kfs("skelCrawl", [
        ("0", "transform: translate(0px, 18px); opacity: 0"),
        (pct(166, ECL), "transform: translate(0px, 18px); opacity: 0"),
        (pct(170, ECL), "transform: translate(-1px, 3px); opacity: .85"),
        (pct(173, ECL), "transform: translate(-2px, 0px); opacity: .9"),
        (pct(180, ECL), "transform: translate(-12px, 0px); opacity: .9"),
        (pct(188, ECL), "transform: translate(-24px, 0px); opacity: .85"),
        (pct(194, ECL), "transform: translate(-32px, 4px); opacity: .7"),
        (pct(198, ECL), "transform: translate(-36px, 14px); opacity: 0"),
        ("100", "transform: translate(-36px, 14px); opacity: 0"),
    ]))
    css.append(kfs("wispGate", [
        ("0", "opacity: 0"), (pct(152, ECL), "opacity: 0"), (pct(156, ECL), "opacity: 1"),
        (pct(198, ECL), "opacity: 1"), (pct(202, ECL), "opacity: 0"), ("100", "opacity: 0"),
    ]))
    css.append(kfs("wispFloat", [
        ("0", "transform: translate(0px, 0px); opacity: .25"),
        ("30", "transform: translate(3px, -6px); opacity: 1"),
        ("60", "transform: translate(-2px, -10px); opacity: .5"),
        ("85", "transform: translate(-4px, -3px); opacity: .85"),
        ("100", "transform: translate(0px, 0px); opacity: .25"),
    ]))
    # 墓穴开口跟着月食一起出现、一起合上，不整夜敞着
    css.append("    .graves { animation: crackShow 960s linear infinite }")
    css.append("    .ghost { animation: ghostDrift 960s linear infinite }")
    css.append("    .skel { animation: skelCrawl 960s linear infinite }")
    css.append("    .wispGate { animation: wispGate 960s linear infinite }")
    css.append("    .wA { animation: wispFloat 5.3s ease-in-out infinite -0.7s }")
    css.append("    .wB { animation: wispFloat 6.9s ease-in-out infinite -3.1s }")
    css.append("    .wC { animation: wispFloat 4.7s ease-in-out infinite -2.2s }")
    css.append("    .wD { animation: wispFloat 7.7s ease-in-out infinite -5.4s }")
    css.append("    .wE { animation: wispFloat 6.1s ease-in-out infinite -1.3s }")

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
        "全黑之后只隔 3 秒，第 101 秒月亮就从东边起来，一升起就是一枚新月（暗盘），"
        "月相在天空中按时间均匀地转：渐渐亮成蛾眉、上弦、凸月，到天顶时正好是满月并稍作停留，"
        "再均匀地亏回新月，第 239 秒落下；相邻两次过境明暗左右交替。"
        "月全食不是每夜都有，四个夜里才来一次，铜红缓缓浸透月盘再退去。"
        "日食分三种，轮流出现：正午月亮正对太阳是日全食，从太阳上方掠过是大半食，擦过边缘是小半食。"
        "日食时城堡上空浮起一座发光的十字架，淡金光晕笼住整座城堡：全食最盛，半食只是淡淡一道，食尽即散。"
        "月全食时反过来，城堡上空浮起巨大的血红倒五角星，里面隐约一个黑山羊头，随铜红褪去而消失。"
        "同一夜，坟土裂开，幽灵从墓里浮起，骨架爬出来在林间游荡，树丛间亮起几点绿色鬼火。"
        "日月都只在过天顶时减速，升起与落下保持匀速；日月交替只隔 3 秒，不做长时间停顿。"
        "昼夜 240 秒一轮，月相 480 秒，月全食 960 秒，日食 2160 秒——"
        "几条时钟互相错开，整张图要 8640 秒才完全重复。"
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

    # 清掉被后面规则覆盖掉的旧规则和它们的关键帧。
    # 这些是历次改版留下的：512s 的旧月食、moonArc/moonFade 的旧写法、
    # 240s 的旧月相。留着不会出错，但会让人以为它们还在起作用。
    for dead in (
        ".eclMoon { animation: lunarEclipse 512s linear infinite }",
        ".eclDark { animation: eclDarken 960s linear infinite }",
        ".eclDimM { animation: eclDimM 512s ease-in-out infinite; pointer-events: none }",
        ".moonArc { animation: moonArc 240s ease-in-out infinite, moonFade 240s ease-in-out infinite }",
        ".mphase { animation: mphase 240s linear infinite }",
    ):
        svg = svg.replace(dead, "")
    for dead_kf in ("lunarEclipse", "eclDarken", "eclDimM", "moonArc", "moonFade", "mphase"):
        svg = drop_kf(svg, dead_kf)
    svg = svg.replace("\n\n\n", "\n\n")

    (ASSETS / "banner.svg").write_text(svg, encoding="utf-8", newline="\n")
    print("wrote assets/banner.svg  %.1f KB" % (len(svg.encode("utf-8")) / 1024))


if __name__ == "__main__":
    main()
