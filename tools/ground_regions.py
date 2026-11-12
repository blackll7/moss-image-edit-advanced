#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用 Qwen3-VL 做 2D grounding，把参考图按部位裁出来，再逐块反写成详细描述。

用途：A+B 链的 `--region-prompt` 需要「每个区域尽可能详细」的描述。整图反写会
把 11 件揉成一团，改成先定位、再裁、再单块反写，描述才有细节密度。

用法：
    python tools/ground_regions.py --image 参考图.png --outdir work/grounded
    python tools/ground_regions.py --image 参考图.png --outdir work/grounded --describe

`--describe` 会对每块裁剪图再调一次模型做详细中文描述（慢一倍）。

坐标约定：模型返回 [y0, x0, y1, x1]，归一化到 0-1000。
"""
import argparse
import base64
import json
import os
import sys
import urllib.request

from PIL import Image

ENV = os.path.expanduser("~/.dsh/.env")
BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MODEL = "qwen3-vl-plus"

# 11 件：id → 给模型看的英文描述（要具体，别用 "the pants" 这种，模型会找错）
PHRASES = {
    "hair":      "the long blonde hair in a thick braid",
    "veil":      "the sheer pale cloth draped over the head and shoulders",
    "sleeve_r":  "the wide pale-blue sleeve on the right upper arm",
    "sleeve_l":  "the wide blue sleeve on the left upper arm",
    "bodice":    "the small jewelled top covering only the chest",
    "sash":      "the wide decorated band wrapped around the waist",
    "orb":       "the small round silver ornament hanging at the left hip",
    "drape":     "the long dark blue cloth panel hanging from the left hip down past the knee",
    "sash_point":"the short dark strip hanging in front of the waist",
    "legs":      "the wide loose trousers covering both legs down to the ankles",
    "shoes":     "the pointed shoes on the feet",
}


def load_key():
    for line in open(ENV, encoding="utf-8"):
        if line.startswith("QIANWEN_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("QIANWEN_API_KEY 不在 %s" % ENV)


def call(key, b64, prompt, max_tokens=200):
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
            {"type": "text", "text": prompt},
        ]}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    req = urllib.request.Request(
        BASE, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        j = json.loads(r.read().decode())
    return j["choices"][0]["message"]["content"]


def parse_box(text):
    """从回复里抠出 [y0,x0,y1,x1]，容忍 ```json 包裹与多余文字。"""
    i, j = text.find("["), text.rfind("]")
    if i < 0 or j < 0:
        return None
    try:
        vals = json.loads(text[i:j + 1])
    except Exception:
        return None
    if not isinstance(vals, list) or len(vals) != 4:
        return None
    try:
        return [float(v) for v in vals]
    except Exception:
        return None


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--pad", type=float, default=0.04, help="裁剪时四周留的归一化边距")
    ap.add_argument("--describe", action="store_true")
    ap.add_argument("--only", default="", help="逗号分隔的 id，只跑这几个")
    args = ap.parse_args()

    key = load_key()
    img = Image.open(args.image).convert("RGB")
    W, H = img.size
    os.makedirs(args.outdir, exist_ok=True)
    print("图 %dx%d  输出 %s" % (W, H, args.outdir))

    ids = [s.strip() for s in args.only.split(",") if s.strip()] or list(PHRASES)
    results = []

    for rid in ids:
        phrase = PHRASES[rid]
        b64 = base64.b64encode(open(args.image, "rb").read()).decode()
        prompt = (
            "请在这张图中定位「%s」。\n"
            "只输出 JSON：{\"box_2d\": [xmin, ymin, xmax, ymax]}，四个整数归一化到 0-1000"
            "（相对图宽与图高）。不要输出其它文字。" % phrase)
        try:
            reply = call(key, b64, prompt)
            box = parse_box(reply)
        except Exception as e:
            print("  %-10s FAIL %s" % (rid, e))
            continue
        if box is None:
            print("  %-10s 解析失败: %r" % (rid, reply[:80]))
            continue

        x0, y0, x1, y1 = box
        # 归一化 → 像素，加边距，夹到图内
        py0 = max(0, int((min(y0, y1) / 1000.0 - args.pad) * H))
        py1 = min(H, int((max(y0, y1) / 1000.0 + args.pad) * H))
        px0 = max(0, int((min(x0, x1) / 1000.0 - args.pad) * W))
        px1 = min(W, int((max(x0, x1) / 1000.0 + args.pad) * W))
        if px1 - px0 < 8 or py1 - py0 < 8:
            print("  %-10s 框太小，跳过 %s" % (rid, box))
            continue

        crop = img.crop((px0, py0, px1, py1))
        cpath = os.path.join(args.outdir, "%s.png" % rid)
        crop.save(cpath)
        print("  %-10s box=%s → 像素 (%d,%d)-(%d,%d)  %dx%d" % (
            rid, [int(v) for v in box], px0, py0, px1, py1, crop.size[0], crop.size[1]))

        desc = ""
        if args.describe:
            cb64 = base64.b64encode(open(cpath, "rb").read()).decode()
            dprompt = (
                "描述这张局部图里能看到的一切：形状、边缘轮廓、材质与光泽、颜色（含明暗与渐变）、"
                "纹样与图案（逐个数清数量与排列）、金属件与宝石的镶嵌方式、以及它相对人体的位置。"
                "只写看得见的，不要推测。用中文，300 字以内，不分段。")
            try:
                desc = call(key, cb64, dprompt, max_tokens=700).strip().replace("\n", " ")
                print("      描述 %d 字" % len(desc))
            except Exception as e:
                print("      描述 FAIL %s" % e)

        results.append({
            "id": rid, "phrase": phrase, "box_2d": [int(v) for v in box],
            "pixel_box": [px0, py0, px1, py1],
            "size": [crop.size[0], crop.size[1]],
            "crop": cpath.replace("\\", "/"),
            "description": desc,
        })

    out = os.path.join(args.outdir, "grounding.json")
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n写出 %s（%d 项）" % (out, len(results)))


if __name__ == "__main__":
    main()
