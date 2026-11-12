#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_depth.py —— 把深度图的背景刷成纯黑（SOP 第 0 步的必要处理）

为什么必须做：
  Depth-Anything 一类模型把「纯白背景」当成一个平面，输出里背景并不是均匀的
  远（黑），经常出现「一角很亮」的情况。而 MOSS 的深度图语义是「近处白、远处黑」，
  于是那个亮角就被读成「这里有一块很近的东西」，模型会在画布对应侧补画近景装饰。

  实测（2026-11-12）：参考图 1216x1632 的深度图四角亮度是
      左下 152.7   右下 243.1
      左上 153.8   右上 247.0
  右下/右上接近纯白 → 24 步生成时画面左右各多出一条贯穿全高的装饰带
  （左右边缘非白 99.7%）。把背景刷成纯黑（四角 0.0）后，两条带消失，
  左右边缘非白降到 0.0%。

用法：
    python tools/clean_depth.py --depth 深度图.png --ref 参考图.png \
        --out C:\\MOSS-Deploy\\ComfyUI\\input\\xxx_depth_black.png

    可选 --bg-max 238   判定背景的阈值（参考图三通道都 > 此值才算背景，默认 238）
    可选 --no-ref       不用参考图，直接按亮度阈值把「接近纯白」的像素刷黑

产物必须放在 ComfyUI 的 input 目录下（--depth-map 只认那里）。
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image


def main() -> int:
    ap = argparse.ArgumentParser(description="把深度图背景刷成纯黑")
    ap.add_argument("--depth", required=True, help="输入深度图（灰度）")
    ap.add_argument("--ref", default="", help="参考图，用它的背景掩码来刷黑（推荐）")
    ap.add_argument("--out", required=True, help="输出路径（建议放 ComfyUI/input/）")
    ap.add_argument("--bg-max", type=int, default=238,
                    help="参考图背景判据：三通道都 > 此值才算背景（默认 238）")
    ap.add_argument("--no-ref", action="store_true",
                    help="不给参考图，直接按深度图自身的亮度把接近纯白的刷黑")
    ap.add_argument("--white-max", type=int, default=250,
                    help="--no-ref 时的白色阈值（默认 250）")
    args = ap.parse_args()

    if not os.path.exists(args.depth):
        print("[error] 找不到深度图 %s" % args.depth)
        return 2
    dep = np.asarray(Image.open(args.depth).convert("L")).astype(np.int16)
    H, W = dep.shape
    corners = [dep[:40, :40], dep[:40, -40:], dep[-40:, :40], dep[-40:, -40:]]
    print("[before] %dx%d  四角均值 %s" % (W, H, [round(float(c.mean()), 1) for c in corners]))

    if args.no_ref:
        mask = dep >= args.white_max
        how = "按深度图自身亮度 >= %d" % args.white_max
    else:
        if not os.path.exists(args.ref):
            print("[error] 找不到参考图 %s（或者加 --no-ref）" % args.ref)
            return 2
        ref = Image.open(args.ref)
        if ref.mode == "RGBA":
            bg = Image.new("RGB", ref.size, (255, 255, 255))
            bg.paste(ref, mask=ref.split()[3])
            ref = bg
        ref = ref.convert("RGB").resize((W, H), Image.LANCZOS)
        arr = np.asarray(ref).astype(np.int16)
        mask = arr.min(axis=2) > args.bg_max
        how = "参考图三通道都 > %d" % args.bg_max

    print("[mask] %s → 背景占 %.2f%%" % (how, mask.mean() * 100))
    out = dep.copy()
    out[mask] = 0
    after = [out[:40, :40], out[:40, -40:], out[-40:, :40], out[-40:, -40:]]
    print("[after ] 四角均值 %s" % [round(float(c.mean()), 1) for c in after])

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    Image.fromarray(out.astype(np.uint8), "L").save(args.out)
    print("[write ] %s" % args.out)
    if max(float(c.mean()) for c in after) > 8:
        print("[warn  ] 四角仍偏亮，模型可能仍会把角落当成近景；可调小 --bg-max")
    return 0


if __name__ == "__main__":
    sys.exit(main())
