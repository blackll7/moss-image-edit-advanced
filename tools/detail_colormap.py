#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SOP 第三步：把 details[] 变成分区色图 + region prompt 文案

用法：
    python tools\\detail_colormap.py ^
        --parts  C:\\MOSS-Deploy\\work\\parts_all.json ^
        --picked C:\\MOSS-Deploy\\work\\picked.json ^
        --zones  legs,sash,bodice ^
        --input-dir C:\\MOSS-Deploy\\ComfyUI\\input ^
        --prefix gt ^
        --w 1216 --h 1632 ^
        --out-colormap C:\\MOSS-Deploy\\ComfyUI\\input\\cm_3.png ^
        --out-prompts  C:\\MOSS-Deploy\\work\\region_prompts.txt

输出：
    <out-colormap>   中灰底 + 若干色区（形状来自掩码，不是矩形）
    <out-prompts>    每行一条 `the <#hex> area carries ...`，可直接读成 --region-prompt

三条规则（违反会失败，见 notes\\手册-region-prompt.md）：
    1) 色区形状必须贴合衣物轮廓 —— 本脚本用 <prefix>m_<id>.png 掩码，不用矩形
    2) 色区数上限 = 互不重叠的部位数（不是固定的 3）—— 加区前先查掩码像素重叠，
       重叠 >90% 的两块合并成一个区；本案例 11 部位里两对重叠，上限 9 区
    3) 背景必须是中灰 (128,128,128) —— 白底会把姿态拉成正面站定
    4) >3 区时必须 --control-strength 1.0 --depth-strength 1.0，否则退化成多个人
"""
import argparse
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

# 区域 ID 色板：高饱和极值色，模型不会自己画出来，只当「这块归你」的编号。
# 与参考图的冰蓝 / 海军蓝 / 金 都拉开距离，避免被当成填色指令。
PALETTE = [
    "#ff00ff",  # 洋红
    "#0000ff",  # 纯蓝
    "#00ff00",  # 纯绿
    "#ff8000",  # 橙
    "#8000ff",  # 紫
    "#00ffff",  # 青
    "#ff0000",  # 纯红
    "#80ff00",  # 黄绿
    "#ff0080",  # 玫红
    "#0080ff",  # 天蓝
]

GREY = 128  # 中灰底，必须


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def load_parts(path):
    data = json.load(io.open(path, encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("parts") or data.get("items") or list(data.values())
    return {p["id"]: p for p in data if isinstance(p, dict) and p.get("id")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", required=True)
    ap.add_argument("--picked", default="", help="pick_parts.py 的 --out-selection（给了就校验 zones 都在里面）")
    ap.add_argument("--zones", required=True, help="要做成色区的部位，逗号分隔，最多 3 个")
    ap.add_argument("--input-dir", required=True, help="掩码所在目录（ComfyUI\\input）")
    ap.add_argument("--prefix", default="gt", help="掩码文件名前缀 <prefix>m_<id>.png")
    ap.add_argument("--w", type=int, default=1216)
    ap.add_argument("--h", type=int, default=1632)
    ap.add_argument("--out-colormap", required=True)
    ap.add_argument("--out-prompts", required=True)
    ap.add_argument("--max-details", type=int, default=8, help="每区最多合并多少条 details（硬上限）")
    ap.add_argument("--chars-per-pct", type=float, default=50.0,
                    help="每 1%% 画布面积配多少字符文案（面积决定文本话语权；实测 50 附近合适）")
    ap.add_argument("--min-chars", type=int, default=120, help="每区文案的保底字符数")
    args = ap.parse_args()

    import numpy as np
    from PIL import Image

    zones = [s.strip() for s in args.zones.split(",") if s.strip()]
    if len(zones) > len(PALETTE):
        print("❌ 色区数 %d 超过色板容量 %d，请减少色区或扩充 PALETTE" % (len(zones), len(PALETTE)))
        return 2
    if len(zones) > 3:
        # 旧结论「色区 > 3 会被理解成多个人」已被证伪：当年的多人真因是
        # --control-strength 0.5（深度图被砍半）。现在只要 strength 保持 1.0 就可以放多区。
        print("⚠ 色区数 %d（>3）。请确认 --control-strength 1.0 --depth-strength 1.0，"
              "否则会退化成多个人。" % len(zones))

    parts = load_parts(args.parts)
    if args.picked:
        picked = set(json.load(io.open(args.picked, encoding="utf-8")).get("picked", []))
        missing = [z for z in zones if z not in picked]
        if missing:
            print("❌ 这些色区不在第二步选中的部件里：%s" % missing)
            print("   要么改用已选中的部件，要么在 pick_parts 里把它的 --pick 加上")
            return 2

    # ---- 拼色图 ----
    base = np.full((args.h, args.w, 3), GREY, np.uint8)
    used, lines, stats = [], [], []

    for i, zid in enumerate(zones):
        mpath = os.path.join(args.input_dir, "%sm_%s.png" % (args.prefix, zid))
        if not os.path.exists(mpath):
            print("❌ 缺掩码 %s" % mpath)
            return 2
        m = np.asarray(Image.open(mpath).convert("L").resize((args.w, args.h), Image.NEAREST)) > 127
        if not m.any():
            print("❌ 掩码 %s 全黑" % mpath)
            return 2
        hexc = PALETTE[i]
        base[m] = hex_to_rgb(hexc)
        cov = m.mean() * 100
        used.append(hexc)

        p = parts.get(zid, {})
        det = [d.strip() for d in (p.get("details") or []) if d and d.strip()]
        if not det:
            det = [p.get("trunk", "").strip()] if p.get("trunk") else []

        # 按色区面积自动截断文案长度 —— 面积决定文本话语权
        # 大色区（腿 17%）吃得下整段细节；小色区（胸衣 4.7%）写多了文本会压过裁片，
        # 实测胸衣 115.3→120.6、腰 121.8→125.8 就是这么来的
        budget = max(args.min_chars, int(cov * args.chars_per_pct))
        kept, used_chars = [], 0
        for d in det:
            if used_chars >= budget and kept:
                break
            if kept and used_chars + len(d) > budget * 1.25:
                break
            kept.append(d)
            used_chars += len(d)
        if args.max_details and len(kept) > args.max_details:
            kept = kept[: args.max_details]
            used_chars = sum(len(x) for x in kept)

        body = "; ".join(s.rstrip(".") for s in kept if s)
        lines.append("the %s area carries %s." % (hexc, body))
        stats.append((zid, hexc, cov, len(kept), len(det), used_chars, budget))

    Image.fromarray(base).save(args.out_colormap)

    io.open(args.out_prompts, "w", encoding="utf-8").write("\n".join(lines) + "\n")

    total = sum(s[2] for s in stats)
    print("色图 %s  (%d 个色区，合计覆盖 %.2f%% 画布)" % (args.out_colormap, len(stats), total))
    for zid, hexc, cov, nkept, nall, nchars, budget in stats:
        print("  %-12s %s  %5.2f%%  文案 %d/%d 条 %4d 字（预算 %d）"
              % (zid, hexc, cov, nkept, nall, nchars, budget))
    print("\n文案 %s：" % args.out_prompts)
    for l in lines:
        print("  " + (l[:110] + "…" if len(l) > 110 else l))

    if total > 70:
        print("\n⚠ 色区合计覆盖 %.1f%% 画布，偏高；超过 70%% 时模型可能把画面当成色块拼图" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
