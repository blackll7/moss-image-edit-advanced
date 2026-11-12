#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""bbox_to_layout.py —— 把 grounding.json 的 bbox + tags 的描述合成 MOSS layout.json。

这是「全自动化」缺的最后一环：
    ground_regions.py → grounding.json（部位 bbox）
    tags_v3_real.json（部位描述，逐实体声明版）
    ↓ 本脚本
    layout.json → moss_run.py --layout（自动变色图 + 自动注入 Region 文案）

用法
----
  python tools/bbox_to_layout.py \
      --grounding work/grounded/grounding.json \
      --tags      work/reg_ice3/tags_v3_real.json \
      --canvas    1216x1632 \
      --out       work/layout_auto.json

坐标约定（关键，来自实测）
--------------------------
* `grounding.json` 的 `pixel_box` 是 **[x0, y0, x1, y1]**（左上右下，像素）
* MOSS layout 的 bbox 是 **abs_centralized `[y0, x0, y1, x1]`**
  —— 顺序是 y 在前，且以画布中心为原点：`v - 画布边长//2`
* 换算时**务必**先按 (x0,y0,x1,y1) 解读 pixel_box，再重排成 (y0,x0,y1,x1) 后减中心

跳过规则
--------
* `overlap_ids` 里的项（默认 sleeve_l）—— grounding 对左右袖返回同一个框，
  两个同位置矩形叠在一起会让色图只剩后画的一个
"""
import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")


def load_desc(tags_path):
    """从 tags json 里取 name → (label, ref_tag, preserve)。"""
    if not tags_path or not os.path.exists(tags_path):
        return {}
    d = json.load(open(tags_path, encoding="utf-8"))
    out = {}
    for t in (d.get("tags") if isinstance(d, dict) else d) or []:
        out[t.get("name")] = (
            t.get("label") or t.get("name"),
            t.get("ref_tag") or t.get("prompt") or "",
            t.get("preserve") or "partially",
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grounding", required=True, help="ground_regions.py 产出的 grounding.json")
    ap.add_argument("--tags", default="", help="tags_v3_real.json（提供 label / ref_tag）")
    ap.add_argument("--canvas", required=True, help="画布 WxH，必须与生成尺寸一致")
    ap.add_argument("--out", required=True, help="输出 layout.json")
    ap.add_argument("--summary", default="", help="layout 的 summary 字段（可空）")
    ap.add_argument("--min-area", type=float, default=0.3,
                    help="面积占比小于此值的项跳过（默认 0.3%%，太小会被色图吃掉）")
    ap.add_argument("--max-items", type=int, default=11)
    ap.add_argument("--skip", default="", help="逗号分隔，要跳过的 id")
    ap.add_argument("--overlap-ids", default="sleeve_l",
                    help="逗号分隔，这些 id 若与已收项框重合>90%% 就跳过（默认 sleeve_l）")
    ap.add_argument("--pretty", action="store_true")
    a = ap.parse_args()

    W, H = (int(v) for v in a.canvas.lower().split("x"))
    cx, cy = W // 2, H // 2

    items_raw = json.load(open(a.grounding, encoding="utf-8"))
    if isinstance(items_raw, dict):
        items_raw = items_raw.get("items") or items_raw.get("results") or []
    desc = load_desc(a.tags)

    skip = {s.strip() for s in a.skip.split(",") if s.strip()}
    overlap_ids = {s.strip() for s in a.overlap_ids.split(",") if s.strip()}

    items, taken = [], []
    for it in items_raw:
        rid = it.get("id") or it.get("name")
        if not rid or rid in skip:
            continue
        pb = it.get("pixel_box")
        if not pb or len(pb) != 4:
            print("  [skip] %-11s 没有 pixel_box" % rid)
            continue
        # pixel_box = [x0, y0, x1, y1]
        x0, y0, x1, y1 = (int(v) for v in pb)
        x0, x1 = max(0, min(x0, x1)), min(W, max(x0, x1))
        y0, y1 = max(0, min(y0, y1)), min(H, max(y0, y1))
        if x1 - x0 < 8 or y1 - y0 < 8:
            print("  [skip] %-11s 框太小 %dx%d" % (rid, x1 - x0, y1 - y0))
            continue
        area_pct = (x1 - x0) * (y1 - y0) / float(W * H) * 100
        if area_pct < a.min_area:
            print("  [skip] %-11s 面积 %.2f%% < %.2f%%" % (rid, area_pct, a.min_area))
            continue
        # 重合检测（左右袖同框是已知问题）
        if rid in overlap_ids:
            dup = False
            for (tx0, ty0, tx1, ty1, tid) in taken:
                ix = max(0, min(x1, tx1) - max(x0, tx0))
                iy = max(0, min(y1, ty1) - max(y0, ty0))
                if ix * iy > 0.9 * min((x1 - x0) * (y1 - y0), (tx1 - tx0) * (ty1 - ty0)):
                    print("  [skip] %-11s 与 %s 框重合>90%%" % (rid, tid))
                    dup = True
                    break
            if dup:
                continue
        label, ref_tag, preserve = desc.get(rid, (rid, "", "partially"))
        paint = ref_tag or (it.get("description") or "").strip()
        if not paint:
            print("  [warn] %-11s 没有描述文本，paint_prompt 用 label 顶替" % rid)
            paint = label
        # abs_centralized，[y0, x0, y1, x1]
        bbox = [y0 - cy, x0 - cx, y1 - cy, x1 - cx]
        items.append({"label": label, "paint_prompt": paint, "bbox": bbox})
        taken.append((x0, y0, x1, y1, rid))
        print("  [keep] %-11s x %4d-%4d  y %4d-%4d  %.2f%%  preserve=%s"
              % (rid, x0, x1, y0, y1, area_pct, preserve))
        if len(items) >= a.max_items:
            break

    if not items:
        sys.exit("没有可用的 layout 项")

    d = {
        "summary": {"text": a.summary} if a.summary else {},
        "items": items,
        "bbox_coord_space": "abs_centralized",
        "bbox_format": "yxyx",
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1 if a.pretty else None)
    print("\n写出 %s（%d 项 / 画布 %dx%d）" % (a.out, len(items), W, H))


if __name__ == "__main__":
    main()
