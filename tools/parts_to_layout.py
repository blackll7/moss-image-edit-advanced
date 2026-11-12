#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""parts_to_layout.py —— 把 parts.json 拆成两条通道：主干提示词 + layout（细节）。

用户 2026-11-11 三步规划的第二、三步：
    ① describe_parts.py → parts.json（每部位 trunk + details[]）
    ② 本脚本 → prompt_trunk.txt（主干）+ layout.json（bbox + 细节）
    ③ moss_run.py --layout → 生成

通道分工
--------
* **主干（trunk）** → 主提示词，每条跟着它自己的 `<Item N>` 声明，保住 `<Item N>` 与
  layout 项的一一对应
* **细节（details）** → layout 的 `paint_prompt`（一条部位内的细节合并成一串，不拆框）
* **bbox** → 直接用 `parts.json` 的 `bbox_abs`（来自 grounding 的反向定位）

保留级别判据（沿用既有约定）
--------------------------
位置要不要跟姿态走：fully = legs / bodice / sash / shoes；partially = 其余。
可用 `--fully` 覆盖。

用法
----
  python tools/parts_to_layout.py \
      --parts  work/parts_all.json \
      --prompt work/prompt_trunk.txt \
      --layout work/layout_parts.json \
      --canvas 1216x1632
"""
import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_FULLY = {"legs", "bodice", "sash", "shoes"}

# 部位在句子里的自然读法（"is preserved" 的主语）
LABEL_FMT = {
    "hair": "the long braided hair",
    "veil": "the sheer head veil",
    "sleeve_r": "the right sleeve",
    "sleeve_l": "the left sleeve",
    "bodice": "the jewelled chest piece",
    "sash": "the wide waist band",
    "orb": "the silver filigree sphere",
    "drape": "the deep indigo hanging panel",
    "sash_point": "the long navy tail",
    "legs": "the loose baggy trousers",
    "shoes": "the heeled shoes",
}

ORDER = ["hair", "veil", "sleeve_r", "sleeve_l", "bodice", "sash",
         "orb", "drape", "sash_point", "legs", "shoes"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", required=True)
    ap.add_argument("--prompt", required=True, help="输出主干提示词 txt")
    ap.add_argument("--layout", required=True, help="输出 layout.json")
    ap.add_argument("--canvas", default="1216x1632")
    ap.add_argument("--fully", default="", help="逗号分隔，覆盖默认的 fully 集合")
    ap.add_argument("--skip", default="", help="逗号分隔，跳过的 id（如 sleeve_l）")
    ap.add_argument("--min-area", type=float, default=0.3, help="面积%%低于此值跳过")
    ap.add_argument("--max-area", type=float, default=0.0,
                    help="面积%%高于此值按比例缩到该值（0=不限）；用于压 drape/legs 的渗漏")
    ap.add_argument("--summary", default="", help="layout 的 summary")
    ap.add_argument("--pretty", action="store_true")
    a = ap.parse_args()

    W, H = (int(v) for v in a.canvas.lower().split("x"))
    cx, cy = W // 2, H // 2
    fully = DEFAULT_FULLY if not a.fully else {s.strip() for s in a.fully.split(",") if s.strip()}
    skip = {s.strip() for s in a.skip.split(",") if s.strip()}

    parts = json.load(open(a.parts, encoding="utf-8"))
    if isinstance(parts, dict):
        parts = parts.get("parts") or parts.get("items") or []
    by_id = {p["id"]: p for p in parts}

    # 按固定顺序排，缺的跳过
    ordered = [by_id[i] for i in ORDER if i in by_id and i not in skip]
    for p in parts:                       # 兜底：不在 ORDER 里的追加到末尾
        if p["id"] not in ORDER and p["id"] not in skip:
            ordered.append(p)

    items, lines, kept = [], [], []
    for pid in ORDER:
        pass
    for p in ordered:
        pid = p["id"]
        area = p.get("area_pct", 0.0)
        if area < a.min_area:
            print("  [skip] %-11s 面积 %.2f%% < %.2f%%" % (pid, area, a.min_area))
            continue
        bb = p.get("bbox_abs")
        if not bb or len(bb) != 4:
            print("  [skip] %-11s 无 bbox_abs" % pid)
            continue
        y0, x0, y1, x1 = (int(v) for v in bb)
        # max-area：向中心缩，避免大色块渗进画面
        if a.max_area > 0 and area > a.max_area:
            k = (a.max_area / area) ** 0.5
            ch, cw = (y0 + y1) / 2.0, (x0 + x1) / 2.0
            hh, hw = (y1 - y0) * k / 2.0, (x1 - x0) * k / 2.0
            y0, y1 = int(ch - hh), int(ch + hh)
            x0, x1 = int(cw - hw), int(cw + hw)
            print("  [缩框] %-11s %.2f%% -> %.2f%%" % (pid, area, a.max_area))
        trunk = (p.get("trunk") or "").strip()
        details = [d.strip() for d in (p.get("details") or []) if str(d).strip()]
        if not trunk:
            print("  [skip] %-11s 没有主干" % pid)
            continue
        label = LABEL_FMT.get(pid, pid)
        keep = "fully" if pid in fully else "partially"
        n = len(kept) + 1
        if keep == "fully":
            lines.append("<Item %d — %s> is fully preserved: %s" % (n, label, trunk))
        else:
            lines.append(
                "<Item %d — %s> is partially preserved; its shape and ornament stay as drawn, "
                "but its exact position may adapt to the pose: %s" % (n, label, trunk))
        paint = "; ".join(details) if details else label
        items.append({"label": "Item %d — %s" % (n, label),
                      "paint_prompt": paint, "bbox": [y0, x0, y1, x1]})
        kept.append(pid)
        print("  [keep] %-11s %-7s %.2f%%  trunk %d 字 / details %d 条"
              % (pid, keep, area, len(trunk), len(details)))

    if not items:
        sys.exit("没有可用项")

    header = ("Picture 1 is the character card. Keep exactly these parts of her design:"
              if False else "")
    body = "\n\n".join(lines)
    with open(a.prompt, "w", encoding="utf-8") as f:
        f.write(body)
    d = {"summary": {"text": a.summary} if a.summary else {},
         "items": items, "bbox_coord_space": "abs_centralized", "bbox_format": "yxyx"}
    os.makedirs(os.path.dirname(os.path.abspath(a.layout)) or ".", exist_ok=True)
    json.dump(d, open(a.layout, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1 if a.pretty else None)

    nprompt = len(body)
    print("\n写出 %s（%d 字 / %d 条）" % (a.prompt, nprompt, len(lines)))
    print("写出 %s（%d 项）" % (a.layout, len(items)))
    print("\n--- 主干提示词 ---")
    print(body)


if __name__ == "__main__":
    main()
