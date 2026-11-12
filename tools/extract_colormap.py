#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从过渡图按调色板提取色图（GrabTag 两步生成 · 第二步的输入之一）。

用法：
    python tools/extract_colormap.py 过渡图.png --palette palette11.json --out 色图.png --stats

判定规则（都是踩过坑才有的）：
  1. 每个像素取到调色板各项 RGB 的最近欧氏距离，超阈值 → 未分类
  2. 阈值默认 55。palette11 的最小色差是 57.8；阈值 70 会把白背景吃进 silver
  3. 白背景（min(RGB) > 238）先排除
  4. 肤色规则必须带 rb < 110：金发 #d4a73a 的 R−B≈154，不加这个上限会被当肤色吃掉
     （第一次跑 hair 占 0.00% 就是这个原因）
"""
import argparse
import json
import sys

import numpy as np
from PIL import Image


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="过渡图（纯 T2I 生成的那张）")
    ap.add_argument("--palette", default=r"C:\MOSS-Deploy\work\palette11.json")
    ap.add_argument("--out", required=True, help="输出色图路径")
    ap.add_argument("--threshold", type=float, default=55.0)
    ap.add_argument("--bg-threshold", type=int, default=238)
    ap.add_argument("--stats", action="store_true", help="打印每个区域的占比")
    args = ap.parse_args()

    pal = json.load(open(args.palette, encoding="utf-8"))
    if isinstance(pal, dict) and "regions" in pal:
        pal = pal["regions"]
    # 允许两种写法：rgb 字段 或 只用 hex
    for p in pal:
        if "rgb" not in p:
            h = p.get("hex") or p.get("color")
            p["rgb"] = [int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)]
        if "hex" not in p:
            r, g, b = p["rgb"]
            p["hex"] = "#%02x%02x%02x" % (r, g, b)

    img = Image.open(args.image).convert("RGB")
    a = np.asarray(img).astype(np.float32)
    cols = np.array([p["rgb"] for p in pal], dtype=np.float32)

    d = np.linalg.norm(a[:, :, None, :] - cols[None, None, :, :], axis=3)
    idx = d.argmin(axis=2)
    mind = d.min(axis=2)

    bg = a.min(axis=2) > args.bg_threshold
    rb = a[:, :, 0] - a[:, :, 2]
    skin = ((a[:, :, 0] > 150) & (a[:, :, 1] > 110) & (a[:, :, 2] < 200)
            & (rb > 35) & (rb < 110))
    mask = (mind < args.threshold) & (~bg) & (~skin)

    out = np.full_like(a, 255, dtype=np.uint8)
    for i, p in enumerate(pal):
        r, g, b = p["rgb"]
        out[(idx == i) & mask] = np.array([r, g, b], dtype=np.uint8)

    Image.fromarray(out).save(args.out)
    print("色图写出 %s" % args.out)
    print("背景 %.1f%%  肤色 %.1f%%  命中 %.1f%%" % (
        bg.mean() * 100, skin.mean() * 100, mask.mean() * 100))
    if args.stats:
        for i, p in enumerate(pal):
            print("  %-12s %-9s %6.2f%%" % (
                p.get("id", "?"), p["hex"], ((idx == i) & mask).mean() * 100))
    # 人物框（用于后续量尺寸）
    ys, xs = np.where(mask)
    if len(ys):
        print("人物框 x %d–%d / y %d–%d（宽 %d 高 %d）" % (
            xs.min(), xs.max(), ys.min(), ys.max(),
            xs.max() - xs.min() + 1, ys.max() - ys.min() + 1))


if __name__ == "__main__":
    main()
