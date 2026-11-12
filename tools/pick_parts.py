#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
SOP 第二步：从 parts_all.json 选关键部件 → 切裁片 + 切掩码

用法：
    python tools\\pick_parts.py ^
        --parts  C:\\MOSS-Deploy\\work\\parts_all.json ^
        --ref    C:\\MOSS-Deploy\\ComfyUI\\input\\v2sop_ref.png ^
        --w 1216 --h 1632 ^
        --input-dir C:\\MOSS-Deploy\\ComfyUI\\input ^
        --prefix gt ^
        --max 8 ^
        --size 512 ^
        --out-selection C:\\MOSS-Deploy\\work\\picked.json

输出：
    <input-dir>\<prefix>_<id>.png        裁片（最长边 --size）
    <input-dir>\<prefix>m_<id>.png       掩码（画布同尺寸，白=该部件负责的区域）
    <out-selection>                       选中的 id 列表 + 每项打分理由

规则（优先级从高到低，见 notes\\SOP-三步出图.md §第二步）：
    1) 面积大、决定整体轮廓
    2) 位置容易漂移（sash / waist / belt / point 等）
    3) 有大块独特色彩或材质
    4) 需要和小件配对
    排除：面积 < --min-area 画布、在黑名单里的（hair / orb 等）
"""
import argparse
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

# 默认黑名单：这些部位要么常被别的部件遮住，要么在画布上面积太小
DEFAULT_BLACKLIST = {"hair", "orb", "face", "head"}

# 位置容易漂移的关键词（命中加分）
DRIFT_WORDS = ("sash", "waist", "belt", "point", "ring", "cuff")

# 需要配对的小件（如果有主体，这个也一起要）
PAIR_WORDS = ("point", "inner", "lining")


def load_parts(path):
    data = json.load(io.open(path, encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("parts") or data.get("items") or list(data.values())
    return [p for p in data if isinstance(p, dict) and p.get("id")]


def score_part(p, blacklist, min_area):
    """返回 (score, reasons) 或 (None, [拒绝理由])"""
    pid = p["id"]
    area = float(p.get("area_pct") or 0.0)
    if pid in blacklist:
        return None, ["在黑名单里（常被遮挡或过小）"]
    if area < min_area:
        return None, ["面积 %.2f%% < 阈值 %.2f%%" % (area, min_area)]

    score = area * 10.0          # 面积是主项
    reasons = ["面积 %.2f%%" % area]

    low = pid.lower()
    if any(w in low for w in DRIFT_WORDS):
        score += 5.0
        reasons.append("位置易漂 +5")
    if any(w in low for w in PAIR_WORDS):
        score += 3.0
        reasons.append("需配对 +3")
    if p.get("details"):
        score += min(len(p["details"]), 8) * 0.5
        reasons.append("细节 %d 条" % len(p["details"]))
    return score, reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", required=True, help="parts_all.json")
    ap.add_argument("--ref", required=True, help="参考图")
    ap.add_argument("--w", type=int, default=1216)
    ap.add_argument("--h", type=int, default=1632)
    ap.add_argument("--input-dir", required=True, help="ComfyUI\\input（裁片与掩码必须放这里）")
    ap.add_argument("--prefix", default="gt", help="文件名前缀，裁片 <prefix>_<id>.png、掩码 <prefix>m_<id>.png")
    ap.add_argument("--max", type=int, default=8, help="最多选几个（MOSSSetRefQueryMaskPor 上限 8）")
    ap.add_argument("--size", type=int, default=512, help="裁片最长边")
    ap.add_argument("--min-area", type=float, default=3.0, help="低于这个画布占比的不选")
    ap.add_argument("--dedup-iou", type=float, default=0.8, help="bbox 重叠超过这个比例就合并（grounding 常把相邻部位框成一块）")
    ap.add_argument("--blacklist", default=",".join(sorted(DEFAULT_BLACKLIST)))
    ap.add_argument("--pick", default="", help="强制指定（逗号分隔），给了就跳过自动打分")
    ap.add_argument("--shape-mode", default="nonwhite", choices=["nonwhite", "palette"],
                    help="nonwhite=参考图 bbox 内的非背景像素（推荐）；palette=按调色板颜色匹配（色图颜色偏离时会丢失）")
    ap.add_argument("--shape-source", default="", help="palette 模式下的部位色图（如 cm_trans8.png）")
    ap.add_argument("--palette", default="C:\\MOSS-Deploy\\work\\palette11.json", help="id → rgb 的调色板")
    ap.add_argument("--shape-tol", type=int, default=55, help="palette 模式的颜色容差")
    ap.add_argument("--bg-max", type=int, default=238, help="nonwhite 模式下超过这个亮度视为背景（与 MOSS white_bg 一致）")
    ap.add_argument("--bg-min", type=int, default=16,
                    help="nonwhite 模式下低于这个亮度的暗部（纯黑背景）也视为背景；黑底参考图必须设，"
                         "否则透明/黑背景会整块算进前景（实测纯黑可占 45%%，导致掩码面积翻倍）")
    ap.add_argument("--out-selection", default="")
    args = ap.parse_args()

    from PIL import Image

    parts = load_parts(args.parts)
    blacklist = {s.strip() for s in args.blacklist.split(",") if s.strip()}
    by_id = {p["id"]: p for p in parts}

    # ---- 选 ----
    picked, rejected = [], []
    if args.pick.strip():
        for pid in [s.strip() for s in args.pick.split(",") if s.strip()]:
            if pid not in by_id:
                print("[skip] 强制指定的 %s 不在 parts_all.json 里" % pid)
                continue
            picked.append((pid, 0.0, ["人工指定"]))
    else:
        scored = []
        for p in parts:
            s, why = score_part(p, blacklist, args.min_area)
            if s is None:
                rejected.append((p["id"], why))
            else:
                scored.append((p["id"], s, why))
        scored.sort(key=lambda x: -x[1])
        picked = [(pid, s, why) for pid, s, why in scored]   # 先去重（下一步），再截断

    if not picked:
        print("没有选出任何部件，检查 --min-area / --blacklist")
        return 1

    # ---- 切 ----
    ref = Image.open(args.ref)
    if ref.mode == "RGBA":
        bg = Image.new("RGB", ref.size, (255, 255, 255))
        bg.paste(ref, mask=ref.split()[3])
        ref = bg
    ref = ref.convert("RGB")

    # bbox 优先用像素坐标；没有就用绝对坐标换算
    def bbox_px(p):
        b = p.get("bbox_px")
        if b and len(b) == 4:
            return [int(v) for v in b]
        a = p.get("bbox_abs")
        if a and len(a) == 4:  # 相对中心、x: ±W/2, y: ±H/2
            x0, y0, x1, y1 = [float(v) for v in a]
            return [int(x0 + args.w / 2), int(y0 + args.h / 2),
                    int(x1 + args.w / 2), int(y1 + args.h / 2)]
        return None

    # 去重：bbox 完全相同或高度重叠（IoU > --dedup-iou）的只留得分最高的
    # grounding 常把左右袖、veil 与 bodice 框成同一块，两个几乎同位置的掩码会让模型混淆
    def iou(a, b):
        ax0, ay0, ax1, ay1 = a
        bx0, by0, bx1, by1 = b
        ix0, iy0 = max(ax0, bx0), max(ay0, by0)
        ix1, iy1 = min(ax1, bx1), min(ay1, by1)
        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0
        inter = (ix1 - ix0) * (iy1 - iy0)
        area_a = (ax1 - ax0) * (ay1 - ay0)
        area_b = (bx1 - bx0) * (by1 - by0)
        return inter / float(area_a + area_b - inter)

    kept = []          # [(pid, score, why, bbox)]
    for pid, s, why in picked:
        bb = bbox_px(by_id[pid])
        if bb is None:
            kept.append((pid, s, why, None))
            continue
        clash = None
        for k in kept:
            if k[3] is None:
                continue
            v = iou(bb, k[3])
            if v > args.dedup_iou:
                clash = (k, v)
                break
        if clash is None:
            kept.append((pid, s, why, bb))
        else:
            other, v = clash
            if s > other[1]:
                kept = [k for k in kept if k[0] != other[0]]
                kept.append((pid, s, why, bb))
                print("[dedup] %s 与 %s 重叠 %.0f%%，保留得分更高的 %s（%.1f > %.1f）"
                      % (other[0], pid, v * 100, pid, s, other[1]))
            else:
                print("[dedup] %s 与 %s 重叠 %.0f%%，保留得分更高的 %s（%.1f > %.1f）"
                      % (pid, other[0], v * 100, other[0], other[1], s))
    picked = [(k[0], k[1], k[2]) for k in kept]

    # 去重之后再截断到 --max，避免「先截断后去重」把有空位的名额浪费掉
    if len(picked) > args.max:
        for pid, s, why in picked[args.max:]:
            rejected.append((pid, ["超出 --max %d（去重后仍剩 %d 个），得分 %.1f"
                                   % (args.max, len(picked), s)]))
        picked = picked[: args.max]

    import numpy as np
    os.makedirs(args.input_dir, exist_ok=True)

    # ---- 形状来源：优先用真实轮廓，否则退回 bbox 矩形 ----
    # 矩形掩码会让模型把每个色块画成一个独立主体（实测非白 41%→81%），必须用真实轮廓
    # 两种来源：
    #   nonwhite（默认，推荐）＝ 参考图 bbox 内的非背景像素 —— 不依赖颜色匹配，最稳
    #   palette              ＝ 部位色图里按 palette 颜色匹配 —— 色图颜色偏离调色板时会大面积丢失
    shape_img, shape_pal, shape_tol = None, {}, args.shape_tol
    nonwhite = (args.shape_mode == "nonwhite")
    if nonwhite:
        arr = np.asarray(ref).astype(np.int16)
        # 背景判据：三个通道都接近白才算背景（min(RGB) > bg_max）
        # 用 max(RGB) 会把浅蓝衣服（如 (200,230,240) max=240）也判成背景，留下大量空洞
        # 同时排除纯黑：黑底参考图（PNG 透明区转 RGB 后是 (0,0,0)）会被 min<=238 全算成前景
        fg = (arr.min(axis=2) <= args.bg_max) & (arr.max(axis=2) >= args.bg_min)
        print("[shape] 用参考图非背景轮廓（%d<=min(RGB)<=%d，前景 %.1f%%）"
              % (args.bg_min, args.bg_max, fg.mean() * 100))
        shape_img = fg
    elif args.shape_source:
        if not os.path.exists(args.shape_source):
            print("❌ 找不到形状来源 %s" % args.shape_source)
            return 2
        shape_img = np.asarray(Image.open(args.shape_source).convert("RGB")).astype(np.int16)
        pal = json.load(io.open(args.palette, encoding="utf-8")) if args.palette else []
        shape_pal = {it["id"]: np.array(it["rgb"], dtype=np.int16) for it in pal if "rgb" in it}
        print("[shape] 从 %s 提取轮廓（palette %d 项，tol %d）"
              % (os.path.basename(args.shape_source), len(shape_pal), shape_tol))

    def shape_mask(pid, bb):
        """返回 (H,W) bool 掩码；拿不到真实形状时退回 bbox 矩形"""
        x0, y0, x1, y1 = bb
        if nonwhite:
            m = np.zeros((args.h, args.w), bool)
            m[y0:y1, x0:x1] = shape_img[y0:y1, x0:x1]
            return m
        if shape_img is not None and pid in shape_pal:
            H, W = shape_img.shape[:2]
            dist = np.abs(shape_img - shape_pal[pid]).sum(axis=2)
            hit = dist < shape_tol
            if hit.any():
                keep = np.zeros_like(hit)
                keep[y0:y1, x0:x1] = True
                hit = hit & keep
                if hit.any():
                    if (H, W) != (args.h, args.w):
                        hit = np.asarray(Image.fromarray(hit.astype(np.uint8) * 255)
                                         .resize((args.w, args.h), Image.NEAREST)) > 127
                    return hit
        m = np.zeros((args.h, args.w), bool)
        m[y0:y1, x0:x1] = True
        return m

    made = []
    for pid, s, why in picked:
        p = by_id[pid]
        bb = bbox_px(p)
        if bb is None:
            print("[skip] %s 没有 bbox" % pid)
            continue
        x0, y0, x1, y1 = bb
        x0 = max(0, min(x0, args.w - 1)); x1 = max(x0 + 1, min(x1, args.w))
        y0 = max(0, min(y0, args.h - 1)); y1 = max(y0 + 1, min(y1, args.h))

        crop = ref.crop((x0, y0, x1, y1))
        crop.thumbnail((args.size, args.size), Image.LANCZOS)
        cpath = os.path.join(args.input_dir, "%s_%s.png" % (args.prefix, pid))
        crop.save(cpath)

        m = shape_mask(pid, (x0, y0, x1, y1))
        cov = m.mean() * 100
        mpath = os.path.join(args.input_dir, "%sm_%s.png" % (args.prefix, pid))
        Image.fromarray((m.astype(np.uint8) * 255)).save(mpath)

        made.append(pid)
        print("[pick] %-12s 得分 %5.1f  bbox=(%d,%d,%d,%d)  掩码 %.2f%%  %s"
              % (pid, s, x0, y0, x1, y1, cov, "；".join(why)))

    if rejected:
        print("\n[没选]")
        for pid, why in rejected:
            print("  %-12s %s" % (pid, "；".join(why)))

    # ---- 输出可直接粘的命令片段 ----
    print("\n--- 复制到 moss_run.py ---")
    print("--image %s" % ",".join("%s_%s.png:raw" % (args.prefix, p) for p in made))
    print("--ref-labels %s" % ",".join(made))
    print("--ref-query-mask-por %s" % ",".join("%sm_%s.png" % (args.prefix, p) for p in made))

    if args.out_selection:
        io.open(args.out_selection, "w", encoding="utf-8").write(
            json.dumps({"picked": made, "input_dir": args.input_dir,
                        "prefix": args.prefix, "size": [args.w, args.h]},
                       ensure_ascii=False, indent=2))
        print("\n选择结果已写 %s（%d 个部件）" % (args.out_selection, len(made)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
