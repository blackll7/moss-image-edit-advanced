#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对 grounding 裁出来的每块图做详细反写，产出 A+B 链的 --region-prompt 草稿。

前置：先跑 `tools/ground_regions.py` 得到 `grounding.json` 与各块 png。

用法：
    python tools/describe_crops.py --indir C:\MOSS-Deploy\work\grounded \
        --out C:\MOSS-Deploy\work\_region_detailed.txt

输出格式一行一段：`the <hex> area is <描述>`，hex 从 grounding.json 的 id 对 palette 查。
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

# 每块问的重点不同：问对了模型才会往细处说
FOCUS = {
    "hair":      "头发：编成几股、从哪到哪、发饰由什么组成（冠、链、宝石的形状与数量）",
    "veil":      "头纱：材质透不透、边缘形状、上面的金链与珠子怎么排、覆盖范围",
    "sleeve_r":  "袖子：形状（泡泡/喇叭/宽袖）、长度到哪、袖口的金属件、袖面的纹样（几个、怎么排）",
    "sleeve_l":  "袖子：形状（泡泡/喇叭/宽袖）、长度到哪、袖口的金属件、袖面的纹样（几个、怎么排）",
    "bodice":    "上衣：覆盖范围的上边界与下边界、外框金属件的形状、中央那颗是什么、镶嵌的宝石有几颗怎么排、拼贴的分块与配色",
    "sash":      "腰带：宽度、绕几圈、上面菱形格怎么排、嵌了几颗什么颜色的宝石、下沿挂的链条与垂珠",
    "orb":       "腰间挂饰：球体的材质与镂空花纹、下方坠着什么颜色的流苏、与腰带怎么连",
    "drape":     "垂布：从哪挂到哪、边缘的波形怎么裁、每个波谷上嵌了什么、还有哪些金属花饰与吊坠",
    "sash_point":"腰前垂带：形状、长度、上面的纹样与金属件",
    "legs":      "裤子：整体廓形（哪最宽、哪里收）、裤子上的菱形纹样（几行几列、每个菱形里有几层、中心是什么）、菱形之间的金线怎么连、裤脚的结构",
    "shoes":     "鞋：尖头还是圆头、跟多高、鞋面怎么分区、镶了什么、脚踝上缠的是什么",
}


def load_key():
    for line in open(ENV, encoding="utf-8"):
        if line.startswith("QIANWEN_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("QIANWEN_API_KEY 不在 %s" % ENV)


def call(key, b64, prompt, max_tokens=800):
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
    with urllib.request.urlopen(req, timeout=150) as r:
        j = json.loads(r.read().decode())
    return j["choices"][0]["message"]["content"].strip()


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--indir", required=True)
    ap.add_argument("--palette", default=r"C:\MOSS-Deploy\work\palette11.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    key = load_key()
    items = json.load(open(os.path.join(args.indir, "grounding.json"), encoding="utf-8"))
    pal = json.load(open(args.palette, encoding="utf-8"))
    if isinstance(pal, dict) and "regions" in pal:
        pal = pal["regions"]
    hex_by_id = {p.get("id"): p.get("hex") or p.get("color") for p in pal}

    only = [s.strip() for s in args.only.split(",") if s.strip()]
    if only:
        items = [it for it in items if it["id"] in only]

    lines = []
    for it in items:
        rid = it["id"]
        path = it["crop"]
        if not os.path.exists(path):
            print("  %-10s 缺裁图，跳过" % rid)
            continue
        focus = FOCUS.get(rid, "")
        prompt = (
            "这是从一张全身角色设定图里裁出来的局部。请只描述这一块里看得见的东西，"
            "重点观察：%s。\n"
            "要求：写形状、边缘、材质光泽、颜色（含明暗）、纹样的数量与排列、金属与宝石的镶嵌方式；"
            "只写看得见的，不推测；不分段；200 字以内。" % focus)
        try:
            desc = call(key, base64.b64encode(open(path, "rb").read()).decode(), prompt)
        except Exception as e:
            print("  %-10s FAIL %s" % (rid, e))
            continue
        desc = " ".join(desc.split())
        lines.append("the %s area is %s" % (hex_by_id.get(rid, rid), desc))
        print("  %-10s %3d 字" % (rid, len(desc)))

    # 按 palette 顺序输出，保证与 A 链 tag 顺序一致
    order = [p.get("id") for p in pal]
    lines.sort(key=lambda l: next((i for i, o in enumerate(order)
                                   if hex_by_id.get(o) and hex_by_id[o] in l), 999))
    open(args.out, "w", encoding="utf-8").write("\n".join(lines))
    print("\n写出 %s（%d 段，%d 字符）" % (args.out, len(lines), sum(len(l) for l in lines)))


if __name__ == "__main__":
    main()
