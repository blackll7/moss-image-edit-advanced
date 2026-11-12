# SOP-2 示例 · 四星2 灯笼裤 → 冰衣（2026-11-12）

这是一次完整的 **SOP-2 原图调整流程**留档：在 SOP-1 复刻的基础上，
把**宽松灯笼裤改成冰衣**（冰 + 水的材质替换），并加一盏**冬季侧光**。
所有中间产物都在这里，可以逐步骤复现。

- **输入**：`00-reference/ref.png`（1216×1632）
- **输出**：`05-output/final_24step_ice.png`（24 步定稿）
- **本次调整**：`legs` 这一个部件（灯笼裤 → 冰衣），其余六个部件原样复刻
- **本次光源**：`bright winter sun from image-left at 25 degrees with strong light bouncing up from the white snow, the shadow side and the undersides of the arms and chin filled brightly, very bright overall, cool blue shadows on the snow`
- **流程文档**：`notes/SOP-2-原图调整流程.md`

---

## 冰衣是什么

来自原素材目录的 `00-prompt-sources.md`（素材来源方提供，未随本仓库分发）：

> 腰下一圈是真正的冰（约一指厚、有棱有断面）；冰是透明的、透光的，能透过它看见后面的腿；
> **白色只出现在断面的薄边、裂纹与气泡的边上**，冰本身没有白霜；边缘不规则、往下滴水；
> 裤脚收口那圈同样是冰，冰里冻着原来深紫蓝菱形的轮廓；**从这两圈冰往中间去，冰化成了水**；
> **她不是没穿，是那条裤子化开了** —— 灯笼裤的外沿轮廓还在，成了水的边界；
> 冰与水都是无色、偏青白；裤脚收口的深紫蓝菱形片与金边仍是硬的，在原来位置。

**三个最容易做错的地方**：

| 做错的倾向 | 正确写法 |
|---|---|
| 写成「裤子变成了冰」 | 写 **`no cloth at all`** —— 后者会让模型保留裤子先验、只是换材质 |
| 冰画成白霜/磨砂 | 强调 **`white only on the thin cut edges and bubble rims`** + 一串禁止词 |
| 忘了菱形片仍是硬的 | 单独一句 **`the original diamond appliques and their gold trim still hard and in place`** |

---

## 目录

```
00-reference/
  ref.png              参考图
  depth.png            原始深度图（四角 [152.7,153.8,243.1,247.0]）
  depth_black.png      ★ 背景刷纯黑（四角 [0,0,0,0]）—— 生成时用这张

01-parts/
  grounding.json       11 部位 2D 定位
  crops/               11 张部位裁片
  parts_all.json       ★ 11 部位反写（trunk + details[]）

02-grabtag/
  picked.json          ★ 选出的 7 个部件（按得分降序）
  s2_*.png             7 张 GrabTag 裁片
  masks/s2m_*.png      7 张对应掩码
  s2m_sleeve_r.png     副本（顶层，便于抄命令）

03-colormap/
  colormap.png         ★ 3 区色图（legs 洋红 / sash 纯蓝 / bodice 青）
  region_prompts.txt   ★ 3 条 region prompt（legs 这条已换成冰衣）
  region_prompts_raw.txt  自动生成的原始三条（对照用）

04-prompt/
  prompt_blocks.txt    ★ 主提示词，5 个 <|概念|> 块，1308 字符

05-output/
  final_24step_ice.png 24 步定稿
```

★ = 生成时实际用到的五个文件。

---

## 复现步骤

### 第 0 步：深度图背景刷纯黑

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\clean_depth.py' `
    --depth '00-reference\depth.png' --ref '00-reference\ref.png' `
    --out 'C:\MOSS-Deploy\ComfyUI\input\s2_depth_black.png'
```

判据：`[after] 四角均值` 全为 **0.0**。不刷的话，右下/右上那两块接近纯白（243/247）
会被读成「这一侧有很近的东西」，24 步下画面左右各多一条贯穿全高的装饰带。

### 第 1 步：切块反写

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\ground_regions.py' `
    --image '00-reference\ref.png' --outdir '01-parts\crops'

& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\describe_parts.py' `
    --image '00-reference\ref.png' `
    --grounding '01-parts\crops\grounding.json' `
    --out '01-parts\parts_all.json' --cropdir '01-parts\crops'
```

11 部位，其中 `legs` 17.10% / 8 条细节 1034 字（这是本次要改造的部件）。

### 第 2 步：选关键部件

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\pick_parts.py' `
    --parts '01-parts\parts_all.json' --ref '00-reference\ref.png' `
    --w 1216 --h 1632 --input-dir 'C:\MOSS-Deploy\ComfyUI\input' `
    --prefix s2 --max 8 --size 512 --min-area 2.5 `
    --out-selection '02-grabtag\picked.json'
```

选出 7 个：`legs 175.0 / drape 103.6 / sash_point 70.2 / shoes 58.4 / bodice 50.7 / sash 50.4 / sleeve_r 44.6`。
去重日志：`veil 与 bodice 重叠 90%`、`sleeve_l 与 sleeve_r 重叠 100%`。

### 第 3 步：色图 + region prompt

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\detail_colormap.py' `
    --parts '01-parts\parts_all.json' --picked '02-grabtag\picked.json' `
    --zones 'legs,sash,bodice' --input-dir 'C:\MOSS-Deploy\ComfyUI\input' `
    --prefix s2 --w 1216 --h 1632 `
    --out-colormap 'C:\MOSS-Deploy\ComfyUI\input\cm_s2.png' `
    --out-prompts '03-colormap\region_prompts_raw.txt'
```

得到 3 区（合计 25.93% 画布）与三条自动文案。**然后手动把第一条（`#ff00ff` / legs）
整段替换成冰衣描述** —— 这是 SOP-2 与 SOP-1 的唯一差别：

```
the #ff00ff area carries ice and water instead of cloth: a ring of real ice at the waist
about one finger thick with visible facets and broken edges, clear and see-through so the
legs read straight through it, white only on the thin cut edges and bubble rims, its rim
irregular and dripping a drop or two; a second ring of frozen ice at the ankle cuff with
the original deep violet-blue diamond appliques and their gold trim still hard and in place
on its outer face; between the two rings the fabric has melted into flowing water that
clings to the legs, bright moving highlights and tiny bubbles under the low winter sun,
thinnest where it fades into a single streak of reflection, transparent so the calves knees
and thighs show with skin colour and light intact; she is not bare, the original harem-pant
silhouette remains as the boundary of the water; ice and water are colourless cool blue-white,
with no rainbow and no oil slick and no plastic sheen and no cellophane crease and no white
frost and no rime and no sugar coating
```

（1033 字符，比自动预算 854 超了 179 —— 冰衣这类**材质替换**值得给超额预算，因为它不是「加细节」而是「换性质」。）

### 第 4 步：24 步生成

```powershell
$rArgs = @()
Get-Content '03-colormap\region_prompts.txt' -Encoding UTF8 |
  Where-Object { $_.Trim() } |
  ForEach-Object { $rArgs += @('--region-prompt', $_) }

& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'C:\MOSS-Deploy\moss_run.py' --port 8190 `
  --image 's2_legs.png:raw,s2_drape.png:raw,s2_sash_point.png:raw,s2_shoes.png:raw,s2_bodice.png:raw,s2_sash.png:raw,s2_sleeve_r.png:raw' `
  --ref-labels 'legs,drape,sash_point,shoes,bodice,sash,sleeve_r' `
  --ref-query-mask-por 's2m_legs.png,s2m_drape.png,s2m_sash_point.png,s2m_shoes.png,s2m_bodice.png,s2m_sash.png,s2m_sleeve_r.png' `
  --color-map 'cm_s2.png' --depth-map 's2_depth_black.png' `
  --control-strength 1.0 --color-strength 0.4 --depth-strength 1.0 --control-end 1.0 `
  --w 1216 --h 1632 --no-fast --steps 24 --cfg 3.5 --seed 9001 `
  --edit-format ai-toolkit --ref-no-pos 1 `
  --negative 'worst quality, bad anatomy, watermark, jpeg artifact' `
  --prompt-file '04-prompt\prompt_blocks.txt' @rArgs --prefix 's2_ice'
```

3.65 min。

---

## 光源提示词怎么放

`04-prompt/prompt_blocks.txt` 的第 1 块：

```
<|style_and_lighting|>Bright winter sun from image-left at 25 degrees, strong light bouncing up
from the white snow, the shadow side and the undersides of the arms and chin filled brightly,
very bright overall, cool blue shadows on the snow. The scene is a blank white snowfield, empty:
no scenery, no horizon, no buildings, nothing behind or around her. In that field stands a single
woman in a full-body costume, ...<|/style_and_lighting|>
```

**光源必须写在人物与衣物名词之前。** Qwen3.5 是从左到右单向因果注意力，
句序就是条件顺序 —— 把光写在人物后面，模型只会理解成「这幅画应该有个光源」，
而不会真的给人物染色。

实际效果：人物左上方受光、右半身转冷、脸部与手臂下方被雪地反光提亮、雪面拖出冷蓝阴影。

---

## 五处不能改的参数

| 参数 | 值 | 为什么不能改 |
|---|---|---|
| `--control-strength` | **1.0** | 同时缩放 color 与 depth。降到 0.5 时深度图被砍半，**直接画出 2–3 个人** |
| `--depth-strength` | **1.0** | 单独降它更糟：色图矩形边界会原样显形 |
| `--color-strength` | **0.4** | 调到 1.0 线条变硬、画风偏；调到 0 则失去「这块归你」的指派，冰衣退回布料 |
| `--ref-no-pos` | **1** | 让参考的布局不压过姿态控制 |
| `--image ... :raw` | 每张都带 | 不带 `:raw` 时参考走缩放通道，裁片会被 resize |

---

## 结果核对

按冰衣定义逐条对：

| 定义 | 结果 |
|---|---|
| 腰下一圈真冰、有棱有断面 | ✅ 腰侧那块透明冰，能看到棱边与厚度 |
| 冰透明、透见腿 | ✅ 冰环后面能看见布料与皮肤 |
| 白色只在断面薄边与气泡边 | ✅ 没有白霜，冰通体青白 |
| 冰缘参差、滴水 | ✅ 腰侧与裤脚都有水滴垂下 |
| 裤脚一圈冰冻着菱形片 | ✅ 底部冰环里冻着深紫蓝菱形 |
| 中间化成水贴腿 | ✅ 水膜透明、能看到大腿/膝盖/小腿轮廓 |
| 灯笼裤轮廓成了水的边界 | ✅ 外轮廓完整 |
| 菱形片与金边仍是硬的 | ✅ 位置与形状都对 |
| 光源从左侧 25°、雪面反光 | ✅ 左上受光、右侧转冷、雪地冷蓝阴影 |
| 单人、无装饰边框 | ✅ |

**没做到的**：鞋仍是圆头平底（参考是尖头高跟），这是全流程已知短板，与冰衣无关。

---

## 与 SOP-1 示例的差别

| 项 | SOP-1（复刻） | SOP-2（本次调整） |
|---|---|---|
| 改了哪一步 | 不改 | **第 3 步的 legs 文案**换成冰衣 |
| 主提示词第 4 块 | `Her legs are covered by <legs>.` | `Her legs ... are wrapped in ice and water rather than cloth — <legs>.` |
| 第 1 块 | 纯白背景 + 平光 | **冬季侧光 + 雪地** |
| 其余参数 | 完全相同 | 完全相同 |

也就是说：**SOP-2 = SOP-1 的产物 + 只改一个部件的文案 + 可选加一条风格/光源描述。** 参数一个都不用动。
