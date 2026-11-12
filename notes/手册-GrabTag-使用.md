# 手册 · GrabTag 使用

> 面向**操作**。想知道它内部怎么实现，看 `notes\机制-GrabTag-当前实现.md`。
> 最后核对：2026-11-11 20:45（代码改动已生效，服务 8190 存活）。

---

## 0 它解决什么问题

**提示词里你写了「深蓝腰带」，但写不出「每格菱形里嵌什么宝石、怎么连」——把它交给参考图那块裁片。**

等价地说：**参考图的哪一块，被用在生成图的哪个部位。**

**什么时候该用它**：

| 该用 | 不该用 |
|---|---|
| 纹样复杂、文本描不准（腰带菱格、裤腿菱阵、球面镂空） | 只要整体像参考（用整图单 A，更省事） |
| 需要「这一块」高保真，其余可以自由 | 想让参考决定布局（GrabTag 不保证布局） |
| 想要「不提就不引用」的可关闭性 | 想改变姿势（那是深度图+control 的事） |

**实测它比整图参考好在哪**：8 块裁片 + 反向指派，`vs参考 121.13` vs 整图参考 `127.80`，且**没有任何漂浮物**。

---

## 1 三步操作

### 第 ① 步：切裁片 + 生成掩码

**先决条件**：参考图必须已经做过 grounding（有 `work\parts_all.json`）。没有就跑 `tools\describe_parts.py` 先切块反写。

```powershell
$py  = 'C:\MOSS-Deploy\venv\Scripts\python.exe'
$env:PYTHONIOENCODING='utf-8'

# 切 8 块裁片（最长边 512，合计约 3147 tok）+ 8 张画布掩码
$script = @'
import json, os
import numpy as np
from PIL import Image
REF   = r"C:\MOSS-Deploy\ComfyUI\input\v2sop_ref.png"
PARTS = r"C:\MOSS-Deploy\work\parts_all.json"
CROPD = r"C:\MOSS-Deploy\work\gt_crops2"
MASKD = r"C:\MOSS-Deploy\ComfyUI\input"
W, H, MAXEDGE = 1216, 1632, 512
os.makedirs(CROPD, exist_ok=True)
im = Image.open(REF)
if im.mode == "RGBA":
    bg = Image.new("RGB", im.size, (255,255,255)); bg.paste(im, mask=im.split()[3]); im = bg
im = im.convert("RGB").resize((W,H), Image.LANCZOS)
ids = ["bodice","drape","hair","legs","sash","sash_point","sleeve_r","veil"]
by = {p["id"]: p for p in json.load(open(PARTS, encoding="utf-8"))}
for pid in ids:
    x0,y0,x1,y1 = by[pid]["bbox_px"]
    crop = im.crop((x0,y0,x1,y1)); w,h = crop.size
    k = MAXEDGE / max(w,h)
    if k < 1: crop = crop.resize((max(16,int(w*k)), max(16,int(h*k))), Image.LANCZOS)
    crop.save(os.path.join(CROPD, "gt2_%s.png" % pid))
    m = np.zeros((H,W), np.uint8)
    m[max(0,y0):min(H,y1), max(0,x0):min(W,x1)] = 255
    Image.fromarray(m,"L").convert("RGB").save(os.path.join(MASKD, "gtm2_%s.png" % pid))
'@
[System.IO.File]::WriteAllText("$env:TEMP\gt_cut.py", $script, [System.Text.UTF8Encoding]::new($false))
& $py "$env:TEMP\gt_cut.py"

# 裁片要放进 input（LoadImage 只认那里）
Get-ChildItem 'C:\MOSS-Deploy\work\gt_crops2\*.png' | ForEach-Object { Copy-Item $_.FullName 'C:\MOSS-Deploy\ComfyUI\input' -Force }
```

**三个必须记住的点**：

1. **掩码必须放 `ComfyUI\input\` 根目录**——子目录会报 `Invalid image file`
2. **文件名别撞旧文件**——input 里有 2026-11-08 的 `mask_bodice.png` 等旧文件，所以这里统一用 `gtm2_` 前缀
3. **掩码是画布尺寸**（1216×1632），不是裁片尺寸

### 第 ② 步：写提示词（反向指派）

**只写「部位 ← tag」，不要写「tag 是什么」。**

```
A single standing woman in a full-body costume, seen from the front, on a plain off-white background.

Her long braided hair is <hair>.
Her head and shoulders are veiled by <veil>.
Her upper chest and bust are covered by <bodice>.
Her right upper arm carries <sleeve_r>.
Her waist is wrapped in <sash>.
A short panel hangs down the front of her waist: <sash_point>.
A long panel hangs from her left hip down to the floor: <drape>.
Her legs, from waist to ankle, are <legs>.

For every named body region, use the garment from the reference given for that region and no other.
Do not draw any of these parts as separate objects beside the figure; each is worn on the body.
```

**为什么必须这样写**（这是本轮最大的发现）：

| 写法 | vs参考 | 漂浮物 |
|---|---|---|
| `Picture 1 is the jewelled chest piece: …`（正向） | 128.46 | **1** |
| `Her upper chest is covered by <bodice>.`（反向） | **122.61** | **0** |

**正向是属性陈述**（模型自己决定放哪，放不下就丢一边 → 漂浮物）；**反向是位置指派**（主语是画布部位，天然带空间约束）。

**最后两句不要省**：`For every named body region…` 和 `Do not draw any of these parts as separate objects…`。第一轮没有这两句时会出现一缕漂浮的辫子。

### 第 ③ 步：跑

```powershell
$ids = @('bodice','drape','hair','legs','sash','sash_point','sleeve_r','veil')
$img = ($ids | ForEach-Object { "gt2_$_.png:raw" }) -join ','
$msk = ($ids | ForEach-Object { "gtm2_$_.png" }) -join ','
$lbl = $ids -join ','
$pr  = Get-Content 'C:\MOSS-Deploy\work\prompt_gt_tags.txt' -Raw -Encoding UTF8

& $py 'C:\MOSS-Deploy\moss_run.py' --port 8190 `
  --image $img `
  --depth-map 'C:\MOSS-Deploy\ComfyUI\input\refself_depth.png' `
  --ref-query-mask-por $msk `
  --ref-labels $lbl `
  --control-strength 0.5 --control-end 0.5 `
  --w 1216 --h 1632 --steps 8 --cfg 1.0 --fast --seed 9001 `
  --edit-format ai-toolkit --ref-no-pos 1 `
  --negative 'worst quality, bad anatomy, watermark, jpeg artifact' `
  --prompt $pr --prefix 'gt'
```

**成功日志三行齐了才算跑对**：

```
[moss] ref-labels 'bodice,drape,…': 用自定义 tag 代替 Picture N 标记参考
[moss] references=8
[moss] done in ~1.2 min
```

---

## 2 参数速查

| 参数 | 本轮实测值 | 说明 |
|---|---|---|
| `--image` | 8 张 `:raw` | **必须 `:raw`**（`:pose`/`:style` 会缩到 384/512，细节全丢） |
| `--ref-query-mask-por` | 8 张 `gtm2_*.png` | **顺序必须与 `--image` 完全一致** |
| `--ref-labels` | `bodice,drape,…` | 名字不能含空格，下划线可以；数量必须等于参考数 |
| `--ref-no-pos` | `1` | 关掉参考的位置寻址（不复刻布局） |
| `--control-strength / end` | `0.5 / 0.5` | 挂深度图时用；纯 GrabTag 可不挂深度 |
| 步数 / cfg | 8 / 1.0 | `--fast` 档，约 70 s |
| 画布 | 1216×1632 | 与参考同尺寸 |

**token 预算**（最长边 512 时）：

| id | px | tok | id | px | tok |
|---|---|---|---|---|---|
| bodice | 300×312 | 342 | sash | 340×246 | 315 |
| drape | 208×512 | 416 | sash_point | 333×351 | 420 |
| hair | 268×347 | 336 | sleeve_r | 267×309 | 304 |
| legs | 344×512 | 672 | veil | 300×312 | 342 |

合计 **3147 tok**（单张整图参考是 7752）。**最长边 256 时合计 1540 tok，但 `vs参考` 会从 121.13 退化到 131.01**——裁片太小会丢细节。

---

## 3 检查清单（跑前跑后各一遍）

**跑前**

- [ ] 裁片都在 `ComfyUI\input\` 下，且能 `LoadImage` 到
- [ ] 掩码是**画布尺寸**，白区大致覆盖该部位在参考里的位置
- [ ] 掩码文件名用 `gtm2_` 之类前缀，**没撞 2026-11-08 的旧 `mask_*.png`**
- [ ] `--image` 的顺序、`--ref-query-mask-por` 的顺序、`--ref-labels` 的顺序**三者一致**
- [ ] 提示词里每个 `<tag>` 都对应一张真实存在的裁片名
- [ ] 常驻负向四项在

**跑后**

- [ ] 日志有 `[moss] ref-labels …` 与 `references=N`
- [ ] 画面里**没有漂浮的小物件**（辫子、饰片漂在旁边）
- [ ] 每个 `<tag>` 对应的部位，细节来自那块裁片
- [ ] **没写 `<tag>` 的部位，没有被带出来**（可关闭性）

---

## 4 常见问题

**Q：跑出来有「一缕漂浮的辫子」「一块漂浮的装饰」**
A：两种可能。① 提示词漏了 `Do not draw any of these parts as separate objects…` ② 用了正向写法。先检查这两条。

**Q：掩码报 `Invalid image file: xxx.png`**
A：掩码不在 `ComfyUI\input\` 根目录。LoadImage 只认 input 下的一级文件名。

**Q：`ref-labels 数量 N != 参考数 M` 告警**
A：`--ref-labels` 的逗号分隔项数与 `--image` 的张数不等，节点已回退到 `Picture N`。数一下。

**Q：颜色比参考艳很多**
A：已知问题。gt4 饱和度 24.33，整图参考是 16.34。**未解决**，可试在提示词末尾加一句收敛，或把裁片减到 3 块（只留 sash / legs / orb——文本最说不清的那三个）。

**Q：8 块以上怎么办**
A：`MOSSSetRefQueryMaskPor` 只定义到 `image_7`（**最多 8 张掩码**）。9 块以上要么合并相邻部位，要么分两轮。

**Q：会不会 OOM**
A：不会。`MOSS_NO_REF_PRECOMPUTE=1` 默认开启后不再预物化 KV。8 张 × 300 tok 级别很安全。旧说法「≥4 张必崩」是 MiE 提前压缩时代的结论，**已作废**。

**Q：能不能只给 2–3 块裁片**
A：可以，机制上完全支持——`--image` 少给几张、`--ref-labels` 少写几个、提示词里只写那几个 `<tag>` 就行。**这正是「可关闭性」的用法**，但**尚未实测**。

---

## 5 已知限制（别指望它）

| 限制 | 说明 |
|---|---|
| **不保证布局** | GrabTag 管「取哪块」，布局要靠深度图 / control |
| **裁片丢整体构图** | 8 块孤立裁片，模型不知道它们属于同一套衣服——拍得越碎，整体性越弱 |
| **掩码只有 8 张** | 见上 |
| **饱和度偏高** | 未解决 |
| **`--ref-no-pos` 是否该去掉未测** | 反向指派已建立位置对应，理论上裁片几何也可参与 |
| **一次只验过 seed 9001** | 多 seed 稳定性未测 |

---

## 6 实测数据（备查）

1216×1632 / 8 步 fast / cfg 1.0 / seed 9001 / control 0.5,0–0.5 / `--ref-no-pos 1`：

| 臂 | 参考 | vs参考 | 非白% | luma std | 锐度 | 饱和度 | 漂浮物 | 耗时 |
|---|---|---|---|---|---|---|---|---|
| saA | 整图 1 张 7752tok | 127.80 | 35.0 | 64.9 | 3.38 | 16.34 | 0 | 65 s |
| gt1 | 8 裁片 1540tok，**无 tag 引用** | 131.01 | 32.3 | 61.1 | 2.69 | 15.26 | 0 | 78 s |
| gt2 | 8 裁片 3147tok，**正向** | 128.46 | 36.3 | 61.3 | 2.93 | 18.35 | **1** | 66 s |
| gt3 | 8 裁片 3147tok，**反向 `<Picture N>`** | 122.61 | 42.5 | 62.6 | 3.41 | 26.43 | 0 | 58 s |
| **gt4** | 8 裁片 3147tok，**反向 `<tag>`** | **121.13** | 40.0 | **65.5** | 3.27 | 24.33 | **0** | 70 s |

**产物**：`C:\MOSS-Deploy\ComfyUI\output-moss\gt{1,2,3,4}_00001_.png`

---

## 7 相关

- 机制与代码行号：`notes\机制-GrabTag-当前实现.md`
- 三个定位系统的边界：`notes\机制-三个定位系统-GrabTag-layout-色图.md`
- `ref_tag` 文本写法（文本层仍然用）：`notes\2026-11-10-GrabTag-ref_tag-可见细节写法.md`
- 两步生成全流程：`notes\流程-GrabTag两步生成-锁定版.md`
- 重建前的旧资料：`notes\_history\GrabTag-重建前-20261111\`
