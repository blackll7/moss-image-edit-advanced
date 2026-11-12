# SOP-3 示例：站姿 → standing split（24 步档）

> 这套示例演示 **SOP-3 更换姿势流程**的完整四步，第 3 步用的是 **24 步正式档**（`--no-fast --steps 24 --cfg 3.5`）。
> 参考图与第 A 步的取料（`parts_all.json` / `picked9.json` / 裁片 / 掩码）**直接复用案例一**，不重跑。

## 基本信息

| 项 | 值 |
|---|---|
| 参考图 | `C:\MOSS-Deploy\ComfyUI\input\v2sop_ref.png`（四星2 冰蓝舞娘，原姿势：正面站立） |
| 新姿势 | `full_sexy_P008_front_depth.webp`（900×1200，左腿高举过头、左手扶小腿、右臂侧伸、右腿单腿站立） |
| 画布 | 1216×1632 |
| 链路 | A 链（`--edit-format ai-toolkit`），8 裁片 + `<tag>` + 色图 + 深度图 |
| 第 1 步 | 8 步 fast，`--control-strength 0.6 --control-end 0.6` |
| 第 3 步 | **24 步**，`--no-fast --steps 24 --cfg 3.5`，`--control-strength 0.9 --control-start 0.0 --control-end 1.0`，`--image-strength 0.5` |
| seed | 9001 |

## 目录

```
00-depth\        第 0 步：新姿势深度图刷黑
  ex3_black.png      喂 --depth-map（原深度值，背景全 0）
  ex3_mask.png       白=人物（检查用）

01-transition\   第 1 步：纯 T2I 过渡图
  ex3_t_00001_.png   只传 --depth-map，control 0.6 / end 0.6

02-colormap\     第 2 步：从过渡图提色图 + 提深度图 + 画布掩码
  ex3_cm.png             10 区色图（中灰底）
  ex3_depth2_raw.png     Depth-Anything-V2-Small 原始输出
  ex3_depth2.png         刷黑后的第二深度图（喂 --depth-map）
  cvm_*.png              8 张画布坐标掩码（喂 --ref-query-mask-por）

03-prompt\       提示词
  prompt_trans.txt           第 1 步过渡图用
  prompt_main_blocks_v3.txt  第 3 步五块主 prompt（tag + 位置 + 白底声明）
  rp_s4_v2.txt               第 3 步 region prompt（8 条，前形状后细节）

04-output\       第 3 步各档产物
```

## 四步命令

### 第 0 步：深度图刷黑

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\depth_to_mask.py' `
    'full_sexy_P008_front_depth.webp' `
    'C:\MOSS-Deploy\ComfyUI\input\ex3' `
    --width 1216 --height 1632 --feather 2
```

实测：四角原始 `[114, 101, 175, 194]`、Otsu `118.0`、地面过滤（`y>=1403`）把 `448797→275652` 像素、人物 **11.79%**、bbox `x 211-1006 y 84-1498`（两只脚都完整）、四角刷后 `[0,0,0,0]`。

### 第 1 步：过渡图

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'C:\MOSS-Deploy\moss_run.py' --port 8190 `
  --depth-map 'ex3_black.png' `
  --control-strength 0.6 --control-end 0.6 `
  --w 1216 --h 1632 --fast --seed 9001 `
  --negative 'worst quality, bad anatomy, watermark, jpeg artifact, tight fit, skinny pants, leggings, extra legs, extra limbs, extra feet' `
  --prompt-file 'prompt_trans.txt' --prefix 'ex3_t'
```

实测 0.34 min。关键是 prompt 里那句显式形变：

> Because her left leg is raised straight up, the left trouser leg is pulled upward and its fabric bunches into thick heavy folds around the hip and upper thigh, while the standing right leg's fabric hangs down under its own weight and piles into folds just above the ankle cuff

### 第 2 步：提色图 + 提深度图 + 画布掩码

**2.1 色图**：按 HSV 分区，10 个区。**过渡图的色相直方图是必查的**（S>0.35、0.15<V<0.75）：

| 色相区间 | 像素数 | 对应 |
|---|---|---|
| 350–360 | 134713 | 红披风 |
| 0–10 / 10–20 | 4822 / 19397 | 红披风与橙腰带混在这里 |
| 140–150 / 150–160 | 13024 / 142254 | **绿裤** |
| 160–170 | 1631 | 青头纱 |
| 200–230 | 6285 + 13147 | 蓝袖 |
| 250–280 | 521 + 7924 + 8553 | 紫胸衣 |
| 40–50 | 4501 | 棕（前片） |

**四个坑**：

| 坑 | 现象 | 修法 |
|---|---|---|
| 头纱与绿裤色相接近 | 切在 168 会把头纱染成洋红 | `leggings` 140–165、`veil` 165–195 |
| **`sash_point` 被 `drape` 覆盖** | 前片 H≈10 同时落在 drape 的 0–16 区间，drape 后画就全盖掉（0.62% → **0.00%**） | **`sash_point` 必须最后画**，并加位置框 `[655:825, 425:545]` |
| `shoes` 与披风亮部撞色 | H=342 落在 drape 的 340–15，V 也高 | **只能用位置框** `[20:250,180:310]` + `[1420:1550,420:555]`，否则红色铺满披风褶皱（7.14% → 0.40%） |
| `veil` 太透明 | 只抓到边缘 | 主体交给主 prompt，色区只做弱提示 |

实测 10 区：`leggings 8.18%` / `drape 8.96%` / `veil 0.79%` / `sash_point 0.62%` / `bodice 0.85%` / `sleeve_r 0.61%` / `sash 0.77%` / `sleeve_l 0.71%` / `shoes 0.40%` / `orb 0.14%`，合计 22.03%、中灰底 77.97%。

**2.2 第二深度图**：

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'C:\MOSS-Deploy\work\depth_from_image.py' `
    'C:\MOSS-Deploy\ComfyUI\output-moss\ex3_t_00001_.png' `
    'C:\MOSS-Deploy\ComfyUI\input\ex3_depth2_raw.png'
```

然后用 `a[a<58]=0` + 左右各 40 列 + `a[1500:,:]=0` 刷黑：原始四角 `[81,53,210,247]` → 刷后 `[0,0,0,0]`，非零 45.13%。

**2.3 画布掩码**（`cvm_*.png`）：从 `ex3_cm.png` 按 hex 阈值 12 提取，面积 <1% 膨胀 3px、其余 9px。

| 部位 | 原始 | 膨胀 | 结果 |
|---|---|---|---|
| legs | 8.18% | 9px | 10.05% |
| drape | 8.96% | 9px | 10.38% |
| bodice | 0.85% | 3px | 0.90% |
| sleeve_r | 0.61% | 3px | 0.71% |
| sash | 0.77% | 3px | 1.11% |
| sash_point | 0.62% | 3px | 0.70% |
| shoes | 0.40% | 3px | 0.45% |
| orb | 0.14% | 3px | 0.53% |

### 第 3 步：24 步精修

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'C:\MOSS-Deploy\moss_run.py' --port 8190 `
  --image 'e9_legs.png:raw, e9_drape.png:raw, e9_bodice.png:raw, e9_sleeve_r.png:raw, e9_orb.png:raw, e9_sash.png:raw, e9_sash_point.png:raw, e9_shoes.png:raw' `
  --ref-labels 'legs,drape,bodice,sleeve_r,orb,sash,sash_point,shoes' `
  --ref-query-mask-por 'cvm_legs.png, cvm_drape.png, cvm_bodice.png, cvm_sleeve_r.png, cvm_orb.png, cvm_sash.png, cvm_sash_point.png, cvm_shoes.png' `
  --color-map 'ex3_cm.png' --depth-map 'ex3_depth2.png' `
  --control-strength 0.9 --control-start 0.0 --control-end 1.0 `
  --image-strength 0.5 --ref-no-pos 1 --edit-format ai-toolkit `
  --no-fast --steps 24 --cfg 3.5 --w 1216 --h 1632 --seed 9001 `
  --prompt-file 'prompt_main_blocks_v3.txt' --region-prompt-file 'rp_s4_v2.txt' `
  --negative 'worst quality, bad anatomy, watermark, jpeg artifact, tight fit, skinny pants, leggings, extra legs, extra limbs, extra feet, multiple people, text, letters, picture in picture, collage, reference sheet, multiple views, inset, close-up panel, floating ornament, dangling charm in mid-air, isolated ornament, silver hair, white hair, grey hair' `
  --prefix 'ex3_v1_24'
```

## 结果

**定稿 = `04-output\ex3_v3_24pale_FINAL.png`**（24 步 + `rp_s4_v2_pale.txt`）

| 版本 | 非白 | 边缘强度 | 右上角 | 左上角 | 裤腿区 | 裤腿中位 RGB | vs 参考 |
|---|---|---|---|---|---|---|---|
| 8 步 fast（对照 `s4_v17`） | 27.7% | 5.39 | 0.00% | 21.37% | 65.1% | (129,167,185) 蓝 | 133.00 |
| 24 步 sheer（`ex3_v1_24`） | 26.2% | 6.51 | 0.00% | 18.34% | 65.1% | (175,181,182) **灰白** | — |
| 24 步 opaque（`ex3_v2_24opaque`） | 26.3% | 5.96 | 0.00% | 18.41% | 65.2% | (70,104,140) **深蓝** | 133.42 |
| **24 步 pale（定稿 `ex3_v3_24pale`）** | 26.2% | **6.48** | **0.00%** | **18.34%** | 65.1% | **(165,192,193) 浅蓝** | **132.71** |

### 24 步踩的坑：`sheer` 会被放大成完全透明

第一版 24 步（`ex3_v1_24`）**裤子变成半透明纱质**，蓝色渐变与菱形几乎全丢 —— 裤腿 RGB 从 8 步的 (129,167,185) 蓝色掉到 (175,181,182) 灰白。

**先试过无效的方向**：把 `--image-strength` 从 0.5 提到 0.7 → 0.85（各 4.34 / 4.52 min），两版与 0.5 几乎一模一样，仍是透明纱。

**真因**：`legs` 的 trunk 原文是 `Wide loose trousers in gradient light-to-medium blue **sheer fabric** with a voluminous, ankle-length silhouette.` —— **`sheer`（薄纱）这个材质词在 24 步下被完全放大**。参考图本身确实是半透纱质（能看见腿），8 步 fast 时量刚好，24 步就过头。

**两轮修法**：

| 版本 | `legs` 的 trunk | 结果 |
|---|---|---|
| `rp_s4_v2_opaque.txt` | 去掉 `sheer`，补 `the fabric is opaque enough to read as solid cloth, only faintly translucent at the very hem, the leg underneath showing as a soft shape and never as bare skin through a see-through veil` | 不透明了，但**整体偏深蓝** (70,104,140) |
| **`rp_s4_v2_pale.txt`（定稿）** | 上一条 + `in pale ice-blue fabric that fades into a deeper blue toward the ankle cuff` + `the fabric is matte` + `the overall value stays light, not a saturated navy` | **浅冰蓝渐变到深蓝** (165,192,193)，与参考最接近 |

负向同时追加 `transparent fabric, see-through trousers, sheer pants`。

### 24 步 vs 8 步 fast

| 项 | 8 步 fast | 24 步 pale | 结论 |
|---|---|---|---|
| 边缘强度 | 5.39 | **6.48** | 24 步细节更多（+20%） |
| 左上角装饰线 | 21.37% | **18.34%** | 24 步更干净 |
| 右上角拼贴 | 0.00% | 0.00% | 打平 |
| 裤腿纹样区 | 65.1% | 65.1% | 打平 |
| vs 参考 | 133.00 | **132.71** | 24 步更近 |
| 耗时 | 0.24–1.30 min | **4.36 min** | 慢 3–18 倍 |

**结论**：24 步确实更细更干净，但**必须把 `sheer` 这类材质词改成显式不透明**，否则会被放大成透明；这是 8 步看不出来的问题。

## 文件清单

| 文件 | 说明 |
|---|---|
| `00-depth\ex3_black.png` | 刷黑的深度图（喂 `--depth-map`） |
| `00-depth\ex3_mask.png` | 白=人物（检查用） |
| `01-transition\ex3_t_00001_.png` | 过渡图（第 1 步） |
| `02-colormap\ex3_cm.png` | 10 区色图 |
| `02-colormap\ex3_depth2_raw.png` | Depth-Anything 原始输出 |
| `02-colormap\ex3_depth2.png` | 刷黑后的第二深度图 |
| `02-colormap\cvm_*.png`（8 张） | 画布坐标掩码 |
| `03-prompt\prompt_trans.txt` | 第 1 步用 |
| `03-prompt\prompt_main_blocks_v3.txt` | 第 3 步五块主 prompt |
| `03-prompt\rp_s4_v2.txt` | 原始 region prompt（含 `sheer`，24 步会透明） |
| `03-prompt\rp_s4_v2_opaque.txt` | 去掉 sheer 的版本（偏深蓝） |
| **`03-prompt\rp_s4_v2_pale.txt`** | **定稿 region prompt** |
| `04-output\ex3_v1_24_sheer_attempt.png` | 失败版：裤子透明 |
| `04-output\ex3_v1_24_is07.png` / `_is085.png` | 提 image-strength 无效的两版 |
| `04-output\ex3_v2_24opaque.png` | 不透明但偏深蓝 |
| **`04-output\ex3_v3_24pale_FINAL.png`** | **定稿** |
