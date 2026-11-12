#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""describe_parts.py —— 按人体部位切参考图，逐块反写，并把「主干 / 细节」分离。

这是自动化流程的第一步（用户 2026-11-11 规划）：
    参考图 + grounding.json（部位 bbox）
      ↓ 按部位切块（可收缩，聚焦局部）
      ↓ 逐块调 qwen3-vl-plus 反写
      ↓ 每块输出 { trunk, details[] }
    parts.json

为什么分离
----------
* **trunk（主干）**：品类 / 颜色 / 材质 / 轮廓。这是文本通道能可靠表达的部分，
  也是 layout 的 `label` 和色图的依据。
* **details（细节）**：纹样 / 五金 / 镶边 / 数量 / 位置。文本只能描述「有什么」，
  说不清「画在哪一格」——这部分靠参考 latent 或色图子区去传。

用法
----
  python tools/describe_parts.py \
      --grounding work/grounded/grounding.json \
      --image     ComfyUI/input/v2sop_ref.png \
      --out       work/parts.json \
      --shrink    0.92          # 每边向内收 8%，聚焦布料本身、避开背景
      --min-edge  48            # 切出来短边小于这个就跳过

产出
----
parts.json（list，每项）：
  id, label, trunk, details[], bbox_px[x0,y0,x1,y1], bbox_abs[y0,x0,y1,x1],
  crop（切图路径）, area_pct, raw（模型原始回复，排错用）
"""
import argparse
import base64
import io
import json
import os
import sys
import urllib.request

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

ENV = os.path.expanduser("~/.dsh/.env")
BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MODEL = "qwen3-vl-plus"

SYSTEM = (
    "You are a costume cataloguer. You look at a small crop of ONE garment part "
    "and split what you see into a trunk line and a list of details. "
    "Never invent things that are not visible in the crop. Never describe pose, "
    "body, background or lighting."
)

USER_TMPL = """This crop shows: {hint}

Split it into two parts.

PART 1 — trunk: ONE short sentence giving only what the thing IS: its category,
its main colour(s), its material/finish, and its overall silhouette.
No ornament, no hardware, no counts.

PART 2 — details: a list of discrete visible details. Each item names
(a) what it is, (b) its colour/material, (c) its shape, (d) how many,
(e) where on the part it sits. Write each as a short noun phrase, 8-22 words.
Cover ornament, pattern, gems, metalwork, trims, chains, tassels, stitching.
If you can count them, give the number. If a detail is only partly visible, say so.

Reply with JSON only, no prose, no code fence:
{{"trunk": "...", "details": ["...", "..."]}}"""


def read_key():
    for line in open(ENV, encoding="utf-8"):
        if line.startswith("QIANWEN_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("找不到 QIANWEN_API_KEY")


def b64png(im):
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def ask(key, img_b64, hint):
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img_b64}},
                {"type": "text", "text": USER_TMPL.format(hint=hint)},
            ]},
        ],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        BASE, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    txt = d["choices"][0]["message"]["content"].strip()
    if txt.startswith("```"):
        txt = txt.split("```")[1]
        txt = txt[4:] if txt.lower().startswith("json") else txt
    txt = txt.strip().strip("`")
    try:
        return json.loads(txt), txt
    except Exception:
        # 兜底：从第一个 { 到最后一个 }
        i, j = txt.find("{"), txt.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(txt[i:j + 1]), txt
            except Exception:
                pass
        return {"trunk": "", "details": []}, txt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grounding", required=True, help="ground_regions.py 的 grounding.json")
    ap.add_argument("--image", required=True, help="原参考图（用于裁切）")
    ap.add_argument("--out", required=True, help="输出 parts.json")
    ap.add_argument("--cropdir", default="", help="切图输出目录（默认与 out 同级的 crops/）")
    ap.add_argument("--shrink", type=float, default=0.92,
                    help="每边向内收缩比例（1.0 = 不缩；0.92 = 各边收 4%%）")
    ap.add_argument("--min-edge", type=int, default=48, help="短边小于此值跳过")
    ap.add_argument("--upscale", type=float, default=1.0,
                    help="切图送模型前放大倍数（小件可以放到 2.0 让纹样更清楚）")
    ap.add_argument("--canvas", default="", help="画布 WxH（默认取原图尺寸）")
    ap.add_argument("--skip", default="", help="逗号分隔要跳过的 id")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个（调试用）")
    a = ap.parse_args()

    key = read_key()
    im = Image.open(a.image)
    if im.mode == "RGBA":
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        im = bg
    im = im.convert("RGB")
    W, H = im.size
    if a.canvas:
        W, H = (int(v) for v in a.canvas.lower().split("x"))
        if im.size != (W, H):
            im = im.resize((W, H), Image.LANCZOS)
    cx, cy = W // 2, H // 2

    cropdir = a.cropdir or os.path.join(os.path.dirname(os.path.abspath(a.out)), "crops")
    os.makedirs(cropdir, exist_ok=True)

    raw = json.load(open(a.grounding, encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("items") or raw.get("results") or []
    skip = {s.strip() for s in a.skip.split(",") if s.strip()}

    parts = []
    for it in raw:
        rid = it.get("id") or it.get("name")
        if not rid or rid in skip:
            continue
        pb = it.get("pixel_box")
        if not pb or len(pb) != 4:
            print("  [skip] %-11s 无 pixel_box" % rid)
            continue
        x0, y0, x1, y1 = (int(v) for v in pb)          # [x0,y0,x1,y1]
        x0, x1 = sorted((max(0, x0), min(W, x1)))
        y0, y1 = sorted((max(0, y0), min(H, y1)))
        w, h = x1 - x0, y1 - y0
        if w < a.min_edge or h < a.min_edge:
            print("  [skip] %-11s 短边 %d < %d" % (rid, min(w, h), a.min_edge))
            continue
        # 收缩
        if a.shrink != 1.0:
            dx, dy = int(w * (1 - a.shrink) / 2), int(h * (1 - a.shrink) / 2)
            x0, y0, x1, y1 = x0 + dx, y0 + dy, x1 - dx, y1 - dy
            w, h = x1 - x0, y1 - y0
        crop = im.crop((x0, y0, x1, y1))
        if a.upscale != 1.0:
            crop = crop.resize((int(w * a.upscale), int(h * a.upscale)), Image.LANCZOS)
        cpath = os.path.join(cropdir, "%s.png" % rid)
        crop.save(cpath)

        hint = it.get("phrase") or rid
        print("  [ask ] %-11s %dx%d  %.2f%%  → %s" % (rid, w, h, w * h / float(W * H) * 100, hint[:52]), end="", flush=True)
        obj, text = ask(key, b64png(crop), hint)
        trunk = (obj.get("trunk") or "").strip()
        details = [d.strip() for d in (obj.get("details") or []) if str(d).strip()]
        if not trunk and not details:
            print("  ✗ 解析失败（原始 %d 字）" % len(text))
        else:
            print("  ✓ trunk %d 字 / details %d 条" % (len(trunk), len(details)))

        parts.append({
            "id": rid,
            "label": rid,
            "trunk": trunk,
            "details": details,
            "bbox_px": [x0, y0, x1, y1],
            "bbox_abs": [y0 - cy, x0 - cx, y1 - cy, x1 - cx],
            "crop": cpath.replace("\\", "/"),
            "area_pct": round(w * h / float(W * H) * 100, 2),
            "raw": text[:1200],
        })
        if a.limit and len(parts) >= a.limit:
            print("  [limit] 到 %d 个，停" % a.limit)
            break

    if not parts:
        sys.exit("没有任何部位被描述")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    json.dump(parts, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n写出 %s（%d 项）" % (a.out, len(parts)))
    print("=" * 70)
    for p in parts:
        print("\n[%s]  %.2f%%  bbox_abs=%s" % (p["id"], p["area_pct"], p["bbox_abs"]))
        print("  主干: %s" % (p["trunk"] or "(空)"))
        for i, d in enumerate(p["details"], 1):
            print("  细节%d: %s" % (i, d))


if __name__ == "__main__":
    main()
