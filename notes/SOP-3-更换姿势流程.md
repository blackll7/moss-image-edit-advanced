# SOP-3 · 更换姿势流程

> **一句话**：手上有一张参考图，要**保留人物与服装、只换成另一个姿势**，用这条流程。
> **与 SOP-1/SOP-2 的区别**：SOP-1 复刻同一姿势，SOP-2 同姿势改一个部件材质，**SOP-3 换姿势**——姿势一变，色图（定义在画布坐标上）与深度图全部作废，必须重新造。
> **核心难点**：深度图会锁死形态。若直接拿新姿势的深度图 + 高 control 跑 SOP-1，衣服会被压成紧身衣（历史 G1–G4 那批「灯笼裤变紧身裤」就是这么来的）。**解法是先做一张低 control 的过渡图，让衣服在过渡图里先蓬起来，再从过渡图提第二深度图。**

---

## 零、总览

```
参考图（原姿势）                                新姿势深度图
   │                                               │
   ├─[A] 切块反写 describe_parts.py                 │
   │     按部位切成小块 → 逐块反写 → parts_all.json  │
   │     trunk 一句话（品类/主色/材质/轮廓）           │
   │     details 5–8 条（颜色+材质+形状+数量+位置）    │
   │        │                                       │
   │        ├─[A1] 切裁片+掩码 pick_parts.py         │
   │        │      选 ≤8 个关键部件                  │
   │        │      → 裁片（参考侧"是什么"）           │
   │        │      → 掩码（参考侧"在哪"）             │
   │        │                                       │
   │        └─[A2] 部位内切子区 describe_subzones.py │
   │               每个部位再按垂直切 3 段             │
   │               逐段反写 → 拿到「每段有什么、几个」  │
   │               → **这些细节用来重写 [3] 的文案**   │
   │                                               │
   │                                      [0] 刷黑背景
   │                                               │
   │                                      [1] 纯 T2I 过渡图
   │                                         只传 --depth-map
   │                                          control 0.6 / end 0.6
   │                                         prompt 用英文色名
   │                                         深度图轮廓偏窄时，必须在 prompt
   │                                         里写出服装的实际宽度
   │                                               │
   │                                      [2] 从过渡图提
   │                                         ├─ 色图（按颜色分割）
   │                                         └─ 深度图（带服装体积）
   │                                               │
   └─────────────────[3] A+B 精修──────────────────┘
              裁片 + <tag> + 色图 + 深度图
              掩码用画布坐标（从色图反推 cvm_*.png）
              五块主 prompt（tag 在这里引出，带位置）
              + region prompt（前形状、后细节）
              参数 0.9 / end 1.0 / image-strength 0.5
```

**两步走**：左半边是「从参考图取料」（A / A1 / A2，与姿势无关，参考图不变就不用重跑），右半边是「按新姿势铺料」（0 / 1 / 2 / 3）。

**三条通道各自管什么**：

| 通道 | 管什么 | 来源 |
|---|---|---|
| 裁片 + `<tag>`（参考侧） | **是什么** —— 形貌、材质、纹样 | 参考图（原姿势） |
| 色图 + 深度图（画布侧） | **在哪** —— 位置、体积 | 过渡图（新姿势） |
| region prompt | 把两者接起来：`the <#hex> area is <tag>, <位置>; its shape is: <trunk>. Its colours, patterns and materials: <details>` | `parts_all.json` 的 trunk + details + `subzones.json` 的子区细节 |

**参考侧与画布侧本来就是两套几何**（一个站姿、一个新姿势，幅度大的如 standing split 更悬殊）。因此：

- **掩码必须用画布坐标**（从新姿势色区反推 `cvm_*.png`），参考侧 `e9m_*.png` 只说明「参考图里这块在哪」，换姿势后基本失效（`drape` 的 IoU 甚至 0.00%）。
- 实测新旧姿势接近时（站姿→跪姿）`legs 0.25` / `bodice 0.20` 已属「大致重合」；幅度大时不要指望掩码，靠色图 + region prompt。

---

## 零·一、第 A 步：从参考图取料（SOP-3 自带，不依赖 SOP-1）

**参考图不变就不用重跑这一步。** 三个子步，全在本流程内部完成。

### A、切块反写：把参考图变成文本

把参考图按人体部位切成小块，逐块多模态反写，**把主干与细节分开**。

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\describe_parts.py' `
    --image 'C:\MOSS-Deploy\ComfyUI\input\v2sop_ref.png' `
    --out   'C:\MOSS-Deploy\work\parts_all.json'
```

输出 `parts_all.json`，每个部位含：

| 字段 | 内容 | 用途 |
|---|---|---|
| `trunk` | 形状 / 主色 / 材质 / 轮廓（约 1100 字） | **只用来指位置**，不要进 region prompt |
| `details[]` | 纹样 / 数量 / 位置 / 质感（约 9300 字，每部位 5–8 条） | **留给 region prompt** |
| `bbox_px` | 像素坐标 | 切裁片、切掩码 |
| `area_pct` | 画布占比 | 打分、定文案预算 |

`trunk : details ≈ 1 : 8.5` —— 细节天然比主干多，但两者不能混着用。

### A1、切裁片 + 掩码：把部位变成「参考通道」

从 `parts_all.json` 里选 **≤8 个**关键部件（`--ref-query-mask-por` 的硬上限），切裁片与掩码。

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\pick_parts.py' `
    --parts  'C:\MOSS-Deploy\work\parts_all.json' `
    --ref    'C:\MOSS-Deploy\ComfyUI\input\v2sop_ref.png' `
    --w 1216 --h 1632 `
    --input-dir 'C:\MOSS-Deploy\ComfyUI\input' `
    --prefix e9 --max 8 --size 512 --min-area 2.5 `
    --out-selection 'C:\MOSS-Deploy\work\picked9.json'
```

**选择规则**（脚本按此打分）：面积大 ×10 / 位置易漂（`sash`/`waist`/`belt`/`point`/`cuff`）+5 / 需配对（`point`/`inner`/`lining`）+3 / 细节条数每条 +0.5 封顶 8。黑名单 `hair`/`orb`/`face`/`head`。

**输出**：裁片 `input\e9_<id>.png`（最长边 512）、掩码 `input\e9m_<id>.png`（画布同尺寸，`bbox ∩ 参考图非背景`）、选择结果 `work\picked9.json`。

### A2、部位内切子区：拿到「每段有什么、几个」

**这一步是「切块后获取更详细的提示词」的第二次细分。** `details[]` 是整块统计式描述（例如 `approximately 6 per leg visible`），没告诉你「哪一段长什么样」。而服装细节在纵向上分布不均（裤腰 / 裤腿中段 / 裤脚是三批不同的东西），所以要**按垂直方向再把每个部位切 3 段**，逐段反写。

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\describe_subzones.py' `
    --ref      'C:\MOSS-Deploy\ComfyUI\input\v2sop_ref.png' `
    --mask-dir 'C:\MOSS-Deploy\ComfyUI\input' --prefix e9m_ `
    --ids 'legs,drape,bodice,sleeve_r,orb,sash,shoes,sash_point' `
    --parts 3 --upscale 1.4 `
    --out 'E:\DSH-MOSS工作区\work\sop3\subzones.json' `
    --cropdir 'E:\DSH-MOSS工作区\work\sop3\subzones'
```

**切法**：按**累积前景像素**分 3 段（每段含等量前景，而非等高分），段内把掩码外的背景刷中灰 `(128,128,128)`，放大 1.4 倍再反写。

**为什么是垂直而不是水平**：服装左右对称，横切会把对称的两半切开、每段都说「半个图案」；纵切才是「上/中/下」三种不同内容。

**产出举例**（实测）：

| 部位·段 | 反写结果 |
|---|---|
| `legs` 段1（上） | **两条**完整金竖条纹、**三个**完整水滴坠、**一个**星星贴花、**四个**小圆珠 |
| `legs` 段3（下） | **4 个**白色菱形绣花带金边、**2 个**蓝色三角嵌片带粉色内衬、**2 个**金色缎带环、**2 个**金脚链带坠 |
| `sash` 段2（中） | **2 条**金珠链、**3 个**浅蓝水晶水滴坠、**1 个**中央大金饰带净宝石 |
| `bodice` 段2（中） | **6 个**紫方宝石呈网格排布、上下各 **1 条**金卷草带、顶部 **1 个**净色水滴宝石 |

对比整块反写只会说 `approximately 6 per leg visible` —— **子区反写才给得出「几个」与「在哪一段」**。

### A2 的产出怎么用进第 3 步

子区细节**不单独进 prompt**，而是**替换/补充 `details[]` 里对应的那几条**，再整条拼进 region prompt：

```python
# 第 3 步的 region prompt 是这么拼的：
det  = '; '.join(s.rstrip('.') for s in by[pid]['details'])      # 来自 A 步
sub  = '; '.join(s.rstrip('.') for b in subz[pid]['parts']        # 来自 A2 步
                 for s in b['details'])
line = ('the %s area is <%s>, %s; its shape is: %s. '
        'Its colours, patterns and materials: %s; %s') % (hexv, pid, loc[pid], trunk, det, sub)
```

**优先级**：A2 的段内数量比 A 的整块统计更可靠（它能看到「这一段里只有两条」），所以要**放在 `details` 后面**，让模型读到数量时最后一条是具体的。

**检查点**：
- `parts_all.json` 每个部位都有 `trunk` 与 `details`
- `picked9.json` 里恰好 8 个部位，面积都 ≥ 2.5%
- `subzones.json` 里每个部位 3 段，每段 4–9 条

---


## 零·五、第 0 步：新姿势深度图刷纯黑

### 为什么

MOSS 的深度语义是「近处白、远处黑」。深度图一角很亮会被读成「这里有一块很近的东西」，模型在画布对应侧补画近景装饰。实测参考图深度图四角 `[152.7, 153.8, 243.1, 247.0]` → 24 步生成时左右各多一条贯穿全高的装饰带（边缘非白 **99.7%**）；刷黑后 **0.0%**。

### 命令（用工具，不要手写阈值）

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\depth_to_mask.py' `
    '你的新姿势深度图.webp' `
    'C:\MOSS-Deploy\ComfyUI\input\s4' `
    --width 1216 --height 1632 --feather 2
```

**输出两个文件**：
- `s4_black.png` → 喂 `--depth-map`（原深度值，背景全 0）
- `s4_mask.png` → 喂 `--mask` / `--ref-query-mask`（纯黑白，白=人物）

### 它做了什么

| 步骤 | 作用 |
|---|---|
| **Otsu 阈值** | 自适应，不用手调。只在 ROI 内统计，避免四角亮角干扰 |
| **形态学闭/开运算** | `CLOSE (13,13)` 补小洞，`OPEN (5,5)` 去毛刺 |
| **地面宽段过滤** | `y >= 图高×0.86` 的行里，丢掉宽度 > 300 px 的连续段（地面横跨全宽），保留窄段（脚只有几十像素） |
| **最大连通域** | 只留最大的那块，去掉背景里的孤立亮斑 |
| **填洞** | 闭运算补上两腿之间、手臂内侧的小洞 |
| **羽化** | 边缘 `GaussianBlur`（只给 mask，刷黑的深度图不羽化） |

### 关键：为什么不能手写矩形硬切

**2026-11-12 实测的四个坑**（都试过、都失败）：

| 手写方案 | 结果 |
|---|---|
| `a[a<58]=0` 全局阈值 | 背景是**从上到下渐变、四角偏亮**的灰（四角 `[114,101,175,194]`），残留大片灰、还切出怪异多边形 |
| 行内自适应 `thr=max(110,mx-55)` | 人物只剩 **4.49%**（躯干 150 被切掉） |
| 每行低分位减背景 + 最长连续段 | 只剩 **10.09%**（人物被切成横条） |
| `m[1480:,:]=0` 切地面 | **把站立的脚切掉了** → 过渡图生成多肢体 |
| `m[:130,:]=0` 切顶部 | **把抬起的脚尖切掉了**（脚尖从 y=100 开始） |
| 矩形挖空避免切脚 | 留下方块边，人物形状失真 |

**根因**：这张图的背景是渐变灰、与人物暗部（手臂 ~130、躯干 ~150）重叠，**单靠灰度阈值分不开**；而人物上下都有「延伸到边缘」的部分（脚尖、站立的脚），**任何一刀切都是错的**。

**正确做法**：Otsu 定阈值 + **地面按「段宽度」而不是「行位置」过滤**（地面横跨全宽 → 宽段；脚只有几十像素 → 窄段），再取最大连通域。

### 检查点

- 四角必须全是 `0`
- 人物占比 **10–20%**（瘦长站姿）或 25–40%（跪坐/蹲姿），**bbox 不贴画布任何一边**
- **两只脚都在**（如果姿势有两只脚可见）—— 看 `bbox` 的 `y` 是否到人物实际最低点
- 日志 `[depth_to_mask] 地面过滤` 那一行的像素数应该**只减少一部分**（实测 `448797 → 275652`）。如果减少到接近 0，说明 `--floor-max-width` 设小了，脚也被当地面切了

### 地面不用切干净

**地面轮廓对生成没有影响**，只要 prompt 里写「站在地面上」。所以：
```
standing on her right leg on the ground … one foot planted flat on the floor, the other foot raised high in the air
```
**这句写进第 1 步的 prompt 首句**，模型就知道脚踩在地上。

---

## 一、第 1 步：纯 T2I 过渡图（低 control）

### 做什么
**只传新姿势的深度图**，不传 `--image`、不传 `--color-map`。让模型自由发挥，把衣服画蓬。

### 为什么 control 要低
| `--control-strength` | 结果 |
|---|---|
| **1.0** | 裤子平直、像紧身裤（深度图轮廓被当成衣服轮廓） |
| **0.6** | **大腿与小腿都有明显褶皱和鼓包** ← 用这个 |

### 命令
```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'C:\MOSS-Deploy\moss_run.py' --port 8190 `
  --depth-map 's3_depth_clean.png' `
  --control-strength 0.6 --control-end 0.6 `
  --w 1216 --h 1632 --fast --seed 9001 --edit-format ai-toolkit `
  --negative 'worst quality, bad anatomy, watermark, jpeg artifact, sheer fabric, transparent, gradient, pattern, multiple people, tight fit, skinny pants, leggings' `
  --prompt-file 'prompt_trans.txt' --prefix 's3_t2'
```

### prompt 写法
**用英文色名，不用 hex**。MOSS 把英文色名当填色指令，hex 只当区域 ID。

```
a woman kneeling on the ground, both arms lowered and pressing down to the sides,
upper body leaning forward, full body in frame, plain flat white background,
hand-drawn anime illustration with clean lineart and flat cel shading.

She wears solid opaque clothing in clearly separated flat colours. Her trousers are
wide loose harem pants in deep green: ballooning out from the hips into a rounded
barrel shape, staying wide and puffy all the way down the thigh and calf, never
hugging the legs, packed with volume and deep cloth folds, gathered tight only at
the ankle cuff. A long cape hangs from her left hip down to the floor in crimson red. ...
```

**关键三句，作用是「把衣服的实际宽度写出来」**：
- `ballooning out from the hips into a rounded barrel shape` —— 给出整体宽度轮廓
- `staying wide and puffy all the way down the thigh and calf, never hugging the legs` —— 明确排除「贴腿」
- `gathered tight only at the ankle cuff` —— 指定唯一收窄的位置

**为什么要写宽度**：深度图只给「人体表面」，不含衣料。当新姿势的深度图本身轮廓偏窄（例如跪姿把腿压在一起），模型会按深度图的轮廓把衣料一路贴着画，结果就是紧身裤。**这时必须在 prompt 里补出服装的实际宽度**，用「桶形 + 全程宽 + 只踝部收」三句把宽度顶开。

**负向必须有** `tight fit, skinny pants, leggings`，否则模型默认画贴身。

### 检查点
- 姿势与深度图一致（跪姿：双臂下压、双膝着地、上身前倾）
- **裤子有明显鼓包**，不是直筒
- 11 种颜色**全部对上**（用 `hot pink` / `crimson red` / `deep green` 这种标准色名比 hex 稳）

---

## 二、第 2 步：从过渡图提色图 + 提深度图

### 2.1 提色图（按颜色分割）

**先采样过渡图实际画出的颜色**（numpy K-means，sklearn 没装）：

```python
bg = a.min(axis=2) > 238            # 白底
fg = a[~bg]
K = 14
# 30–40 轮迭代，按占比排序打印
```

**再按目标色距离分割**：
```python
for name, srcs, hexv in T:
    cols = np.array(srcs, np.float32)
    d = np.linalg.norm(a[:,:,None,:] - cols[None,None,:,:], axis=3)
    mind = d.min(axis=2)
    m = (mind < 60) & (~bg) & (~skin) & (~used)
    out[m] = hex_from(hexv); used |= m
```

**三条实测约束**：

| 情况 | 做法 |
|---|---|
| **大件（legs / drape / bodice / sleeve）** | 按颜色提取可靠，形状贴合 |
| **小件（shoes / sash_point）** | **不可靠** —— 颜色阈值会混入阴影，实测 `shoes` bbox 横跨全宽、与掩码交集 0.0%。**改用手工椭圆/矩形**：按过渡图目视位置填 |
| **薄纱（veil）** | **不要合进 bodice** —— 合了会被填成胸衣的颜色，模型按胸衣去画头纱。**留中灰 128，交给主 prompt** |

**手工填小件的例子**：
```python
yy,xx = np.mgrid[0:H,0:W]
shoe = (((xx-115)/80)**2 + ((yy-1475)/90)**2 <= 1) | \
       (((xx-875)/85)**2 + ((yy-1505)/90)**2 <= 1)
cm[shoe] = (255,0,0)
```

### 2.2 提第二深度图

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'C:\MOSS-Deploy\work\depth_from_image.py' `
    '过渡图.png' 'C:\MOSS-Deploy\ComfyUI\input\s3_depth2.png'
```

**这张图的价值**：它带**服装体积**（灯笼裤的大腿鼓包、膝下深褶都在深度里），比原始姿势深度图更适合锁形态。

**同样要刷黑**（实测四角 `[50, 36, 191, 173]`）。这条过渡图的背景是**均匀深灰**（人物从 60 起、背景主峰 30–49），所以这里可以直接用简单的阈值 + 切底部；如果背景是渐变或有地面，用同一个工具：

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\depth_to_mask.py' `
    'C:\MOSS-Deploy\ComfyUI\input\s3_depth2.png' `
    'C:\MOSS-Deploy\ComfyUI\input\s3_depth2' `
    --feather 0 --keep-floor
```

**注意**：第二深度图是「从已生成的画里反推的」，**它没有人物的完整轮廓信息**（画面四周是白底、没有真实的远近关系），所以**不要用地面宽段过滤**（`--keep-floor`），否则会把画面下半当成地面切掉。这种情况也可以直接用两行：

```python
a[a < 58] = 0        # 背景
a[1500:, :] = 0      # 底部（图像边缘，非人物）
a[:, :40] = 0; a[:, -40:] = 0
```

---

## 三、第 3 步：A+B 精修（裁片 + `<tag>` + 色图 + 深度图）

### 命令骨架
```powershell
$ids = @('legs','drape','sash_point','sash','shoes','bodice','sleeve_r','orb')
$img = ($ids | ForEach-Object { "e9_$_.png:raw" }) -join ','
# 掩码用画布坐标（从色图反推），不要用参考侧 e9m_*.png —— 那是参考图坐标
$msk = ($ids | ForEach-Object { "cvm_$_.png" }) -join ','

& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'C:\MOSS-Deploy\moss_run.py' --port 8190 `
  --image $img --ref-labels ($ids -join ',') --ref-query-mask-por $msk `
  --color-map 's3_cm4.png' --depth-map 's3_depth2_clean.png' `
  --control-strength 0.9 --control-start 0.0 --control-end 1.0 `
  --image-strength 0.5 `
  --w 1216 --h 1632 --fast --seed 9001 `
  --edit-format ai-toolkit --ref-no-pos 1 `
  --negative 'worst quality, bad anatomy, watermark, jpeg artifact, multiple people, text, letters, picture in picture, collage, reference sheet, multiple views, inset, close-up panel, isolated ornament, floating object, silver hair, white hair, grey hair' `
  --prompt-file 'prompt_main.txt' @a --prefix 's3_v4'
```

### 掩码怎么来：`cvm_*.png`（画布坐标）

**不要用 `e9m_*.png`** —— 那是参考图的掩码，坐标系是参考图。`--ref-query-mask-por` 要的是**画布坐标**（`moss_ref_mask.py:65-66`：「mask i is the canvas region allowed to read reference i」）。

从第 2 步的色图直接反推，每个色区一张，再适度膨胀：

```python
import numpy as np, cv2
from PIL import Image
cm = np.asarray(Image.open(r'C:\MOSS-Deploy\ComfyUI\input\s4_cm.png').convert('RGB'))
for pid, hexv in [('legs','#ff00ff'),('drape','#0000ff'),('bodice','#ff8000'),
                  ('sleeve_r','#80ff00'),('orb','#c0c0c0'),('sash','#00ff00'),
                  ('sash_point','#800040'),('shoes','#ff0000')]:
    r,g,b = int(hexv[1:3],16), int(hexv[3:5],16), int(hexv[5:7],16)
    m = (np.abs(cm[:,:,0].astype(int)-r) < 12) & (np.abs(cm[:,:,1].astype(int)-g) < 12) & (np.abs(cm[:,:,2].astype(int)-b) < 12)
    m = m.astype(np.uint8)
    # 膨胀：大区域 9px，小区域 3px（面积 < 1% 用 3px，否则 orb/shoes 会膨胀成一团）
    k = 3 if m.mean() < 0.01 else 9
    m = cv2.dilate(m, np.ones((k,k), np.uint8))
    Image.fromarray(m*255).save(r'C:\MOSS-Deploy\ComfyUI\input\cvm_%s.png' % pid)
    print('%-11s %.2f%%  膨胀 %dpx' % (pid, m.mean()*100, k))
```

**为什么要膨胀**：色区是「布料像素」的精确匹配，边界会漏掉抗锯齿与线稿。实测膨胀后边缘强度 6.21 → **7.47**（+20%），裤腿菱形 1 → 2。

**膨胀不能一刀切**：`orb` 色区只有 0.23%，9px 膨胀会把周围一圈都吃掉，右上角反而长出一簇挂坠。**面积 < 1% 的用 3px**。

### 主 prompt：五块结构（照 SOP-1，所有 `<tag>` 在这里引出）

```xml
<|style_and_lighting|>A single standing woman alone on a plain flat pure white empty background with nothing else in the frame, no props, no panels, no floating objects, long golden blonde hair in a single braid, <姿势与机位>, full body in frame, hand-drawn anime illustration with clean lineart and flat cel shading, soft even studio light, no cast shadow on the background.<|/style_and_lighting|>
<|upper_body|>Her upper chest and bust are covered by <bodice>, worn centred on her chest and covering the bust. Her right upper arm, which is raised up and holding the lifted calf, carries <sleeve_r>.<|/upper_body|>
<|waist_and_hip|>Her waist is wrapped in <sash>. A short narrow panel hangs straight down the front of her waist over the crotch, and it is <sash_point>. A long panel hangs from her left hip all the way down to the floor on the left side of the figure, and it is <drape>. A small round ornament dangles at her left hip on a short chain, against the trousers, and it is <orb>.<|/waist_and_hip|>
<|legs|>From waist to ankle her legs are covered by <legs>: the left leg is lifted straight up above her head, and the right leg is standing on the ground. Her feet wear <shoes>, one on the raised foot and one on the standing foot.<|/legs|>
<|constraints|>For every named body region, use the garment from the reference given for that region and no other. Do not draw any of these parts as separate objects beside the figure; each is worn on the body. Exactly one person appears in the whole image. The background stays completely empty white.<|/constraints|>
```

**四条要点**（与 SOP-1 一致）：

1. **第 1 块写风格与光影，且首句就锁死空白背景** —— `alone on a plain flat pure white empty background with nothing else in the frame, no props, no panels, no floating objects`。实测这一句把左上角装饰线从 39.54% 压到 **21.37%**。
2. **块按人体从上到下**：`style_and_lighting` → `upper_body` → `waist_and_hip` → `legs` → `constraints`。
3. **每个 `<tag>` 在这里引出，并写明它在当前姿势下的位置**（`worn centred on her chest` / `over the crotch` / `all the way down to the floor on the left side` / `against the trousers` / `one on the raised foot`）。
4. **`<|constraints|>` 必须留** —— 那句 `Do not draw any of these parts as separate objects beside the figure` 是压拼贴最有效的一条，实测右上角从 4.33% 压到 **0.19%**。

**不要在主 prompt 里写形貌**（宽度、长度、材质），那会跟 region prompt 抢；形貌放 region prompt 前部。

### region prompt：前部位置 + 形状，后部颜色纹样材质

格式固定为三段：

```
the <#hex> area is <tag>, <该姿势下的位置>; its shape is: <trunk>.
Its colours, patterns and materials: <details 用 ; 连>
```

```python
trunk = by[pid]['trunk'].strip().rstrip('.')                        # A 步：形状
det   = '; '.join(s.rstrip('.') for s in by[pid]['details'])        # A 步：细节
sub   = '; '.join(s.rstrip('.') for b in subz[pid]['parts']         # A2 步：子区数量
                  for s in b['details'])
line = ('the %s area is <%s>, %s; its shape is: %s. '
        'Its colours, patterns and materials: %s; %s') % (hexv, pid, loc[pid], trunk, det, sub)
```

**为什么这么分段**：

| 段 | 内容 | 作用 |
|---|---|---|
| 前部 | `<tag>` + 位置（新姿势坐标） | 告诉模型「这块东西戴在哪」，是防漂移的唯一手段 |
| 中段 | `trunk`（形状） | 宽度/长度/轮廓——**只有这里写形貌不会跟主 prompt 抢** |
| 后部 | `details` + 子区数量 | 颜色、纹样、材质、每段几个 |

**子区细节放最后**：`details[]` 给的是「整体有哪些东西」，A2 子区给的是「这一段里有几个」，后者能纠正前者过于笼统的数量（`approximately 6` → 段1 只有 2 条），**放最后让模型最后读到的是具体数字**。

**位置前缀是必写的**（实测缺了就出问题）：

| 部位 | 位置前缀 | 缺了会怎样 |
|---|---|---|
| `orb` | `a small charm dangling at her left hip on a short chain, hanging against the trousers, never floating or shown alone` | **被画成右上角一个巨大的独立饰件**（占画布 8%） |
| `sash_point` | `a narrow strip hanging straight down from the lower edge of the waistband, centred over the crotch, narrow in width` | 被放大成一大块矩形 |
| `legs` | `worn on both legs from waist to ankle` | 位置漂移 |
| `drape` | `hanging from her left hip down to the floor, outside the trousers` | 跑到别处 |

**负向还要加** `isolated ornament, floating object`，双保险。

**长度不是问题**：`moss_run.py:472-478` 把 8 条拼成 `"Colour key: " + " ".join(rp)` 直接追加到主 prompt 末尾，**没有长度上限**。实测 6966 字符 / 8 条正常工作。

---

## 四、参数表（七处不能改）

| 参数 | 值 | 为什么 |
|---|---|---|
| `--control-strength` | **0.9**（第 3 步）/ **0.6**（第 1 步过渡图） | 第 3 步要锁形态；第 1 步要放开 |
| `--control-end` | **1.0**（第 3 步）/ **0.6**（第 1 步） | **第 3 步必须 end 1.0 全程按住**；第 1 步早停让后段长细节 |
| `--depth-map` | 过渡图提的第二深度图（刷黑） | 带服装体积 |
| `--color-map` | 从过渡图提的色图（8–10 区） | 定义在新姿势坐标上；区数上限 = 互不重叠的部位数 |
| `--ref-no-pos 1` | 开 | 解耦参考的布局，避免参考的站姿压过新姿势 |
| `--image-strength` | **0.5** | **压拼贴的关键开关**。默认 1.0 时右上角拼贴 25.4%，0.5 降到 4.3% 而裤腿区细节几乎不变（69.5%→70.2%） |
| `--ref-query-mask-por` | **`cvm_*.png`（画布坐标）** | 用参考侧 `e9m_*.png` 会错位：换姿势后 `drape` 的 IoU 是 **0.00%**、`bodice 6.20%`、`sleeve_r 6.92%` |
| `--edit-format` | `ai-toolkit` | 与 SOP-1 一致（本身就是「参考走 vision tokens」，所以 `--ref-vision-only` 是重复的） |

---

## 五、已知边界

1. **鞋**：参考是灰蓝缎面尖头 + 金鞋头，生成常变成深灰圆头。跪姿下脚背朝上、鞋被裤脚遮住大半，模型按「跪姿脚部」先验补圆头平底。加手工色区（实测 2.35%）只改善到「有金色装饰环」，头型仍圆。**与 SOP-1/SOP-2 记录的脚部短板同源**（分区 `vs参考` 144.5–156.1 vs 其他 106–123）。
2. **金竖条纹密度**：`legs` details 写 `approximately 6 per leg visible`，实际只画出 1–2 条。纹样密度是文本的弱项（B 链三条死路已证）。
3. **小件色区**：面积 < 1% 的部位（`sash_point 0.48%`）色图几乎不起作用，只能靠裁片 + 文案。
4. **薄纱**：`veil` 不能合进任何色区，只能留中灰让主 prompt 处理。
5. **掩码坐标系**：`--ref-query-mask-por` 的掩码是**画布坐标**，不是参考图坐标（`C:\MOSS-Deploy\ComfyUI\custom_nodes\comfyui-moss-ref-bias\moss_ref_mask.py:65-66` 的 `DESCRIPTION` 原文「mask i is the **canvas region** allowed to read reference i」；`comfy\ldm\moss_image\model.py:409-415` 把它 interpolate 到 latent `(H,W)` 后按「画面第几个 image token」`masked_fill_`）。**旋转参考图无效**。换姿势幅度大时参考侧掩码与新色区严重错位：实测 IoU `legs 34.28%` / `sash_point 17.41%` / `sash 11.16%` / `sleeve_r 6.92%` / `bodice 6.20%` / `shoes 2.35%` / `orb 0.43%` / **`drape 0.00%`**（垂布从腰侧滑到地面）。正解是从新姿势色区反推 `cvm_*.png`。
6. **拼贴（参考裁片被画成画面里的特写）**：`--control-strength 1.0` 会让它从 25.4% 飙到 73.4%，降 `--color-strength` 没用（反而 84.0%）。0.9 是「多个人」与「拼贴」两个病症的平衡点。
7. **24 步会把材质词放大**：`legs` 的 trunk 里若写 `sheer fabric`，8 步 fast 下量刚好（裤腿 RGB (129,167,185) 蓝），**24 步会放大成完全透明**（(175,181,182) 灰白，蓝色渐变与菱形全丢）。实测提高 `--image-strength` 到 0.7 / 0.85 无效。修法是改 trunk：去掉 `sheer`，改写 `the fabric is opaque enough to read as solid cloth, only faintly translucent at the very hem` + `in pale ice-blue fabric that fades into a deeper blue toward the ankle cuff` + `the fabric is matte` + `the overall value stays light, not a saturated navy`，负向加 `transparent fabric, see-through trousers, sheer pants`。改后 (165,192,193) 浅蓝，vs 参考 132.71（8 步是 133.00）。
8. **8 步 fast 的纹样密度上限**：24 步（`--no-fast --steps 24 --cfg 3.5`，4.27 min）画面更干净（边缘强度 7.51 vs 6.42）但**裤腿纹样反而更少**；`--region-prompt-head` 把 `legs` 那条 1113 字符前置也无效。

---

## 六、跑前检查表

**取料侧（A / A1 / A2）**
- [ ] `parts_all.json` 每个部位都有 `trunk` 与 `details`，`bbox_px` 落在 0–W / 0–H 之间
- [ ] `picked9.json` 恰好 8 个部位、面积都 ≥ 2.5%
- [ ] 裁片 `e9_*.png` 与掩码 `e9m_*.png` **都放在 `ComfyUI\input` 根目录**（子目录 ComfyUI 读不到）
- [ ] `subzones.json` 每个部位 3 段、每段 4–9 条
- [ ] `--ref-labels` / `--image` / `--ref-query-mask-por` **三者顺序一一对应**

**画布侧（0 / 1 / 2）**
- [ ] 新姿势深度图四角全 `0`（`depth_to_mask.py` 的 `四角(刷后)`）
- [ ] 过渡图裤子有明显鼓包（不是直筒）
- [ ] 过渡图 11 色全中
- [ ] 色图 8–10 区、面积合理，**无头纱被染色**（色相边界切错会让 `veil` 变色）
- [ ] 小件（shoes / sash_point）已手工填区域
- [ ] 第二深度图四角全 `0`、带服装体积

**精修侧（3）**
- [ ] `--ref-query-mask-por` 用的是 **`cvm_*.png`（画布坐标）**，不是 `e9m_*.png`
- [ ] `--control-strength 0.9` / `--control-end 1.0` / `--image-strength 0.5`
- [ ] 主 prompt 是五块结构，首句有 `plain flat pure white empty background … no props, no panels, no floating objects`
- [ ] `<|constraints|>` 含 `Do not draw any of these parts as separate objects beside the figure`
- [ ] region prompt 8 条**都带位置前缀**，且形状（`trunk`）在前、细节在后
- [ ] 负向含 `picture in picture, collage, reference sheet, inset, close-up panel, isolated ornament, floating object`
- [ ] 出图后检查两个角落：右上角（拼贴）应 < 1%，左上角（装饰线）应 < 25%

---

## 七、出问题时

| 症状 | 原因 | 修法 |
|---|---|---|
| **右上角多出一个巨大饰件** | `orb` 没写位置 | 加 `hanging at her left hip ... never floating or shown alone` + 负向 |
| **头纱被画成胸衣的颜色** | `veil` 合进了 `bodice` 色区 | 头纱留中灰 |
| **裤子是紧身裤** | 过渡图 control 太高 / 深度图轮廓本身偏窄却没写出服装宽度 / 负向缺 `tight fit` | 用 `0.6`；prompt 里补「桶形 + 全程宽 + 只踝部收」三句；负向加 `tight fit, skinny pants, leggings` |
| **前片被放大成一大块矩形** | 没写 `narrow in width` + 色区太小 | 加位置前缀，或手工填色块 |
| **画面左右各多一条装饰带** | 深度图背景没刷黑 | 见第 0 步（`tools\depth_to_mask.py`） |
| **多个人 / 角色设定图** | 降了 `--depth-strength` | 不要降 depth，降的是 `--control-strength` |
| **右上角出现胸衣特写 / 整条腿 / 挂坠簇（拼贴）** | ① `--control-strength` 上了 1.0（0.9→25.4%，1.0→**73.4%**）② `--image-strength` 太高（1.0→25.4%，0.5→4.3%）③ 主 prompt 缺 `<|constraints|>` 那段 | 控制参数压到 `0.9 / end 1.0` + `--image-strength 0.5`；主 prompt 补 `Do not draw any of these parts as separate objects beside the figure`；负向加 `picture in picture, collage, reference sheet, inset, close-up panel` |
| **左上角一片金色装饰线** | 主 prompt 没说「空白背景」 | 首句写 `alone on a plain flat pure white empty background with nothing else in the frame, no props, no panels, no floating objects`（实测 39.54%→21.37%） |
| **纹样传不过来（裤腿只有 1–2 个菱形）** | 掩码用错了坐标系 | 掩码是**画布坐标**（`moss_ref_mask.py:65-66` 原文），必须从新姿势色区反推 `cvm_*.png`，不能用参考侧的 `e9m_*.png` |

---

## 八、案例

**四星2 冰蓝舞娘：站姿 → 跪姿**

**取料侧（参考图 `C:\MOSS-Deploy\ComfyUI\input\v2sop_ref.png`）**

| 文件 | 说明 |
|---|---|
| `C:\MOSS-Deploy\work\parts_all.json` | A 步产物：11 个部位的 trunk + details |
| `C:\MOSS-Deploy\work\picked9.json` | A1 步产物：8 个选中部位 |
| `C:\MOSS-Deploy\ComfyUI\input\e9_*.png` / `e9m_*.png` | A1 步产物：8 张裁片 + 8 张掩码 |
| `E:\DSH-MOSS工作区\work\sop3\subzones.json` | A2 步产物：8 部位 × 3 段的反写 |

**画布侧与定稿**

| 文件 | 说明 |
|---|---|
| `s3_depth_clean.png` | 新姿势深度图（`depth_to_mask.py` 的 `_black` 输出，四角 0） |
| `s3_t2_00001_.png` | 过渡图（`control 0.6 / end 0.6`，1.00 min，11 色全中、裤子有鼓包） |
| `s3_cm4.png` | 色图（8 区，中灰底 49.34%）——案例一用 8 区；案例二扩到 10 区 |
| `s3_depth2_clean.png` | 第二深度图（带服装体积，浅阈值刷黑） |
| `rp_s3_v3.txt` | 8 条 region prompt（6966 字符，带位置前缀） |
| `s3_v4_00001_.png` | 定稿（0.93 min，8 步 fast seed 9001） |

**定稿达到的**：跪姿正确；裤色浅蓝→裤脚深蓝渐变；金竖条纹出现；前片是金框蓝色面板、位置居中；`orb` 压在腰带右侧；头纱青色；右上角无独立饰件。
**定稿没达到的**：鞋仍是深灰圆头；金竖条纹只有 1–2 条（要求 6）。

---

### 案例二：站姿 → standing split（2026-11-12，把五块结构与三个新参数定下来）

**参考图**：同上（`v2sop_ref.png`，8 裁片 `e9_*.png` / `e9m_*.png` 直接复用）。
**新姿势**：`full_sexy_P008_front_depth.webp`（900×1200）——左腿高举过头、左手扶小腿、右臂侧伸、右腿单腿站立。

**五个环节的产物**

| 环节 | 文件 | 关键点 |
|---|---|---|
| 第 0 步 | `s4_black.png`（`depth_to_mask.py` 输出） | Otsu `118.0`、地面过滤 `y>=1403` 把 `448797→275652`、人物 **11.79%**、bbox `x 211-1006 y 84-1498`（两只脚都在）、四角全 0 |
| 第 1 步 | `s4_t2_00001_.png` | `--control-strength 0.6 --control-end 0.6`，0.24 min；抬腿裤管在髋与大腿堆厚褶、站立腿下坠堆褶、红披风滑落、11 色全中 |
| 第 2.1 步 | `s4_cm.png`（10 区） | `leggings 8.05%` / `drape 6.20%` / `veil 1.25%` / `sash_point 0.91%` / `bodice 0.85%` / `sleeve_r 0.84%` / `sash 0.60%` / `sleeve_l 0.52%` / `shoes 0.42%` / `orb 0.23%`，中灰底 80.12% |
| 第 2.2 步 | `s4_depth2.png` | `depth_from_image.py`（**位置参数** `sys.argv[1]`/`[2]`）+ 浅阈值刷黑，四角 0 |
| 第 3 步 | `s4_v17_v14plus_00001_.png` | 1.30 min；`0.9 / end 1.0 / image-strength 0.5`；五块 prompt + region 前形状后细节 |

**色图的四个坑（HSV 分区时必踩）**

| 坑 | 现象 | 修法 |
|---|---|---|
| 头纱与绿裤色相接近 | `veil` H≈170、`leggings` H≈152，切在 168 会把头纱染成洋红 | `leggings` 切 136–163、`veil` 163–195 |
| `sash_point` 棕色被披风抢 | 棕色 S=58% 低于 `drape` 的 `smin 0.50` | `sash_point` 排在 `drape` **之前**，并限 `vmax 0.48` |
| `shoes` 与披风亮部撞色 | H=342 落在 drape 的 340–15，V 也高 | **只能用位置框** `box[30:240,195:300]` + `box[1430:1545,430:545]`，否则红色铺满披风褶皱（7.14% → 0.40%） |
| `veil` 太透明 | 只抓到边缘 | 主体交给主 prompt，色区只做弱提示 |

**提示词三轮对比（这是本节最重要的表）**

| 版本 | prompt 结构 | 边缘强度 | 右上角拼贴 | 左上角装饰 | 裤腿区 |
|---|---|---|---|---|---|
| 单行 prompt | 一行交代姿势 + 服装全靠 region | 6.42 | 4.33% | 43.85% | **70.2%** |
| 五块 + tag 在 region | tag 只在主 prompt 引出，位置+形状+细节全在 region | 5.66 | **0.19%** | 39.54% | 68.0% |
| 五块 + tag 全在全局 | region 只留 details | 5.94 | 11.84% | — | 69.3% |
| **五块 + 全局补位置 + 白底声明**（定稿） | 上版基础上每个 tag 在全局也写明位置，首句锁白底 | 5.39 | **0.00%** | **21.37%** | 65.1% |

**读法**：
- **拼贴**靠两件事压——`<|constraints|>` 那句 `Do not draw any of these parts as separate objects`（4.33% → 0.19%）+ `--image-strength 0.5`
- **左上角装饰线**靠首句 `plain flat pure white empty background … no props, no panels, no floating objects`（39.54% → 21.37%）
- **代价**是裤腿细节从 70.2% 降到 65.1%——干净度和纹样密度是此消彼长的

**定稿达到的**：单人、金发、standing split 姿势准确、白底干净（右上 0.00% / 左上 21.37%）、水彩手绘质感、披风滑落与裤管堆褶的形变正确。
**定稿没达到的**：裤腿只有 1 菱形 + 1 星形（要求 4 菱形 + 3 花饰 + 6 金竖纹）；鞋仍深灰。

---

### 案例二的 24 步档（2026-11-12，git 示例用）

同一套深度图、同一批裁片，第 3 步改 `--no-fast --steps 24 --cfg 3.5`（4.36 min）。**四版对比**：

| 版本 | `legs` 的 trunk | 边缘强度 | 左上角 | 裤腿 RGB | vs 参考 |
|---|---|---|---|---|---|
| 8 步 fast（对照） | 原文含 `sheer fabric` | 5.39 | 21.37% | (129,167,185) 蓝 | 133.00 |
| 24 步 原文 | 原文含 `sheer fabric` | 6.51 | 18.34% | (175,181,182) **灰白** | — |
| 24 步 opaque | 去掉 `sheer`，补「不透明」 | 5.96 | 18.41% | (70,104,140) **深蓝** | 133.42 |
| **24 步 pale（定稿）** | 上一条 + `in pale ice-blue fabric that fades into a deeper blue` + `matte` + `the overall value stays light` | **6.48** | **18.34%** | **(165,192,193) 浅蓝** | **132.71** |

**三条**：
1. **24 步会把 `sheer` 放大成完全透明**，8 步看不出来。必须改 trunk。
2. **提高 `--image-strength`（0.5→0.7→0.85）无效**，两版与 0.5 几乎一样。
3. 修好之后 24 步全面更优：边缘 +20%、左上角 21.37%→18.34%、vs 参考 133.00→132.71，代价是耗时 0.24→4.36 min。

完整产物见 `examples\SOP-3-20261112-四星2-standing-split\`（README 有逐档数据与文件清单）。
