# -*- coding: utf-8 -*-
"""region_ask.py —— 给定一张图 + 一个位置，问「这块区域里是什么」。

两种模式：
  --region x,y,w,h   把该区域裁出来、放大到 --max-edge，再整块送模型描述
                     （推荐：等效"只看这一块"，最准）
  不给 --region      整图送模型，靠坐标提示让它聚焦该点
                     （省一次裁图，但模型可能看整幅画面）

用法：
  python tools/region_ask.py "C:\\path\\img.png" --region 330,200,200,200
  python tools/region_ask.py "C:\\path\\img.png" --region 330,200,200,200 --question "这里有手吗？几根手指？"
  python tools/region_ask.py "C:\\path\\img.png" --point 600,1250
  python tools/region_ask.py --image img.png --region ... --json   # 只输出 JSON

key：环境变量 MOSS_API_KEY；没有则读 notes/.pe_key。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import pathlib
import sys
import time
import urllib.request

DEFAULT_BASE = "https://maas.qianwenaiapi.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3-vl-plus"
KEY_FILE = pathlib.Path(r"E:\DSH-MOSS工作区\notes\.pe_key")

DEFAULT_QUESTION = (
    "这块区域里有什么？只描述肉眼可见的形状、颜色、数量与相对位置。"
    "如果这里有身体部位，请说清是哪个部位、朝向、数量。不推测画面外的东西。"
)


def get_key() -> str:
    k = (os.environ.get("MOSS_API_KEY") or "").strip()
    if k:
        return k
    if KEY_FILE.exists():
        return KEY_FILE.read_text(encoding="utf-8").strip()
    raise SystemExit("[x] 没有 MOSS_API_KEY，也没有 notes\\.pe_key")


def crop_region(im, region, max_edge):
    from PIL import Image
    x, y, w, h = region
    c = im.crop((x, y, x + w, y + h))
    k = max_edge / max(c.width, c.height)
    if k > 1:
        c = c.resize((round(c.width * k), round(c.height * k)), Image.LANCZOS)
    return c


def b64png(im) -> str:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def ask(base, model, key, image_b64, question, timeout=120):
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": image_b64}},
            ],
        }],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip(), time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", help="图片路径")
    ap.add_argument("--image", dest="image_opt")
    ap.add_argument("--region", help="x,y,w,h（左上原点像素）")
    ap.add_argument("--point", help="x,y —— 只给点，自动取 240×240 邻域")
    ap.add_argument("--question", default=DEFAULT_QUESTION)
    ap.add_argument("--max-edge", type=int, default=768)
    ap.add_argument("--model", default=os.environ.get("PE_MODEL", DEFAULT_MODEL))
    ap.add_argument("--base", default=os.environ.get("PE_BASE", DEFAULT_BASE))
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    a = ap.parse_args()

    path = a.image or a.image_opt
    if not path:
        raise SystemExit("[x] 需要图片路径")
    from PIL import Image
    im = Image.open(path).convert("RGB")
    W, H = im.size

    region = None
    if a.region:
        region = tuple(int(v) for v in a.region.split(","))
    elif a.point:
        px, py = (int(v) for v in a.point.split(","))
        region = (max(0, px - 120), max(0, py - 120), 240, 240)
        region = (region[0], region[1],
                  min(240, W - region[0]), min(240, H - region[1]))

    if region:
        x, y, w, h = region
        x = max(0, min(x, W - 1)); y = max(0, min(y, H - 1))
        w = max(8, min(w, W - x)); h = max(8, min(h, H - y))
        region = (x, y, w, h)
        crop = crop_region(im, region, a.max_edge)
        q = f"这是从一张 {W}×{H} 的图里裁出的区域（原图坐标 x={x}, y={y}, {w}×{h}）。\n{a.question}"
        img = crop
    else:
        q = f"整图尺寸 {W}×{H}。\n{a.question}"
        img = im
        if img.width > a.max_edge:
            k = a.max_edge / img.width
            img = img.resize((a.max_edge, round(img.height * k)), Image.LANCZOS)

    key = get_key()
    text, dt = ask(a.base, a.model, key, b64png(img), q)

    if a.json:
        print(json.dumps({"ok": True, "image": path, "region": region,
                          "question": a.question, "answer": text,
                          "seconds": round(dt, 1), "model": a.model},
                         ensure_ascii=False, indent=2))
    else:
        print(f"[info] {path}  区域={region}  模型={a.model}  {dt:.1f}s")
        print("-" * 70)
        print(text)


if __name__ == "__main__":
    main()
