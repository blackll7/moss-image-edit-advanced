# SOP-1 示例 · 四星2 冰蓝舞娘（2026-11-12）

这是一次完整的 **SOP-1 原图复刻流程**留档：从一张参考图出发，经
「切块反写 → 选关键部件 → 分区色图 → 一条命令生成」，得到同款同姿势的成图。
所有中间产物都在这里，可以逐步骤复现，也可以直接抄参数。

- **输入**：`00-reference/ref.png`（1216×1632，参考图）
- **输出**：`05-output/final_24step_refnopos.png`（24 步定稿）
- **全流程耗时**：约 **4.5 min**（24 步生成 3.8 min + 前三步 0.7 min）
- **流程文档**：`notes/SOP-1-原图复刻流程.md`

---

## 目录

```
00-reference/
  ref.png              参考图（1216x1632）
  depth.png            Depth-Anything 提的原始深度图（四角 [152.7,153.8,243.1,247.0]）
  depth_black.png      ★ 背景刷纯黑后的深度图（四角 [0,0,0,0]）—— 生成时用这张

01-parts/
  grounding.json       11 个部位的多模态 2D 定位结果（像素框）
  crops/               11 张部位裁片（含 grounding.json）
  parts_all.json       ★ 11 个部位的反写结果：每部位 1 条 trunk + 若干 details

02-grabtag/
  picked.json          ★ 选出的 7 个关键部件（按得分降序）
  ex1_*.png            7 张 GrabTag 裁片
  ex1m_*.png           7 张对应掩码（黑底白区）

03-colormap/
  colormap.png         ★ 3 区色图（legs 洋红 / sash 纯蓝 / bodice 青），背景中灰 128
  region_prompts.txt   ★ 3 条 region prompt（每条对应一个色区）

04-prompt/
  prompt_blocks.txt    ★ 主提示词，5 个 <|概念|> 块，1156 字符

05-output/
  final_24step_refnopos.png   24 步定稿（带 --ref-no-pos 1）
  final_24step.png            24 步对照（不带 --ref-no-pos）
  reference_8step.png         8 步 fast 对照
```

★ = 生成时实际用到的四个文件。

---

## 复现步骤

### 第 0 步：深度图背景刷纯黑

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\clean_depth.py' `
    --depth '00-reference\depth.png' `
    --ref   '00-reference\ref.png' `
    --out   'C:\MOSS-Deploy\ComfyUI\input\ex1_depth_black.png'
```

判据是 `[after] 四角均值` 全为 **0.0**。不刷黑的话，右下/右上那两块接近纯白（243/247）
会被读成「这里有一块很近的东西」，24 步生成时画面**左右各多一条贯穿全高的装饰带**。

### 第 1 步：切块反写 + 主干/细节分离

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\ground_regions.py' `
    --image '00-reference\ref.png' --outdir '01-parts\crops'

& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\describe_parts.py' `
    --image '00-reference\ref.png' `
    --grounding '01-parts\crops\grounding.json' `
    --out '01-parts\parts_all.json' `
    --cropdir '01-parts\crops'
```

产出 `trunk`（形状/主色/材质，汇入主提示词）与 `details[]`（纹样/数量/位置，留给 region prompt）。

### 第 2 步：选关键部件 → 裁片 + 掩码

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\pick_parts.py' `
    --parts '01-parts\parts_all.json' `
    --ref '00-reference\ref.png' `
    --w 1216 --h 1632 `
    --input-dir 'C:\MOSS-Deploy\ComfyUI\input' `
    --prefix ex1 --max 8 --size 512 --min-area 2.5 `
    --out-selection '02-grabtag\picked.json'
```

脚本按「面积 × 10 + 位置易漂 +5 + 需配对 +3 + 细节条数 × 0.5」打分，
并对 grounding 同框的部件做 IoU > 0.8 去重。本示例选出 7 个：

| 部件 | 面积占比 | 得分 |
|---|---|---|
| legs | 17.10% | 175.0 |
| drape | 9.95% | 106.2 |
| sash_point | 5.89% | 70.4 |
| sash | 5.05% | 51.1 |
| shoes | 5.44% | 29.7 |
| bodice | 4.64% | 51.2 |
| sleeve_r | 4.16% | 44.6 |

`veil` 因与 `bodice` 重叠 92% 被去重，`sleeve_l` 因与 `sleeve_r` 重叠 100% 被去重，
`hair` / `orb` 在黑名单里。

### 第 3 步：细节 → 分区色图 + region prompt

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\detail_colormap.py' `
    --parts '01-parts\parts_all.json' `
    --picked '02-grabtag\picked.json' `
    --zones 'legs,sash,bodice' `
    --input-dir 'C:\MOSS-Deploy\ComfyUI\input' `
    --prefix ex1 --w 1216 --h 1632 `
    --out-colormap 'C:\MOSS-Deploy\ComfyUI\input\cm_ex1.png' `
    --out-prompts '03-colormap\region_prompts.txt'
```

三条硬规则：**色区形状贴合**（取掩码，不画矩形）、**≤3 个色区**、**背景中灰 128**。
文案按面积配预算（`chars-per-pct 50`），本示例 legs 8/8 条 945 字、sash 2/6 条 246 字、bodice 1/7 条 159 字。

### 第 4 步：一条命令生成

```powershell
$rArgs = @()
Get-Content '03-colormap\region_prompts.txt' -Encoding UTF8 |
  Where-Object { $_.Trim() } |
  ForEach-Object { $rArgs += @('--region-prompt', $_) }

& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'C:\MOSS-Deploy\moss_run.py' --port 8190 `
  --image 'ex1_legs.png:raw,ex1_drape.png:raw,ex1_sash_point.png:raw,ex1_sash.png:raw,ex1_shoes.png:raw,ex1_bodice.png:raw,ex1_sleeve_r.png:raw' `
  --ref-labels 'legs,drape,sash_point,sash,shoes,bodice,sleeve_r' `
  --ref-query-mask-por 'ex1m_legs.png,ex1m_drape.png,ex1m_sash_point.png,ex1m_sash.png,ex1m_shoes.png,ex1m_bodice.png,ex1m_sleeve_r.png' `
  --color-map 'cm_ex1.png' `
  --depth-map 'ex1_depth_black.png' `
  --control-strength 1.0 --color-strength 0.4 --depth-strength 1.0 --control-end 1.0 `
  --w 1216 --h 1632 --no-fast --steps 24 --cfg 3.5 --seed 9001 `
  --edit-format ai-toolkit --ref-no-pos 1 `
  --negative 'worst quality, bad anatomy, watermark, jpeg artifact' `
  --prompt-file '04-prompt\prompt_blocks.txt' @rArgs --prefix 'ex1'
```

> 裁片、掩码、色图、深度图都必须**先拷到 `C:\MOSS-Deploy\ComfyUI\input\`** 再用短名调用；
> ComfyUI 的 LoadImage 只扫自己的 input 目录，传绝对路径会 `Invalid image file`。

---

## 五处不能改的参数

| 参数 | 值 | 为什么不能改 |
|---|---|---|
| `--control-strength` | **1.0** | 它是 color 与 depth 的总缩放。降到 0.5 时深度图被砍半，分区暗示变成主导，**直接画出 2–3 个人**（实测非白从 41% 涨到 83.6%） |
| `--depth-strength` | **1.0** | 单独降它更糟：色图矩形边界会原样显形（非白 73.7%、锐度 15.75） |
| `--color-strength` | **0.4** | 调到 1.0 会让线条变硬、画风偏；调到 0 则失去「这块归你」的指派 |
| `--ref-no-pos` | **1** | 让参考的布局不压过姿态控制 |
| `--image ... :raw` | 每张都带 | 不带 `:raw` 时参考走缩放通道，裁片会被 resize |

---

## 三版成品对比

| 版本 | 说明 | vs参考 | 非白% | 锐度 |
|---|---|---|---|---|
| `reference_8step.png` | 8 步 fast，画风平、线条简单 | 126.04 | 35.2 | 7.09 |
| `final_24step.png` | 24 步，**不带** `--ref-no-pos` | 133.34 | 33.6 | 8.98 |
| `final_24step_refnopos.png` | 24 步，**带** `--ref-no-pos 1`（定稿） | — | — | — |

24 步 + cfg 3.5 的画风明显更厚：胸衣宝石有高光层次、灯笼裤的渐变更细、腰侧银球有体积。
`vs参考` 偏高是因为参考本身是 3D 渲染（更平、更均匀），而不是复刻变差。

---

## 已知短板

- **脚部**：参考是尖头高跟，生成一律圆头平底，分区 `vs参考` 144.5–156.1，远高于其他部位（106–123）
- **`orb`**：参考里是「大球 + 小球 + 米色流苏」，tag 只描述了一个球
- **掩码是近矩形**：参考图前景占 75.6%，`bbox ∩ 非背景` 仍接近矩形，靠 `strength 1.0` 压住多主体
