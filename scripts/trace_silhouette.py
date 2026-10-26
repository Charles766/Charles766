"""把位图剪影描摹成 SVG 路径（纯 Python，只依赖 Pillow）。

用法: python _trace.py <png> <输出txt> [目标高度] [阈值] [简化容差]
"""
import sys
from PIL import Image

DIRS = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]


def load_mask(path, thresh):
    im = Image.open(path).convert("L")
    w, h = im.size
    px = im.tobytes()
    mask = bytearray(w * h)
    for i, v in enumerate(px):
        if v < thresh:
            mask[i] = 1
    return mask, w, h


def label(mask, w, h):
    lab = [0] * (w * h)
    cur = 0
    for i in range(w * h):
        if mask[i] and not lab[i]:
            cur += 1
            stack = [i]
            lab[i] = cur
            while stack:
                p = stack.pop()
                y, x = divmod(p, w)
                for dy, dx in DIRS:
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w:
                        q = ny * w + nx
                        if mask[q] and not lab[q]:
                            lab[q] = cur
                            stack.append(q)
    return lab, cur


def bbox_of(lab, k, w, h):
    y0, y1, x0, x1 = h, -1, w, -1
    for p, v in enumerate(lab):
        if v == k:
            y, x = divmod(p, w)
            if y < y0: y0 = y
            if y > y1: y1 = y
            if x < x0: x0 = x
            if x > x1: x1 = x
    return x0, y0, x1, y1


def crop_set(lab, k, w, h, box):
    x0, y0, x1, y1 = box
    W, H = x1 - x0 + 1, y1 - y0 + 1
    s = set()
    for y in range(y0, y1 + 1):
        base = y * w
        for x in range(x0, x1 + 1):
            if lab[base + x] == k:
                s.add((y - y0, x - x0))
    return s, W, H


def start_point(pts):
    return min(pts, key=lambda p: (p[0], p[1]))


def trace(pts):
    start = start_point(pts)
    cur = start
    back = (start[0], start[1] - 1)
    out = [cur]
    limit = len(pts) * 12 + 100
    for _ in range(limit):
        d = (back[0] - cur[0], back[1] - cur[1])
        di = DIRS.index(d) if d in DIRS else 0
        found = None
        for k in range(8):
            nd = DIRS[(di + k) % 8]
            cand = (cur[0] + nd[0], cur[1] + nd[1])
            if cand in pts:
                found = cand
                prev = DIRS[(di + k - 1) % 8]
                back = (cur[0] + prev[0], cur[1] + prev[1])
                break
        if found is None:
            break
        cur = found
        if cur == start and len(out) > 3:
            break
        out.append(cur)
    return out


def rdp(pts, eps):
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    norm = (dx * dx + dy * dy) ** 0.5
    dmax, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        if norm == 0:
            d = ((px - x0) ** 2 + (py - y0) ** 2) ** 0.5
        else:
            d = abs(dy * px - dx * py + x1 * y0 - y1 * x0) / norm
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        return rdp(pts[: idx + 1], eps)[:-1] + rdp(pts[idx:], eps)
    return [pts[0], pts[-1]]


def simplify_closed(pts, eps):
    if len(pts) < 5:
        return pts
    half = len(pts) // 2
    a = rdp(pts[: half + 1], eps)
    b = rdp(pts[half:] + [pts[0]], eps)
    return a[:-1] + b[:-1]


def emit(pts, H, W, target_h, nd=1):
    ys = [p[0] for p in pts]
    xs = [p[1] for p in pts]
    sc = target_h / float(H)
    cx = (min(xs) + max(xs)) / 2.0
    base = max(ys)
    out = [(round((x - cx) * sc, nd), round((y - base) * sc, nd)) for y, x in pts]
    return "M" + " L".join(f"{a} {b}" for a, b in out) + " Z"


def main():
    src, dst = sys.argv[1], sys.argv[2]
    target_h = float(sys.argv[3]) if len(sys.argv) > 3 else 27.0
    thresh = int(sys.argv[4]) if len(sys.argv) > 4 else 80
    eps = float(sys.argv[5]) if len(sys.argv) > 5 else 1.2

    mask, w, h = load_mask(src, thresh)
    lab, n = label(mask, w, h)
    sizes = {}
    for v in lab:
        if v:
            sizes[v] = sizes.get(v, 0) + 1
    main_k = max(sizes, key=sizes.get)
    box = bbox_of(lab, main_k, w, h)
    pts, W, H = crop_set(lab, main_k, w, h, box)

    outer = simplify_closed(trace(pts), eps)
    d = emit(outer, H, W, target_h)

    # 内孔：不与裁剪框边界相连的背景连通域
    inv = bytearray(W * H)
    for y in range(H):
        for x in range(W):
            if (y, x) not in pts:
                inv[y * W + x] = 1
    lab2, n2 = label(inv, W, H)
    border = set()
    for x in range(W):
        border.add(lab2[x]); border.add(lab2[(H - 1) * W + x])
    for y in range(H):
        border.add(lab2[y * W]); border.add(lab2[y * W + W - 1])
    holes = []
    for k in range(1, n2 + 1):
        if k in border:
            continue
        hp = set()
        for p, v in enumerate(lab2):
            if v == k:
                y, x = divmod(p, W)
                hp.add((y, x))
        if len(hp) < (W * H) * 0.002:
            continue
        holes.append(emit(simplify_closed(trace(hp), eps), H, W, target_h))

    full = d + (" " + " ".join(holes) if holes else "")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(full)
    print(f"{src.split(chr(92))[-1]}: {W}x{H} | 外轮廓 {len(outer)} 点 | 内孔 {len(holes)} | {len(full)} 字符")


if __name__ == "__main__":
    main()
