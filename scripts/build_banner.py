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
A, B = 2.0, 98.0     # 单次过境区间
APEX = (A + B) / 2.0
X0, X1 = 60.0, 1140.0
YBASE, HEIGHT = 318.0, 244.0

SUN_BASE = (882.0, 150.0)
MOON_BASE = (878.0, 120.0)

LUNATION = 480.0     # 月相周期
FULL_AT = 170.0      # 满月 = 天顶
NEW_AT = FULL_AT + LUNATION / 2.0   # 410s，下一轮天顶，正好新月

DUSK_IN = (98.0, 122.0)     # 夜色淡入
DAWN_OUT = (220.0, 240.0)   # 夜色淡出


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


def replace_kf(css, name, new_block):
    r = kf_block(css, name)
    if r is None:
        return css
    i, k, _ = r
    head = css[: i]
    tail = css[k + 1:]
    return head + "@keyframes " + name + " {" + new_block + "}" + tail


# ---------------------------------------------------------------- 弧线

def build_arc():
    """按速度曲线积分，得到 u(t)，再映射到正弦弧上。"""
    k_slow, w_slow = 0.94, 3.2
    N = 4000
    ts = [A + (B - A) * i / N for i in range(N + 1)]
    sp = [1.0 - k_slow * math.exp(-((t - APEX) / w_slow) ** 2) for t in ts]
    cum = [0.0]
    for i in range(1, N + 1):
        cum.append(cum[-1] + (sp[i] + sp[i - 1]) * 0.5 * (B - A) / N)
    total = cum[-1]

    def u_of(t):
        if t <= A:
            return 0.0
        if t >= B:
            return 1.0
        i = (t - A) / (B - A) * N
        j = int(i)
        f = i - j
        j2 = min(j + 1, N)
        return (cum[j] + (cum[j2] - cum[j]) * f) / total

    def xy(u):
        return X0 + (X1 - X0) * u, YBASE - HEIGHT * math.sin(math.pi * u)

    samples = [(A, u_of(A))]
    t = A
    while t + 1.0 < B:
        t += 1.0
        samples.append((t, u_of(t)))
    samples.append((B, 1.0))
    return samples, xy, u_of


def arc_keyframes(name, base, samples, xy):
    def line(p, x, y):
        return f"      {p}% {{ transform: translate({fmt(x - base[0])}px, {fmt(y - base[1])}px) }}"

    lines = [line("0", X0, YBASE), line(pct(A), X0, YBASE)]
    for t, u in samples[1:-1]:
        x, y = xy(u)
        lines.append(line(pct(t), x, y))
    xe, ye = xy(1.0)
    lines.append(line(pct(B), xe, ye))
    lines.append(line("100", xe, ye))
    return "\n".join(lines)


SEGMENTS = 30          # 一次过境切 30 段，每段一个相位
SEG_LEN = 96.0 / SEGMENTS
PHASE_PERIOD = 480.0   # 两次过境一个循环，明暗方向左右交替


def phase_keyframes():
    """一次过境（96s）走完一轮阴晴圆缺，切成 30 段。
    每段固定一个相位，停 2.7s，再用 0.5s 跳到下一格 —— 相位是"换"的，不是一直"流"的。
    阴影盘 offset：0 = 全遮（新月），±94 = 全露（满月）。"""
    steps = []

    def add(t, off):
        steps.append((pct(t, PHASE_PERIOD), f"transform: translateX({fmt(off)}px)"))

    add(0.0, 0.0)
    for n in range(2):
        start = 122.0 + 240.0 * n
        sign = 1.0 if n % 2 == 0 else -1.0
        add(start - 0.4, 0.0)
        for k in range(SEGMENTS):
            t0 = start + k * SEG_LEN
            off = sign * 94.0 * math.sin(math.pi * (k + 0.5) / SEGMENTS)
            add(t0, off)
            add(t0 + 2.7, off)
        add(start + 96.0, 0.0)
    add(PHASE_PERIOD, 0.0)
    return "\n".join(f"      {p}% {{ {d} }}" for p, d in steps)


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
    def rep(m):
        ind, p1, p2, tail = m.group(1), m.group(2), m.group(3), m.group(4)
        n1 = remap_p(float(p1))
        if p2 is None:
            return "%s%s%%%s" % (ind, fmt(n1), tail)
        n2 = remap_p(float(p2))
        return "%s%s%%, %s%%%s" % (ind, fmt(n1), fmt(n2), tail)

    return re.sub(r"^(\s*)([\d.]+)%(?:\s*,\s*([\d.]+)%)?(\s*\{)", rep, block, flags=re.M)


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
    ldefs = prefix_markup(ldefs)
    lbody = prefix_markup(lbody)

    # ---- 时长统一：128s -> 240s
    dstyle = dstyle.replace("128s", "240s")
    lstyle = lstyle.replace("128s", "240s")

    # ---- 暗版：月食改成"慢慢变红"
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

    css = ["    /* ===== 统一时钟 240s：日月沿同一条弧线，只在过天顶时减速 ===== */"]
    css.append("    @keyframes arcSun {")
    css.append(arc_keyframes("arcSun", SUN_BASE, samples, xy))
    css.append("    }")
    css.append("    @keyframes arcMoon {")
    css.append(arc_keyframes("arcMoon", MOON_BASE, samples, xy))
    css.append("    }")

    fade = [(0.0, 0.0), (A, 0.0), (A + 1.5, 1.0), (B - 1.5, 1.0), (B, 0.0), (T, 0.0)]
    css.append(kfs("bodyFade", [(pct(t), f"opacity: {fmt(o)}") for t, o in fade]))
    css.append(kfs("nightIn", [
        ("0", "opacity: 0"),
        (pct(DUSK_IN[0]), "opacity: 0"),
        (pct(DUSK_IN[1]), "opacity: 1"),
        (pct(DAWN_OUT[0]), "opacity: 1"),
        ("100", "opacity: 0"),
    ]))
    css.append(kfs("duskBand", [
        ("0", "opacity: .9"), ("41", "opacity: .9"), ("56", "opacity: 0"),
        ("84", "opacity: 0"), ("96", "opacity: .55"), ("100", "opacity: .9"),
    ]))
    css.append("    @keyframes mphaseNew {")
    css.append(phase_keyframes())
    css.append("    }")
    L = LUNATION * 2        # 月食隔一个满月一次
    css.append(kfs("eclRed", [
        ("0", "opacity: 0"),
        (pct(132, L), "opacity: 0"),
        (pct(158, L), "opacity: .5"),
        (pct(168, L), "opacity: 1"),
        (pct(178, L), "opacity: 1"),
        (pct(197, L), "opacity: .42"),
        (pct(212, L), "opacity: 0"),
        ("100", "opacity: 0"),
    ]))
    css.append(kfs("eclSceneDim", [
        ("0", "opacity: 0"),
        (pct(140, L), "opacity: 0"),
        (pct(166, L), "opacity: .15"),
        (pct(180, L), "opacity: .15"),
        (pct(206, L), "opacity: 0"),
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
    css.append("    .l-sunwrap { animation: arcSun 240s linear infinite, bodyFade 240s linear infinite }")
    css.append("    .moonArc { animation: arcMoon 240s linear infinite -120s, bodyFade 240s linear infinite -120s }")
    css.append("    .l-sunwash { animation: sunFade 240s linear infinite }")
    css.append(kfs("dawnBand240", [
        ("0", "opacity: .9"), ("20.8", "opacity: 0"), ("40.8", "opacity: .9"), ("100", "opacity: .9"),
    ]))
    css.append("    .l-dawnBand { animation: dawnBand240 240s ease-in-out infinite }")
    css.append("    .duskBand { animation: duskBand 240s ease-in-out infinite }")
    css.append(kfs("eclDarken", [
        ("0", "opacity: 0"),
        (pct(132, L), "opacity: 0"),
        (pct(152, L), "opacity: .12"),
        (pct(168, L), "opacity: .46"),
        (pct(178, L), "opacity: .46"),
        (pct(197, L), "opacity: .12"),
        (pct(212, L), "opacity: 0"),
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

    new_css = "\n".join(css)

    title = "山野一日"
    desc = (
        "一片会自己换日夜的山野，不随浏览器的深浅色模式切换。"
        "第 2 秒太阳自东侧山脊升起，沿弧线过天顶——正午在天顶略作停留——第 98 秒西沉；"
        "天色转暖，暮色里昼层淡出、夜层淡入。"
        "第 122 秒月亮升起，从升起到落下的 96 秒过境均分成 30 段，每段固定一个月相，"
        "停约三秒再换下一格：新月升起，满月到天顶，再一路亏回新月落下；相邻两次过境明暗左右交替。"
        "月全食不是每夜都有，隔一个满月才来一次，铜红缓缓浸透月盘再退去。"
        "日食分三种，轮流出现：正午月亮正对太阳是日全食，从太阳上方掠过是大半食，擦过边缘是小半食。"
        "日月都只在过天顶时减速，升起与落下保持匀速，不做停顿。周期 240 秒，首尾无缝。"
    )

    out = []
    out.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 340" width="2400" height="680" role="img">')
    out.append("  <title>%s</title>" % title)
    out.append("  <desc>%s</desc>" % desc)
    out.append("  <defs>")
    out.append(ddefs)
    out.append(ldefs)
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
