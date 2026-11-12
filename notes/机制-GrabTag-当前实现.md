# 机制 · GrabTag 当前实现（2026-11-11 重建）

> **本文取代 `notes\机制-MOSS-GrabTag-当前实现.md`（旧版把 GrabTag 落在 `--color-map`，方向错了，已作废）。**
> 本文只写**在本机代码上验证过的事实**，每条带 `文件:行号`。行号漂了就重新核对。
> 最后核对：2026-11-11 20:3x，`moss_run.py` 1138 行 / `nodes_moss_image.py` 176 行 / `moss_ref_mask.py` 93 行。
> 实测凭证：`gt1` / `gt2` / `gt3` / `gt4` 四臂（见 §6）。

---

## 0 一句话

**把参考图切成 N 块裁片，每块挂一个 tag 名；提示词提到某个 tag 才引用那块裁片，且只在画布上它自己那一区域生效。**

拆成三条，缺一条就不算做到：

| # | 要求 | 由什么实现 |
|---|---|---|
| ① | tag → 参考裁片 | `--ref-labels`（视觉 token 前缀换成自定义名） |
| ② | tag → 画布区域 | `--ref-query-mask-por`（每块裁片一张画布掩码） |
| ③ | 不提就不引用 | 提示词不写 `<tag>` → 那块裁片不进上下文 |

---

## 1 旧实现错在哪（一句话）

**旧版把 GrabTag 的落点放在 `--color-map`（生成图侧的区域 ID 图）上，等于在问「画在哪儿」，而 GrabTag 要回答的是「从参考的哪一块取像素」。**

两个坐标系被混为一谈：

| | 坐标系 | 谁用 |
|---|---|---|
| **参考图分区** | 参考图的 (x, y) | **GrabTag**（本文件） |
| **生成图分区** | 画布的 (x, y) | layout / 色图 / `paint_prompt` |

用户 2026-11-11 的一句话点破了它：**「grabtag 的标注在参考图上，layout 和色图 prompt 标注在生成图上」**。

---

## 2 三条通道，GrabTag 只占参考通道

| | 文本通道 | 像素通道 | **参考通道** |
|---|---|---|---|
| 载体 | 一段英文 prompt | 与画布同尺寸的 PNG | 参考裁片（`--image`） |
| 代码入口 | `args.prompt` | `--depth-map` / `--color-map` / `--region-edit` | `TextEncodeMOSSImageEdit` 的 `images.image_i` |
| 能表达 | 材质、颜色、纹样、构件名 | 空间的区域划分 | **从参考取哪一块外观** |
| 不能表达 | 精确边界、精确数量 | 任何语义 | 精确落点（要靠掩码）、精确数量 |
| **GrabTag 用不用** | 只用来「提名字」 | **不用** | **全部用它** |

**三者分工**（用户 2026-11-11 定义）：

```
参考图定位 → GrabTag（--ref-query-mask-por + --ref-labels）
色图定位   → layout / 纹样焦点框（--color-map）
生成内容   → paint_prompt / 文本描述
```

---

## 3 数据流（重建后）

```
① 切裁片（按人体部位，最长边 ≤512）
   work\gt_crops2\gt2_<id>.png        ← --image gt2_<id>.png:raw
   + 每块一张画布尺寸掩码
   ComfyUI\input\gtm2_<id>.png        ← --ref-query-mask-por（顺序必须与 --image 一致）

② tag 命名
   --ref-labels bodice,drape,hair,legs,sash,sash_point,sleeve_r,veil
   └─ 节点把视觉 token 前缀从 "Picture N:" 换成 "<tag>:"

③ 提示词反向指派（见 §5，这是效果关键）
   Her waist is wrapped in <sash>.
   Her legs, from waist to ankle, are <legs>.

④ 建图
   moss_run.py --image … --ref-query-mask-por … --ref-labels …
```

---

## 4 三个组件的代码事实

### 4.1 `MOSSSetRefQueryMaskPor`（`custom_nodes\comfyui-moss-ref-bias\moss_ref_mask.py:41-93`）

节点自述原文：

> **Scope each reference separately: mask i is the canvas region allowed to read reference i. White = may read that reference, black = blocked for those image tokens.**
> **`so one crop can be bound to one body part`**

- `image_0` 必需 + `image_1..image_7` 可选 ⇒ **最多 8 张掩码**
- 掩码尺寸必须 = 画布尺寸
- `:83-86` 把 N 张掩码横拼成 `(1, H, W*n_ref)` 走已验证的 `ref_query_mask` 通道

### 4.2 掩码在注意力里怎么生效（`comfy\ldm\moss_image\model.py:419-442`）

```python
if ref_query_mask is not None and not _por_mode:
    # per-image-token allow-list over the reference keys: -inf blocks the reference for
    # those image tokens only, so a reference can be scoped to one panel of the canvas.
    if rq.ndim == 3 and tuple(rq.shape[-2:]) != (H, W):
        rq = interpolate(..., size=(H, W), ...)
    allow = (rq > 0.5)[:, :, None]
    region[:, 0, :H * W, nq:] = ...masked_fill(~allow, float("-inf"))
```

**读法**：`region` 是 attention logits，`[:, :, :H*W, nq:]` 这一段是「图像 token 对参考 token」的权重。白区保留、黑区填 `-inf`（softmax 后为 0）。**所以它是逐图像 token 的开关，不是逐参考 token 的裁剪。**

### 4.3 自定义 tag 标记（`comfy_extras\nodes_moss_image.py:141-152`，2026-11-11 新增）

```python
_labels = [s.strip() for s in str(ref_labels or "").replace(";", ",").split(",") if s.strip()]
if _labels and len(_labels) == len(vl):
    marks = ["%s:" % _labels[i] for i in range(len(vl))]
    print("[moss-ref-label] 用自定义标签标记 %d 个参考: %s" % (len(vl), ", ".join(_labels)))
else:
    marks = ["Picture %d:" % (i + 1) for i in range(len(vl))]
prompt = "".join(m + " <|vision_start|><|image_pad|><|vision_end|>" for m in marks) + prompt
```

**关键**：标记插在 `<|vision_start|>` **前面**，所以模型看到的是「视觉 token 前挂着名字 `<sash>`」，而不是普通文本。
数量不匹配会回退到 `Picture N` 并打印告警。

**参数**：`--ref-labels`（`moss_run.py:970` 定义、`:441-445` 转发进 `base_enc`）。名字不能含空格，下划线可以。

---

## 5 提示词写法：反向指派 > 正向描述

**这是实测出来的最大增益点。**

| 写法 | 例子 | 模型的理解 | 后果 |
|---|---|---|---|
| **正向（差）** | `Picture 1 is the jewelled chest piece: a sheer light-blue halter…` | 「这张图是什么」→ 裁片是**要画的对象** | 容易被当成独立物体画在人物旁边 |
| **反向（好）** | `Her upper chest and bust are covered by <bodice>.` | 「这个位置用什么」→ 裁片是**这处的素材** | 天然带空间约束，不会跑到别处 |

**推荐模板**（实测版本，696 字符）：

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

**最后两句不要省**：第一句是第一轮没有的（当时出现了一缕漂浮的辫子），加上后连通域从 267 降到 153。

---

## 6 实测数据（1216×1632 / 8 步 fast / cfg 1.0 / seed 9001 / control 0.5,0–0.5 / `--ref-no-pos 1`）

| 臂 | 参考 | vs参考 | 非白% | luma std | 锐度 | 饱和度 | 人物外大块 | 耗时 |
|---|---|---|---|---|---|---|---|---|
| saA | 整图 1 张（7752 tok） | 127.80 | 35.0 | 64.9 | 3.38 | 16.34 | 0 | 65 s |
| gt1 | 8 裁片 1540 tok，**无 tag 引用** | 131.01 | 32.3 | 61.1 | 2.69 | 15.26 | 0 | 78 s |
| gt2 | 8 裁片 3147 tok，**正向 `<Picture N>`** | 128.46 | 36.3 | 61.3 | 2.93 | 18.35 | **1** | 66 s |
| gt3 | 8 裁片 3147 tok，**反向 `<Picture N>`** | 122.61 | 42.5 | 62.6 | 3.41 | 26.43 | 0 | 58 s |
| **gt4** | 8 裁片 3147 tok，**反向 `<tag>`** | **121.13** | 40.0 | **65.5** | 3.27 | 24.33 | **0** | 70 s |

**三个结论**：

1. **必须引用**：gt1 的 prompt 里没有任何标记引用，1540 tok 的裁片等于白挂（131.01，比整图还差）。
2. **必须反向**：gt2 → gt3 同裁片同参数，只换句式，`vs参考` 降 5.85、锐度升 0.48、漂浮物从 1 降到 0。
3. **自定义 tag 略优于 `Picture N`**：gt3 → gt4 降 1.48、luma std 升 2.9、饱和度降 2.1。`gt3 vs gt4 = 10.19`（不是严格等价，推测 `<tag>` 单 token 且语义直指部位，绑定更紧）。

**裁片预算**（`work\parts_all.json` 的 `bbox_px`，最长边 512）：

| id | 裁片 px | token | id | 裁片 px | token |
|---|---|---|---|---|---|
| bodice | 300×312 | 342 | sash | 340×246 | 315 |
| drape | 208×512 | 416 | sash_point | 333×351 | 420 |
| hair | 268×347 | 336 | sleeve_r | 267×309 | 304 |
| legs | 344×512 | 672 | veil | 300×312 | 342 |

合计 **3147 tok**（单张整图 7752）。最长边 256 时合计 1540 tok。

---

## 7 完整命令

```powershell
$ids = @('bodice','drape','hair','legs','sash','sash_point','sleeve_r','veil')
$img = ($ids | ForEach-Object { "gt2_$_.png:raw" }) -join ','
$msk = ($ids | ForEach-Object { "gtm2_$_.png" }) -join ','
$lbl = $ids -join ','

C:\MOSS-Deploy\venv\Scripts\python.exe C:\MOSS-Deploy\moss_run.py --port 8190 `
  --image $img `
  --depth-map 'C:\MOSS-Deploy\ComfyUI\input\refself_depth.png' `
  --ref-query-mask-por $msk `
  --ref-labels $lbl `
  --control-strength 0.5 --control-end 0.5 `
  --w 1216 --h 1632 --steps 8 --cfg 1.0 --fast --seed 9001 `
  --edit-format ai-toolkit --ref-no-pos 1 `
  --negative 'worst quality, bad anatomy, watermark, jpeg artifact' `
  --prompt (Get-Content 'C:\MOSS-Deploy\work\prompt_gt_tags.txt' -Raw) `
  --prefix 'gt'
```

**成功标志**（日志三行齐了才算）：

```
[moss] ref-labels 'bodice,drape,…': 用自定义 tag 代替 Picture N 标记参考
[moss] references=8
[moss] done in ~1.2 min
```

---

## 8 已知限制与陷阱

1. **掩码最多 8 张**（`moss_ref_mask.py` 只定义到 `image_7`）。9 块以上要合并或分批。
2. **掩码必须放 `C:\MOSS-Deploy\ComfyUI\input\` 根目录**，子目录会报 `Invalid image file: xxx.png`，因为 `LoadImage` 只认 input 下的相对名。
3. **掩码文件名别撞旧文件**：input 里已有 2026-11-08 的 `mask_bodice/sash/sleeve_r.png`（不同尺寸），同名会被静默用错。用 `gtm_` / `gtm2_` 之类前缀。
4. **掩码顺序必须与 `--image` 完全一致**，节点按 `sorted(images)` 取，而 `moss_run.py` 按 `--image` 顺序编号 → 文件名排序与传入顺序不同就会错位。
5. **参考张数**：`MOSS_NO_REF_PRECOMPUTE=1`（默认开）之后不再预物化 KV，8 张 × 300 tok 级别不会 OOM。旧文档「≥4 张必崩」是 MiE 提前压缩时代的结论，**已作废**。
6. **饱和度偏高**：gt4 的 24.33 仍高于整图参考的 16.34，画面偏艳（粉、紫、亮蓝被推高）。未解决。
7. **裁片丢整体构图**：1540 tok（256 边）时 `vs参考` 131.01，比整图 127.80 差——**裁片各自独立，模型不知道它们属于同一套衣服**。要么放大裁片（3147 tok 时降到 121.13），要么走混合模式（整图 + 少量裁片，**未实测**）。
8. **`--ref-no-pos 1` 目前带上了**。去掉是否会更好**未测**（反向指派已经靠文本建立了位置对应，理论上可以让裁片几何也参与）。

---

## 9 待验证 / 未解

| # | 问题 | 建议做法 |
|---|---|---|
| 1 | 饱和度 24.33 偏高 | prompt 末尾加收敛句；或裁片减到 3 块 |
| 2 | 混合模式（整图 + 2–3 裁片）未跑 | `--image 整图:raw,gt_sash:raw,gt_legs:raw` + 三张掩码 |
| 3 | 去掉 `--ref-no-pos` 是否更好 | 单变量对照 |
| 4 | 按部位比对（而非整图 vs参考）的评估脚本 | 裁出 tag 区域与裁片比对 |
| 5 | 「可关闭性」未单测 | 只写 4 个 `<tag>`，看另外 4 块是否真不引用 |

---

## 10 出处

- 掩码语义与实现：`C:\MOSS-Deploy\ComfyUI\custom_nodes\comfyui-moss-ref-bias\moss_ref_mask.py:41-93`
- 注意力落点：`C:\MOSS-Deploy\ComfyUI\comfy\ldm\moss_image\model.py:419-442`
- 视觉标记：`C:\MOSS-Deploy\ComfyUI\comfy_extras\nodes_moss_image.py:141-152`
- 调用侧：`C:\MOSS-Deploy\moss_run.py:441-445`（转发）、`:970`（参数定义）
- 裁片与掩码生成：`E:\DSH-MOSS工作区\tools\describe_parts.py`（部位切块与反写）、`work\parts_all.json`
- 实测产物：`C:\MOSS-Deploy\ComfyUI\output-moss\gt{1,2,3,4}_00001_.png`
- 旧实现（作废，仅存档）：`notes\机制-MOSS-GrabTag-当前实现.md`
