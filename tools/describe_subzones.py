#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""describe_subzones.py —— 把一个部位的掩码按垂直方向切成若干段，逐段反写。

为什么要有这一步
----------------
`describe_parts.py` 的粒度是「一个部位（如 legs 17.10%）整体写 8 条」，得到的是
**整块统计式**描述：

    "Gold-thread vertical stripes, thin and straight, running full length down
     each leg, approximately 6 per leg visible"

这种描述告诉了模型「整条腿有 6 条金线」，但没说清「裤脚那一圈有几条」「腰下那一段
渐变到多深」。因为整块图被平均了。

切成 3 段之后，每段只占原部位的三分之一，纹样密度、色彩过渡、边缘状态都会被单独
描述出来，写 region prompt 时才有「哪一段长什么样」可写。

为什么按垂直方向切
------------------
服装细节在纵向上分布不均（裤腰 / 裤腿中段 / 裤脚），横切会把左右对称的两半切开、
每块都只有一半信息。垂直切（上 / 中 / 下）正好对上「腰 / 中段 / 下摆」的自然分段。

用法
----
    python tools/describe_subzones.py ^
        --ref    ComfyUI/input/v2sop_ref.png ^
        --mask-dir ComfyUI/input ^
        --ids    legs,drape,bodice ^
        --prefix e9m_ ^
        --parts  3 ^
        --out    work/subzones.json ^
        --cropdir work/subzones

产出
----
subzones.json（list，每项）：
  id, part_mask, parts[]:
    { index, band[y0,y1], crop, area_pct_of_part, trunk, details[] }
"""
import argparse
import base64
import io
import json
import os
import sys
import urllib.request

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MODEL = "qwen3-vl-plus"
ENV = os.path.expanduser("~/.dsh/.env")

SYSTEM = """You are a costume-detail describer for a text-to-image pipeline.
You will be shown ONE horizontal slice of a garment part, cropped tight to the part.
Describe ONLY what is visible inside this slice. Never describe anything outside it.
Be concrete and countable. Use plain English, no marketing adjectives."""

USER_TMPL = """This image is one horizontal slice of a larger costume part.

PART 1 - trunk: ONE short sentence giving only what the slice shows: its category,
main colour(s), material/finish, and overall silhouette. No ornament, no counts.

PART 2 - details: a list of discrete visible details. Each item names
(a) what it is, (b) its colour/material, (c) its shape, (d) how many are visible
IN THIS SLICE, (e) where inside the slice it sits (top / middle / bottom / left /
right / along the lower edge). Write each as a short noun phrase, 8-22 words.
If you can count them, give the number. If a detail is cut off by the slice
boundary, say so.

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
        i, j = txt.find("{"), txt.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(txt[i:j + 1]), txt
            except Exception:
                pass
        return {"trunk": "", "details": []}, txt


def load_mask(path, size):
    m = Image.open(path).convert("L")
    if m.size != size:
        m = m.resize(size, Image.NEAREST)
    return np.asarray(m) > 127


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="原始参考图")
    ap.add_argument("--mask-dir", required=True, help="掩码所在目录")
    ap.add_argument("--ids", required=True, help="逗号分隔的部位 id，如 legs,drape")
    ap.add_argument("--prefix", default="e9m_", help="掩码文件名前���")
    ap.add_argument("--parts", type=int, default=3, help="垂直切几段")
    ap.add_argument("--out", required=True, help="输出 json")
    ap.add_argument("--cropdir", default="", help="切片图输出目录")
    ap.add_argument("--min-edge", type=int, default=64, help="切片短边小于此值跳过")
    ap.add_argument("--upscale", type=float, default=1.4, help="切片送模型前放大倍数")
    a = ap.parse_args()

    key = read_key()
    ref = Image.open(a.ref).convert("RGB")
    ref_np = np.asarray(ref)
    W, H = ref.size
    cropdir = a.cropdir or os.path.join(os.path.dirname(a.out), "subzones")
    os.makedirs(cropdir, exist_ok=True)

    ids = [x.strip() for x in a.ids.split(",") if x.strip()]
    result = []

    for pid in ids:
        mpath = os.path.join(a.mask_dir, a.prefix + pid + ".png")
        if not os.path.exists(mpath):
            print(f"[skip] {pid}: 找不到 {mpath}")
            continue
        mask = load_mask(mpath, (W, H))
        sel = mask.sum()
        if sel == 0:
            print(f"[skip] {pid}: 掩码为空")
            continue
        ys, xs = np.where(mask)
        y0, y1 = int(ys.min()), int(ys.max())
        x0, x1 = int(xs.min()), int(xs.max())
        print(f"[part] {pid}  bbox x {x0}-{x1} y {y0}-{y1}  面积 {sel/(W*H)*100:.2f}%")

        # 按掩码覆盖率把垂直方向切成 N 段：每段含等量的前景像素
        rows = mask.sum(axis=1)
        cum = np.cumsum(rows)
        total = cum[-1]
        cuts = [y0]
        for k in range(1, a.parts):
            target = total * k / a.parts
            yy = int(np.searchsorted(cum, target))
            cuts.append(max(cuts[-1] + 1, min(yy, y1)))
        cuts.append(y1 + 1)

        bands = []
        for k in range(a.parts):
            by0, by1 = cuts[k], cuts[k + 1]
            sub = mask[by0:by1, x0:x1 + 1]
            if sub.sum() == 0:
                continue
            # 在该段内再用掩码把背景抬灰（避免模型描述背景）
            sub_img = ref_np[by0:by1, x0:x1 + 1].copy()
            sub_mask = sub[..., None]
            sub_img = np.where(sub_mask, sub_img, np.array([128, 128, 128], np.uint8))
            crop = Image.fromarray(sub_img)
            band_area = sub.sum() / sel * 100
            if min(crop.size) < a.min_edge:
                print(f"   [skip] band{k} 尺寸 {crop.size} < {a.min_edge}")
                continue
            if a.upscale != 1.0:
                crop = crop.resize(
                    (int(crop.width * a.upscale), int(crop.height * a.upscale)),
                    Image.LANCZOS)
            cpath = os.path.join(cropdir, f"{pid}_band{k}.png")
            crop.save(cpath)
            hint = (f"part={pid} band={k+1}/{a.parts} "
                    f"(vertical slice {k+1} of {a.parts}, top to bottom)")
            try:
                obj, raw = ask(key, b64png(crop), hint)
            except Exception as e:
                print(f"   [fail] band{k}: {e}")
                obj, raw = {"trunk": "", "details": []}, str(e)
            print(f"   band{k}  {band_area:5.1f}% of part  -> {len(obj.get('details', []))} 条")
            bands.append({
                "index": k, "band": [by0, by1], "crop": cpath,
                "area_pct_of_part": round(band_area, 2),
                "trunk": obj.get("trunk", ""), "details": obj.get("details", []),
                "raw": raw,
            })
        result.append({"id": pid, "part_mask": mpath, "bbox": [x0, y0, x1, y1], "parts": bands})

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n写出 {a.out}  共 {len(result)} 个部位 / "
          f"{sum(len(r['parts']) for r in result)} 段")


if __name__ == "__main__":
    main()
