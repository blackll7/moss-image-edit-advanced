# SOP-3 示例 · 四星2 跪姿

> **一句话**：参考图是站姿，要把同一个人同一套衣服换成跪姿，用这条流程。
> **与 SOP-1/SOP-2 的区别**：SOP-1 复刻同一姿势、SOP-2 同姿势改一个部件，**SOP-3 换姿势** —— 姿势一变，色图（定义在画布坐标上）和深度图全部作废，必须重新造。
> **核心难点**：深度图会锁死形态。直接拿新姿势深度图 + 高 control 跑，衣服会被压成紧身衣（历史 G1–G4「灯笼裤变紧身裤」就是这么来的）。**解法：先做一张低 control 的过渡图，让衣服先蓬起来，再从过渡图提第二深度图。**

---

## 目录

```
SOP-3-20261112-四星2跪姿/
├── 00-depth/
│   └── s3_depth_clean.png        新姿势深度图（刷黑后四角 0）
├── 01-transition/
│   └── s3_t2_00001_.png          ★ 过渡图（control 0.6 / end 0.6，1.00 min）
├── 02-colormap/
│   ├── s3_cm4.png                ★ 8 区色图（中灰底 49.34%）
│   └── s3_depth2_clean.png       ★ 第二深度图（带服装体积）
├── 03-prompt/
│   ├── prompt_trans2.txt         过渡图 prompt（英文色名 + 蓬松三句）
│   ├── prompt_main.txt           第 3 步主 prompt（只交代姿势白底画风）
│   └── rp_s3_v3.txt              ★ 8 条 region prompt（6966 字符，带位置前缀）
└── 04-output/
    └── s3_v4_00001_.png          ★ 定稿（0.93 min，8 步 fast seed 9001）
```

★ = 生成实际用到的四个文件

---

## 三步命令

### 第 0 步：新姿势深度图刷黑

新姿势的深度图常带地面（底部两角很亮）。按行找「横跨全宽」的那一行：

```python
for y in range(1300, H, 25):
    row = (a[y] > 60)
    print(y, row.mean()*100, longest_span(row))
# 实测：y=1425 99.8% → y≥1450 100.0%（最长段 1216）= 纯地面
```

刷黑三步：

```python
a[1430:, :] = 0          # 地面
a[a < 58] = 0            # 背景雾（先看直方图，背景主峰在 30-49）
a[:, :40] = 0; a[:, -40:] = 0
```

**检查点**：四角全 `0`；人物占比 30–70%。

### 第 1 步：纯 T2I 过渡图

**只传深度图**，不传 `--image`、不传 `--color-map`。

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'C:\MOSS-Deploy\moss_run.py' --port 8190 `
  --depth-map 's3_depth_clean.png' `
  --control-strength 0.6 --control-end 0.6 `
  --w 1216 --h 1632 --fast --seed 9001 --edit-format ai-toolkit `
  --negative 'worst quality, bad anatomy, watermark, jpeg artifact, sheer fabric, transparent, gradient, pattern, multiple people, tight fit, skinny pants, leggings' `
  --prompt-file '03-prompt\prompt_trans2.txt' --prefix 's3_t2'
```

**control 对照**：

| `--control-strength` | 结果 |
|---|---|
| 1.0 | 裤子平直、像紧身裤 |
| **0.6** | **大腿与小腿都有明显褶皱和鼓包** ← 用这个 |

**prompt 里最关键的三句**：
- `ballooning out from the hips into a rounded barrel shape`
- `staying wide and puffy all the way down the thigh and calf, never hugging the legs`
- `gathered tight only at the ankle cuff`

### 第 2 步：从过渡图提色图 + 提深度图

```powershell
# 提第二深度图
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'C:\MOSS-Deploy\work\depth_from_image.py' `
    's3_t2_00001_.png' 'C:\MOSS-Deploy\ComfyUI\input\s3_depth2.png'
```

色图按目标色距离分割（`mind < 60`，排除白底与肤色）。**三条实测约束**：

| 情况 | 做法 |
|---|---|
| 大件（legs / drape / bodice / sleeve） | 按颜色提取可靠 |
| **小件（shoes / sash_point）** | 颜色阈值会混入阴影，**改手工椭圆** |
| **薄纱（veil）** | **不要合进 bodice**，留中灰 128 交给主 prompt |

第二深度图同样刷黑（实测四角 `[50, 36, 191, 173]`）。

### 第 3 步：A+B 精修

```powershell
$ids = @('legs','drape','sash_point','sash','shoes','bodice','sleeve_r','orb')
$img = ($ids | ForEach-Object { "e9_$_.png:raw" }) -join ','
$msk = ($ids | ForEach-Object { "e9m_$_.png" }) -join ','
$rp  = Get-Content '03-prompt\rp_s3_v3.txt' -Encoding UTF8 | Where-Object { $_.Trim() }
$a = @(); foreach ($l in $rp) { $a += @('--region-prompt', $l) }

& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'C:\MOSS-Deploy\moss_run.py' --port 8190 `
  --image $img --ref-labels ($ids -join ',') --ref-query-mask-por $msk `
  --color-map 's3_cm4.png' --depth-map 's3_depth2_clean.png' `
  --control-strength 1.0 --control-end 0.6 `
  --w 1216 --h 1632 --fast --seed 9001 `
  --edit-format ai-toolkit --ref-no-pos 1 `
  --negative 'worst quality, bad anatomy, watermark, jpeg artifact, multiple people, text, letters, isolated ornament, floating object' `
  --prompt-file '03-prompt\prompt_main.txt' @a --prefix 's3_v4'
```

---

## 五处不能改的参数

| 参数 | 值 | 为什么 |
|---|---|---|
| `--control-strength` | **1.0**（第 3 步）/ **0.6**（第 1 步） | 第 3 步锁形态，第 1 步放开让衣服蓬 |
| `--control-end` | **0.6** | 早停让后段放开细节 |
| `--depth-map` | 过渡图提的第二深度图 | 带服装体积 |
| `--color-map` | 从过渡图提的 8 区 | 定义在新姿势坐标上 |
| `--ref-no-pos 1` | 开 | 解耦参考布局，避免站姿压过新姿势 |
| `--edit-format` | `ai-toolkit` | 与 SOP-1 一致 |

---

## 已知边界

1. **鞋**：参考是灰蓝缎面尖头 + 金鞋头，生成常变成深灰圆头。跪姿下脚背朝上、鞋被裤脚遮住大半，模型按「跪姿脚部」先验补圆头。手工色区（2.35%）只改善到「有金色装饰环」，头型仍圆。与 SOP-1/SOP-2 的脚部短板同源。
2. **金竖条纹密度**：`legs` details 写 `approximately 6 per leg visible`，实际只画出 1–2 条。纹样密度是文本的弱项。
3. **小件色区**：面积 < 1% 的部位（`sash_point 0.48%`）色图几乎不起作用，只能靠裁片 + 文案。
4. **薄纱**：`veil` 不能合进任何色区。

---

## 出问题时

| 症状 | 原因 | 修法 |
|---|---|---|
| 右上角多出一个巨大饰件 | `orb` 没写位置 | 加 `hanging at her left hip ... never floating or shown alone` + 负向 `isolated ornament, floating object` |
| 头纱被画成胸衣的颜色 | `veil` 合进了 `bodice` 色区 | 头纱留中灰 |
| 裤子是紧身裤 | control 太高 / prompt 没写蓬松 / 负向缺 `tight fit` | 用 `0.6`，加「蓬松三句」 |
| 前片被放大成一大块矩形 | 没写 `narrow in width` + 色区太小 | 加位置前缀，或手工填色块 |
| 画面左右各多一条装饰带 | 深度图背景没刷黑 | 见第 0 步 |
| 多个人 / 角色设定图 | 降了 `--depth-strength` | 不要降 depth，降的是 `--control-strength` |

---

## 本案例达到与未达到

**达到**：跪姿正确（双臂下压、双膝着地、上身前倾）；裤色浅蓝→裤脚深蓝渐变；金竖条纹出现；前片是金框蓝色面板、位置居中；`orb` 压在腰带右侧；头纱青色；右上角无独立饰件；胸衣是暗蓝 + 紫方砖 + 金饰。

**未达到**：鞋仍是深灰圆头；金竖条纹只有 1–2 条（要求 6）。
