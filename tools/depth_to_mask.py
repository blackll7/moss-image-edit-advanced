# -*- coding: utf-8 -*-
"""depth_to_mask.py —— 深度图 → 人物剪影 mask + 背景刷黑的深度图

一次做完：Otsu 阈值 → 形态学闭运算 → 最大连通域 → 填洞 → 羽化。

为什么不用 ComfyUI 核心的 ThresholdMask：
  单个全局阈值遇到「地面/渐变背景」会把地面也算进人物。
  这里用 Otsu 自适应 + 最大连通域 + 地面宽段过滤，不需要手调阈值。

输出两个文件（前缀由 --out 决定）：
  <out>_mask.png   纯黑白 mask：白=人物，黑=背景（给 MOSS 的 --mask / --ref-query-mask）
  <out>_black.png  原深度值，背景全 0（给 MOSS 的 --depth-map）

用法：
  python depth_to_mask.py 输入图 输出前缀 [--roi x1,y1,x2,y2] [--feather 3]
                                            [--floor-from 1400] [--floor-max-width 300]
                                            [--invert] [--keep-floor]

  --roi            人物大概所在矩形，裁掉外围干扰；不给就用全图
  --feather        边缘羽化半径，0 = 不羽化（默认 2）
  --floor-from     从第几行开始做「地面宽段过滤」（默认 1400，图高 20% 处起算更稳）
  --floor-max-width 该行内宽度超过这个值的连续段判为地面并丢掉（默认 300）
  --invert         反转阈值方向（背景比人物亮时用）
  --keep-floor     不做地面宽段过滤（地面本来就是人物一部分时用）
"""
import argparse
import os
import sys

import cv2
import numpy as np
from PIL import Image


def load_gray(path, width=None, height=None):
    im = Image.open(path).convert("RGB")
    if width and height and im.size != (width, height):
        im = im.resize((width, height), Image.LANCZOS)
    return np.asarray(im).astype(np.float32)[..., 0]


def drop_floor_segments(binary, start_row, max_width):
    """y >= start_row 的行里，丢掉宽度 > max_width 的连续段（那是地面，横跨全宽）。"""
    out = binary.copy()
    h, w = out.shape
    for y in range(max(0, start_row), h):
        row = out[y]
        if not row.any():
            continue
        idx = np.where(row)[0]
        split = np.where(np.diff(idx) > 8)[0]
        segs, s = [], 0
        for k in split:
            segs.append((idx[s], idx[k]))
            s = k + 1
        segs.append((idx[s], idx[-1]))
        keep = np.zeros(w, bool)
        for lo, hi in segs:
            if hi - lo < max_width:
                keep[lo:hi + 1] = True
        out[y] = keep.astype(binary.dtype)
    return out


def largest_component(binary):
    n, lab, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:
        return binary
    areas = stats[1:, cv2.CC_STAT_AREA]
    return (lab == (int(np.argmax(areas)) + 1)).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="输入深度图（webp/png/jpg）")
    ap.add_argument("out", help="输出前缀，会写出 <out>_mask.png 与 <out>_black.png")
    ap.add_argument("--width", type=int, default=0, help="先缩放到这个宽（配 --height 一起用）")
    ap.add_argument("--height", type=int, default=0)
    ap.add_argument("--roi", default="", help="人物大致区域 x1,y1,x2,y2（像素）")
    ap.add_argument("--feather", type=int, default=2, help="边缘羽化半径，0=不羽化")
    ap.add_argument("--floor-from", type=int, default=-1, help="从第几行开始做地面宽段过滤；-1 = 图高的 86%%")
    ap.add_argument("--floor-max-width", type=int, default=300)
    ap.add_argument("--invert", action="store_true", help="背景比人物亮时反转")
    ap.add_argument("--keep-floor", action="store_true", help="不做地面宽段过滤")
    a = ap.parse_args()

    if not os.path.exists(a.src):
        sys.exit("[depth_to_mask] 找不到输入：%s" % a.src)

    g = load_gray(a.src, a.width or None, a.height or None)
    H, W = g.shape
    print("[depth_to_mask] 输入 %dx%d  四角 %s" % (
        W, H, [int(g[y, x]) for y in (0, H - 1) for x in (0, W - 1)]))

    # 可选 ROI：只在这个矩形里找人物
    roi_mask = np.ones((H, W), bool)
    if a.roi:
        x1, y1, x2, y2 = [int(t) for t in a.roi.split(",")]
        roi_mask[:] = False
        roi_mask[max(0, y1):min(H, y2), max(0, x1):min(W, x2)] = True
        print("[depth_to_mask] ROI (%d,%d)-(%d,%d)" % (x1, y1, x2, y2))

    # 1) Otsu 阈值（只在 ROI 内统计，避免外围亮角干扰）
    sample = (g[roi_mask].astype(np.uint8)).reshape(-1, 1)
    thr, _ = cv2.threshold(sample, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thr = float(thr)
    print("[depth_to_mask] Otsu 阈值 %.1f%s" % (thr, "（反转）" if a.invert else ""))
    m = (g < thr) if a.invert else (g > thr)
    m = (m & roi_mask).astype(np.uint8)

    # 2) 形态学：闭运算补小洞、开运算去毛刺
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((13, 13), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))

    # 3) 地面宽段过滤（地面横跨全宽，人物脚只有几十像素宽）
    if not a.keep_floor:
        start = a.floor_from if a.floor_from >= 0 else int(H * 0.86)
        before = int(m.sum())
        m = drop_floor_segments(m, start, a.floor_max_width)
        print("[depth_to_mask] 地面过滤（y>=%d，宽>%d 丢弃）：%d → %d 像素" % (
            start, a.floor_max_width, before, int(m.sum())))

    # 4) 最大连通域
    m = largest_component(m)
    # 5) 填洞
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))

    # 6) 羽化（只给 mask 用；刷黑的深度图不羽化）
    if a.feather > 0:
        k = a.feather * 2 + 1
        mask_soft = cv2.GaussianBlur(m.astype(np.float32), (k, k), 0)
        mask_soft = np.clip(mask_soft, 0, 1)
    else:
        mask_soft = m.astype(np.float32)

    base = a.out
    mask_u8 = (mask_soft * 255).astype(np.uint8)
    Image.fromarray(mask_u8).save(base + "_mask.png")

    black = np.where(m > 0, np.clip(g, 0, 255), 0).astype(np.uint8)
    # 四角强制清零（MOSS 对深度图的硬要求）
    e = max(4, a.feather + 2)
    black[:e, :e] = 0
    black[:e, -e:] = 0
    black[-e:, :e] = 0
    black[-e:, -e:] = 0
    Image.fromarray(black).save(base + "_black.png")

    ys, xs = np.where(black > 0)
    area = (black > 0).mean() * 100
    if len(ys):
        print("[depth_to_mask] 人物 %.2f%%  bbox x %d-%d y %d-%d" % (
            area, xs.min(), xs.max(), ys.min(), ys.max()))
    print("[depth_to_mask] 四角(刷后) %s" % [int(black[y, x]) for y in (0, H - 1) for x in (0, W - 1)])
    print("[depth_to_mask] 写出：\n  %s_mask.png   白=人物\n  %s_black.png  背景全 0 的深度图"
          % (base, base))
    if area < 3:
        print("[depth_to_mask] 警告：人物面积 < 3%%，阈值可能不对，试 --invert 或给 --roi")


if __name__ == "__main__":
    main()
