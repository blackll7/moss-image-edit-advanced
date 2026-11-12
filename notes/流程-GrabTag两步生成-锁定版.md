# 流程 · GrabTag 两步生成（锁定版）

> **每次做 GrabTag 生成前必须先读这份。** 2026-11-10 19:32 锁定，19:55 补工具链。
> 上下文会丢，本文自足：参数、工具、提示词规则、量化数据、判据全在这里。
> 详细实验记录见 `notes\2026-11-10-路线-两步生成-过渡图提取色图与深度图.md`。
>
> ---
>
> **⚠️ 2026-11-11 重要变更：GrabTag 本身已重建，本文只保留「两步生成」这部分。**
>
> 本文原来把 GrabTag 当成「用 `--color-map` 分区引用的东西」，**那是错的**。GrabTag 的标注在**参考图**上，落点是参考侧通道：
>
> ```
> --ref-query-mask-por  （每块裁片一张画布掩码）
> --ref-labels          （每块裁片一个 tag 名）
> prompt: Her waist is wrapped in <sash>.   （反向指派）
> ```
>
> **GrabTag 机制看 `notes\机制-GrabTag-当前实现.md`**（含四臂实测：vs参考 121.13，优于整图参考的 127.80）。
> 本文里凡是「不传 `--image` / 不传 `--color-map`」的说法，指的是**两步生成的第一步**（过渡图阶段），与 GrabTag 无关，仍然有效。

---

## 0. 一句话

**本文是 A+B 路线的完整流程：纯 T2I 造一张「穿着目标服装的人」→ 从中提取色图与第二深度图 → 交给 A+B 链生成目标图。**

色图与深度图同源同尺寸（1216×1632），位置天然对齐，绕开「色图位置与人体不匹配」和「色图色彩污染生成图」两个老问题。

> **如果你只是要复刻参考图或改它的动作，不要走这条**——用 §0.5 里的「单 A 主路线」，0.7–1.0 min、四 seed 全过。

---

## 0.5 先选路线：单 A 还是 A+B

**开工前先回答一个问题：这次要「换动作」还是「换姿势/换构图」？**

| | **单 A 主路线** | **A+B 两步生成（本文件）** |
|---|---|---|
| 要做什么 | 复刻一张参考图，或只改它的动作 | 换姿势、换构图、换视角 |
| 深度图 | **参考图自己提的那张**（同源） | 目标姿势的深度图（异源） |
| 色图 | 不用 | 要（第二步） |
| 参考图 | latent 直传（7752 tok） | 也是 latent，但被 control 挤到次席 |
| 提示词 | `--tags tags_v3_real.json` | A 链 tags + B 链 11 段 region prompt |
| 命令 | `moss_main.py --card --pose --tags --ref-no-pos 1` | 三步（过渡图 → 提色图/深度 → A+B） |
| 耗时 | **0.7–1.0 min** | 1.4–4.9 min |
| 稳定性 | **四 seed 全过**（参考影响 14.06–15.29） | 单 seed 验证（AB3/AB4） |
| 详细文档 | `notes\路线-单A复刻-参考图直接复刻与提示词微调.md` | **本文件** |

**一句话判据：**

- 参考图的姿态能用、只想改细节或动作 → **单 A**
- 参考图的姿态不能用、要换成别的姿势 → **A+B**

**两者的共同前提**：参考图的服装信息要先被翻译成「色图 + 描述」（A+B）或「tag + latent」（单 A）。**参考图不能直接当唯一条件用**——那是今天六条失败路径的共同死因。

---

## 1. 流程图

```
参考图（服饰类型 + 量化尺寸）─┐
                                ├─→ ① 过渡图（纯 T2I，英文色名，无参考无色图）
原始深度图（姿态）─────────────┘        │
                                        ├─ 颜色距离分割 ─→ ② 色图（贴边，无矩形）
                                        └─ Depth-Anything ─→ ③ 第二深度图（带服装体积）
                                                              │
参考图 11 条 ref_tag ───────────────────────────────────────────┤
                                                              ▼
                                                    ④ A+B 链 → 目标图
```

---

## 1.5 工具链（每一步用哪个工具）

**`$py` = `C:\MOSS-Deploy\venv\Scripts\python.exe`。路径一律用绝对路径。**

| 环节 | 工具 | 路径 | 用途 |
|---|---|---|---|
| 看参考图写了什么 | `reverse_prompt.py` | `E:\DSH-MOSS工作区\tools\reverse_prompt.py` | 把图反写成中文描述（qwen3-vl-plus）。**核对装饰是否传到生成图时必须用它**，`mean\|diff\|` 不可信 |
| **提色图** | **`extract_colormap.py`** | **`E:\DSH-MOSS工作区\tools\extract_colormap.py`** | **从过渡图按调色板提取色图**（内联版已固化，逐字节一致） |
| **GrabTag 切裁片** | **`describe_parts.py`** | **`E:\DSH-MOSS工作区\tools\describe_parts.py`** | **按人体部位切参考图 + 逐块反写**（trunk / details 分离），产物 `work\parts_all.json`。**GrabTag 的裁片和描述都从这里来** |
| 造贴边色图（旧路，已废） | grabtag CLI | `C:\MOSS-Deploy\publish\grabtag\grabtag\core\region_caption.py` | 从参考图按 spec 分割贴边色块。**GrabTag 重建后不再使用**（它产出的是色图，属于生成图侧） |
| 生成 | `moss_run.py` | `C:\MOSS-Deploy\moss_run.py` | 唯一底层入口，所有参数都在这 |
| 生成（A 链封装） | `moss_main.py` | `C:\MOSS-Deploy\moss_main.py` | `--tags tags.json` 自动拼 `build_prompt`；`--dry-run` 可先看命令 |
| 色调色板 | `palette11.json` | `C:\MOSS-Deploy\work\palette11.json` | 11 件的 `id` / `colour`（英文色名）/ `rgb` / `hex`，最小色差 57.8 |
| 提深度 | `depth_from_image.py` | `C:\MOSS-Deploy\work\depth_from_image.py` | Depth-Anything-V2-Small，近=亮；需 `$env:HF_ENDPOINT='https://hf-mirror.com'` |
| 反写成品图 | 同上 `reverse_prompt.py` | — | 产 `notes\reverse\<stem>__<sha8>.md`，按 sha 缓存，`--force` 重跑 |
| 服务 | ComfyUI | `C:\MOSS-Deploy\start-comfyui-moss-8190.bat` | 端口 8190；`-UseNewEnvironment` 会丢 `$env:`，继承环境时**不要加** |

**中间文件约定**

| 文件 | 位置 |
|---|---|
| 过渡图 | `ComfyUI\output-moss\trans<N>_00001_.png` |
| 色图 | `C:\MOSS-Deploy\work\trans<N>_cm.png` → 拷 `ComfyUI\input\cm_trans<N>.png` |
| 第二深度图 | `C:\MOSS-Deploy\work\trans<N>_depth.png` → 拷 `ComfyUI\input\dep_trans<N>.png` |
| A 链 tag 串 | `C:\MOSS-Deploy\work\_prompt_achain.txt` |
| B 链区域提示词 | `C:\MOSS-Deploy\work\_region_trans<N>.txt`（一行一段） |
| 定稿副本 | `E:\DSH-MOSS工作区\out\2026-11-10_*.png` |

**两条容易被忽略的环境事实**

- `moss_run.py` / `moss_main.py` 用**相对路径**会解析到当前 cwd（可能是 `E:\DSH-MOSS工作区`），**一律用绝对路径**
- Python 脚本打印中文/✅ 到 GBK 控制台会 `UnicodeEncodeError`；脚本开头加 `sys.stdout.reconfigure(encoding="utf-8")`

---

## 1.6 步数三档

| 档 | 参数 | 实测耗时（两步合计） | 用途 |
|---|---|---|---|
| **测试/草稿** | `--steps 8 --cfg 1.0 --fast` | **1.4 min** | **默认档：试参数、试提示词、找方向（2026-11-10 用户定：日常测试都用 fast）** |
| **中间** | `--steps 24 --no-fast --cfg 3.5` | **4.9 min** | 需要看清细节层次时才用 |
| **成品** | `--steps 50 --no-fast --cfg 3.5` | 未跑 | **最终交付用，2026-11-10 定，尚未验证** |

**8 步 vs 24 步实测（同一 seed、同一色图/深度图）**：

| | AB3（8 步） | AB4（24 步） |
|---|---|---|
| 姿态 | 正确 | 正确 |
| 灯笼裤 | 鼓，实心布料 | 鼓，**半透明薄纱质感** |
| 披风装饰 | 稀疏菱形 | **完整宝石挂饰链**（菱形蓝宝石 + 金框 + 红珠 + 流苏） |
| 非白占比 | 43.2% | **52.1%** |
| luma std | 71.8 | **81.9** |
| 两图 `mean\|diff\|` | — | 29.52 |

**重要**：`--fast` 会把 steps 压回 8、cfg 压到 1.0。**用 24/50 步必须同时写 `--no-fast --cfg 3.5`**，否则白设。

**之前经验卡记着「24 步会转水彩颗粒」，这次没出现**——因为前面有过渡图给的色图 + 第二深度图，约束更强。**过渡图不只是提供形状，还把高步数的生成力导向细节。**

---

## 2. 第一步：过渡图

### 参数

```powershell
& $py 'C:\MOSS-Deploy\moss_run.py' --port 8190 `
  --depth-map 'C:\MOSS-Deploy\ComfyUI\input\<原始深度图>' `
  --control-strength 0.6 --control-end 0.4 `
  --w 1216 --h 1632 --steps 8 --cfg 1.0 --fast --seed 9001 --edit-format ai-toolkit `
  --negative 'worst quality, bad anatomy, watermark, jpeg artifact, sheer fabric, transparent, gradient, pattern' `
  --prompt $main --prefix trans<N>
```

**三个"不"**：不传 `--image`、不传 `--color-map`、prompt 不写装饰细节。

### control 参数：`strength 0.6 / end 0.4`（2026-11-10 19:41 定）

**为什么不是降 strength**：`strength` 只改「多强」，`end` 才改「在采样的哪一段施加」。节点原生说明（`nodes_moss_image.py:71`）写着 **"Ending early keeps the layout and depth while the rest of the steps loosen the shapes"**——提前结束控制会保留布局与深度，剩下的步骤放松形状。

四档实测（1216×1632 / 8 步 fast / seed 9001）：

| strength | end | 结果 |
|---|---|---|
| 0.6 | 0.6 | 单人、姿态正确、**裤子扁**（trans5） |
| 0.4 | 0.6 | 单人、裤子很鼓、**姿态丢**（trans6，正面站姿） |
| 0.5 | 0.6 | **画出两个人**（trans7） |
| **0.6** | **0.4** | **单人、姿态正确、裤子鼓**（trans8）✓ |

**降 strength 会让模型整体自由发挥，容易画错人数或姿态。不要用它调形状。**

详见 `notes\机制-control三参数-strength-start-end.md`。

### 提示词规则（全部有实测依据）

**① 颜色只用英文色名，绝不用 hex**

`#cfe6f2` 只是区域 ID，模型不会把它当颜色；`pale turquoise` 才是填色指令。trans4 用 6 个色名、trans5 用 11 个色名，全部命中；trans1d 用 hex，全部失败。

**② 11 色调色板（`palette11.json`）**

| id | 色名 | hex |
|---|---|---|
| hair | golden yellow | `#d4a73a` |
| veil | pale turquoise | `#9fe8e0` |
| sleeve_r | sky blue | `#3e9be0` |
| sleeve_l | navy blue | `#203060` |
| bodice | violet | `#8b4bb5` |
| sash | orange | `#e8781e` |
| orb | silver | `#b8bcc4` |
| drape | crimson red | `#b02a3c` |
| sash_point | dark brown | `#5a3a2a` |
| legs | deep green | `#2e8b3a` |
| shoes | hot pink | `#e04a96` |

最小色差 57.8（所以分割阈值可以用 55）。初版 `sleeve_l` 用 bright cyan，与 sky blue 只差 47.0，换成 navy 才过。

**③ 每件只写「形状 + 长度 + 量化尺寸」，不写装饰**

装饰（菱形、宝石、金链）写了反而让形状跑偏（trans1d 实证）。

**④ 关键部件必须给量化尺寸，并明确要求突破轮廓**

参考实测（从 `reg_ice3_seedtest/cm.png` 贴边色图量得）：

```
人物 bbox：x 151–1055（宽 905px）  y 20–1556（高 1537px）

裤腿宽度（占身高）：
  上 25% (y=919)   436px  28.4%
  中 50% (y=1105)  499px  32.5%
  下 75% (y=1290)  423px  27.5%
  最宽处 (y=1094)  503px  32.7%

腰宽（sash 最宽）  328px  21.3%

>>> 裤腿最宽 / 腰宽 = 1.53 倍
>>> 裤腿最宽 / 人体总宽 = 0.56 倍
```

**裤子 prompt 必须写成：**

```
deep green trousers, loose and baggy, their widest point at mid-thigh measuring
one and a half times the waist width, the fabric bulging outward well past the
leg silhouette on both sides, then gathered tight at the ankle
```

**⑤ 材质写死 `solid opaque`，负向加 `sheer fabric, transparent`**

否则裤子是薄纱，提深度时透出皮肤。

**⑥ 完整主 prompt 模板**

```
a woman standing in a plain white background, full body, hand-drawn anime illustration,
wearing solid opaque clothing: <每件：形状+量化尺寸+in+色名，用分号隔开>
```

---

## 2.5 第二步：完善提示词（grounding 聚焦 → 逐块反写）

**目标**：`--region-prompt` 每段要有足够细节密度。整图反写会把 11 件揉成一团，必须先定位、再裁、再单块反写。

### 工具

| 脚本 | 作用 |
|---|---|
| `tools\ground_regions.py` | 用 `qwen3-vl-plus` 做 2D grounding，把参考图按 11 件裁出来，存 `grounding.json` |
| `tools\describe_crops.py` | 对每块裁剪图单独反写，产出 `_region_detailed.txt` |

**`Nynxz/ComfyUI-NynxzExperimental` 的 Qwen3-VL Ground 节点不用装**：它是给 Fusion 管线用的（需要 Qwen3-VL CLIP + fusion encode），我们的 MOSS 不走那条管线。grounding 能力用 DashScope 的 `qwen3-vl-plus` 直接问即可，效果一样。

### 命令

```powershell
& $py 'E:\DSH-MOSS工作区\tools\ground_regions.py' `
  --image 'C:\MOSS-Deploy\ComfyUI\input\<参考图>.png' `
  --outdir 'C:\MOSS-Deploy\work\grounded'

& $py 'E:\DSH-MOSS工作区\tools\describe_crops.py' `
  --indir 'C:\MOSS-Deploy\work\grounded' `
  --out 'C:\MOSS-Deploy\work\_region_detailed.txt'
```

### 坐标顺序的坑（必读）

Qwen3-VL 官方约定 `box_2d` 是 `[ymin, xmin, ymax, xmax]`，**但实测返回的是 `[xmin, ymin, xmax, ymax]`**。按官方顺序解析会裁出一片空白（第一次跑 `hair` 就是这样）。

**正确做法**：用中文提问，并在 prompt 里显式写 `{"box_2d": [xmin, ymin, xmax, ymax]}`，再按这个顺序解包。脚本里已经这样写死。

### 已知的定位缺陷

- `sleeve_r` 与 `sleeve_l` 返回同一个框（模型不区分左右）——需要时手动改 `grounding.json`
- `bodice` 与 `veil` 的框高度重叠（衣物层叠，边界本身模糊）

### 关键规则：量化廓形必须手写补回

**grounding 的描述是「观察性」的，没有数字**。它写「最宽处在大腿中部」，模型不知道要宽到什么程度——AB5 实测裤子又变紧身。

**所以 `legs` 那段必须在 grounding 描述前加量化句**：

```
the #2e8b3a area is loose baggy trousers whose widest point at mid-thigh measures
one and a half times the waist width, the fabric bulging outward well past the leg
silhouette on both sides, then gathered tight at the ankle; <grounding 描述原文>
```

AB6 实测：加了这句，裤子从紧身变回灯笼裤（AB5 vs AB6 = 7.47，只改了这一段）。

**同理，任何「廓形」类要求都不能只靠 grounding 描述。**

### 段落格式与顺序

- 一行一段：`the <hex> area is <描述>`
- **顺序必须与 A 链 tag 顺序一致**（`describe_crops.py` 已按 palette 顺序排序）
- 11 段合计 2300–2500 字符

---
## 3. 第二步：提取色图与深度图

### 色图（颜色距离分割）

```powershell
& $py 'E:\DSH-MOSS工作区\tools\extract_colormap.py' `
  'C:\MOSS-Deploy\ComfyUI\output-moss\trans<N>_00001_.png' `
  --palette 'C:\MOSS-Deploy\work\palette11.json' `
  --out 'C:\MOSS-Deploy\work\trans<N>_cm.png' --stats

Copy-Item 'C:\MOSS-Deploy\work\trans<N>_cm.png' 'C:\MOSS-Deploy\ComfyUI\input\cm_trans<N>.png' -Force
```

**脚本内部三条规则**（已固化，逐字节复现过内联版）：

1. **最近邻 + 阈值 55**。palette11 最小色差 57.8；阈值 70 会把白背景吃进 silver。
2. **白背景先排除**：`bg = min(RGB) > 238`。
3. **肤色规则必须带 `rb<110`**：`skin = (R>150)&(G>110)&(B<200)&(rb>35)&(rb<110)`。金发 `#d4a73a` 的 R−B≈154，不加这个上限会被当肤色吃掉（第一次跑 hair 占 0.00% 就是这个原因）。

**`--stats` 打印的区域占比是判断过渡图质量的第一手数据**：某区过小 = 那个颜色没画出来，过大 = 溢出了。

### 深度图

```powershell
$env:HF_ENDPOINT = 'https://hf-mirror.com'
& $py 'C:\MOSS-Deploy\work\depth_from_image.py' `
  'C:\MOSS-Deploy\ComfyUI\output-moss\trans<N>_00001_.png' `
  'C:\MOSS-Deploy\work\trans<N>_depth.png'

Copy-Item 'C:\MOSS-Deploy\work\trans<N>_depth.png' 'C:\MOSS-Deploy\ComfyUI\input\dep_trans<N>.png' -Force
```

内部 `depth-anything/Depth-Anything-V2-Small-hf`，HF 走 `hf-mirror.com`，输出「近=亮」。

---

## 4. 第三步：A+B 链

### 参数

```powershell
$ap = (Get-Content 'C:\MOSS-Deploy\work\_prompt_achain.txt' -Raw -Encoding UTF8).Trim()
$rp = Get-Content 'C:\MOSS-Deploy\work\_region_trans<N>.txt' -Encoding UTF8 | Where-Object { $_.Trim() }

$a = @('C:\MOSS-Deploy\moss_run.py','--port','8190',
  '--image','v2sop_ref.png:raw',
  '--color-map','cm_trans<N>.png',
  '--depth-map','C:\MOSS-Deploy\ComfyUI\input\dep_trans<N>.png',
  '--control-strength','0.6','--control-end','0.6',
  '--w','1216','--h','1632','--steps','8','--cfg','1.0','--fast','--seed','9001',
  '--edit-format','ai-toolkit','--ref-no-pos','1',
  '--negative','worst quality, bad anatomy, watermark, jpeg artifact',
  '--prompt',$ap,'--prefix','AB<N>')
foreach ($line in $rp) { $a += @('--region-prompt', $line) }
& $py @a
```

**第二步用 `end 0.6`（默认）**，不是 0.4——它的深度图已经带服装体积，不需要再放开形状；放开反而丢姿态。

### 两个提示词文件怎么来

**`_prompt_achain.txt`**（A 链）：跑一次 `moss_main.py --dry-run`，把它打印的 `prompt:` 整段抄下来。

```powershell
& $py 'C:\MOSS-Deploy\moss_main.py' --card 'v2sop_ref.png' --pose 'v2sop_depth.png' `
  --tags 'C:\MOSS-Deploy\work\reg_ice3\tags_v3_real.json' --size '1216x1632' --seed 9001 --dry-run
```

**`_region_trans<N>.txt`**（B 链）：一行一段，色图有几个颜色写几段，格式 `the <hex> area is <该件的 ref_tag>`，11 段共约 1300 字符。

> **2026-11-11 起，A 链的 `--prompt` 变成逐实体保留声明**（`<Item N — 标签> is fully/partially preserved: …`），从 `moss_main.py --dry-run` 抄出来的就是新格式。生成方式与保留级别判据见上一节。

### 提示词双层，必须一一对应

**A 链（`--prompt`）** = `moss_main.py` 的 `build_prompt` names 模式——**2026-11-11 起默认是逐实体保留声明**：

```
Picture 1 is the character card, one woman shown front-on, full body in frame.

<Item 1 — the loose baggy trousers> is fully preserved: <legs 的 ref_tag>
<Item 2 — the deep indigo hanging panel> is partially preserved; its shape and
  ornament stay as drawn, but its exact position may adapt to the pose: <drape 的 ref_tag>
… 共 11 条
```

（变更原因与实测见 `notes\2026-11-11-经验-逐实体保留声明.md`；旧格式是 `Keep exactly these parts of her design: <tag1>; <tag2>; …` 一句话平铺，会让腰带菱形网格这类细节被整体语义吞掉。）

**B 链（`--region-prompt` × 11）**：

```
the #d4a73a area is <hair 的 ref_tag>
the #9fe8e0 area is <veil 的 ref_tag>
… 共 11 段，顺序与 A 链 tags 完全一致
```

**一一对应是硬要求**：颜色 ↔ tag ↔ 色图区域，三者顺序必须相同。

**B 链是否也加保留级别（2026-11-11，已实测：无效）**：B 链的 region prompt **已经天然是按区域分段的**（每区一句），「分段」这一半它已经有了，缺的只是「保留级别」。**实测加了没用**——`bch_ent vs bch_base = 4.43`（噪声级），反写互有胜负无一致改善；随后又试了「块内分层描述」（8.99）和「拆色区四段」（9.61），**三条都失败，纹样照样不落地**。

**结论：`preserve` 字段只在单 A 的 `build_prompt` 里有用，B 链不要加。** 根因是**色图/深度图/region prompt 三个通道里没有高频信息**，参考 latent 才是唯一能传纹样的通道，而 B 链为了换姿势把它压到 8–14。完整证据与三条出路见 `notes\2026-11-11-经验-B链传不了纹样.md`。

**B 链的定位**：控制**形状与位置**（灯笼裤的鼓、银球的圆、披风走向、腰带高低、鞋的尖），**不负责纹样**。纹样要先在单 A 里做到满意，再用它当参考做 A+B，或出图后 `--region-edit` 局部重绘。

实测 AB1（只有 B 链 7 段、`--prompt` 极简）→ 裤腿菱形全无、胸衣简化；AB2（A 链 11 条 + B 链 11 段）→ 装饰密度回来。

### A+B 四条铁律

1. `--image` **必须带 `:raw`**（否则参考副轴缩到 384）
2. **必须加 `--ref-no-pos 1`**（否则参考锁布局、深度不接管姿态）
3. **`--edit-format ai-toolkit`** + `--fast`（8 步 cfg 1.0）
4. **不要加 `--region-concat`**（实测拼接胜出；concat 会把整体配色拆散：两腿不同色、披风分两层）

---

## 5. 当前状态

**两条路线，各自的最优点不同，不要混用参数。**

| 环节 | 状态 |
|---|---|
| **单 A 主路线** | ✓ **四 seed 全过**（参考影响 14.06–15.29、左右比 0.43–0.50、细节 4/4 一致），见 `notes\路线-单A复刻-参考图直接复刻与提示词微调.md` |
| 过渡图 11 色 | ✓ 颜色全部命中；`sleeve_l`(navy) 仍偏大（trans9 占 8.93%）、`bodice`(violet) 偏小（1.36%） |
| 色图提取 | ✓ 11 区全部提取；脚本已固化 |
| 第二深度图 | ✓ 带服装体积（trans9 裤腿 40.6% 身高，参考 32.7%） |
| control 参数 | ✓ **第一步 `0.6/0.4`、第二步 `0.6/0.6` 已定**；单 A 主路线用 `0.6/0.6`（同源深度只锁布局） |
| A+B 链 | ✓ **AB3（8 步）与 AB4（24 步）均同时保住形状与装饰**（单 seed） |

**下一个待优化**：`sleeve_l` 在过渡图里溢成大袖片（8.93%）、`bodice` 只占 1.36%、`shoes` 在 trans9 只 0.03%。改提示词限制袖子长度与上衣边界。

**A+B 还没做过多 seed 复验**——单 A 已经四 seed 全过，A+B 只有单 seed（AB3/AB4）。**投入生产前建议先跑 9002/9003。**

---

## 6. 执行清单

### 6.A 单 A 路线（复刻 / 改动作，0.7–1.0 min）

- [ ] 参考图放进 `ComfyUI\input\`
- [ ] `depth_from_image.py <参考图> <参考图名>_depth.png`（**必须同源**）
- [ ] 深度图也拷进 `ComfyUI\input\`
- [ ] `moss_main.py --card <参考图> --pose <参考图名>_depth.png --tags tags_v3_real.json --ref-no-pos 1`
- [ ] 验收：单人物？单视角？细节对上？（左右比 < 0.6 即单主体）

### 6.B A+B 路线（换姿势，1.4–4.9 min）

**第一步**
- [ ] 读 `palette11.json`，确认 11 色
- [ ] 主 prompt 写 `wearing solid opaque clothing`
- [ ] 每件只写形状+长度，裤子写死「1.5×腰宽 + past the leg silhouette」
- [ ] 颜色只用英文色名
- [ ] **`--control-strength 0.6 --control-end 0.4`**
- [ ] 不传 `--image` / `--color-map`

**第二步**
- [ ] `extract_colormap.py --stats`，看每个区域占比
- [ ] 某区为 0 → 回第一步改提示词
- [ ] `depth_from_image.py` 提深度
- [ ] 两个产物都拷进 `ComfyUI\input\`

**第三步**
- [ ] `--prompt` 用 `_prompt_achain.txt` 全文
- [ ] `--region-prompt` 段数 = 色图颜色数
- [ ] `--image ...:raw` + `--ref-no-pos 1` + `--edit-format ai-toolkit`
- [ ] `--control-strength 0.6 --control-end 0.6`
- [ ] 不加 `--region-concat`

**验收（两条路线通用）**
- [ ] 姿态五线索逐条指认（前倾 / 双手 / 臀 / 腿分前后 / 重心）
- [ ] 用 `reverse_prompt.py` 反写，按「部位+数量+形态」核对装饰
- [ ] **不要用 `mean|diff|` 判细节**（AB3 vs V3 只有 3.31，但细节差很多）

---

## 7. 常见故障对照

| 现象 | 原因 | 修法 |
|---|---|---|
| 过渡图颜色全不对 | 用了 hex | 改英文色名 |
| 过渡图是原来那套配色 | 挂了 `--image` | 去掉参考 |
| 深度图里透出皮肤 | 材质没写死不透光 | 主 prompt 加 `solid opaque`，负向加 `sheer fabric` |
| 色图某个区域 0.00% | 被肤色规则吃掉 | 肤色规则加 `rb < 110` |
| 色图大半是 silver | 白背景被当银色 | 加 `bg = min(RGB) > 238` 排除 |
| 最终图装饰稀 | 只有 B 链没 A 链 | `--prompt` 用 `build_prompt` 原样 |
| 最终图姿态不跟深度 | 没加 `--ref-no-pos 1` | 加上 |
| 最终图配色被拆散 | 加了 `--region-concat` | 去掉 |
| **衣服贴身 / 不够鼓** | **`end` 太大，控制持续到后期** | **`--control-end 0.4`** |
| **姿态跑 / 画错人数** | **`strength` 太低或 `end` 太小** | **strength 提到 0.6、end 不低于 0.4** |
| OOM | 系统内存不足 | 关程序；服务刚重启时内存最干净 |

**单 A 路线专属故障**

| 现象 | 原因 | 修法 |
|---|---|---|
| **画出两个视角 + 配饰分解（角色设定图）** | 缺 `--pose`，或深度图与参考不同源 | 用参考图自己提的深度图，且带上 `--pose` |
| **画出两个人** | 深度图不同源（control 与参考抢主体） | 换同源深度图 |
| 细节稀疏（腰侧一坨花饰） | 缺 `--tags` | 加 `tags_v3_real.json` |
| 提示词改不动 | 缺 `--ref-no-pos 1` | 加上 |
| 改画风没反应 | 参考 latent 主导 | **正常现象**，单 A 改不了画风；要改画风走 Seedream 路线（反写成文本） |

---

## 8. 产物命名

- 过渡图：`trans<N>_00001_.png`（output-moss），副本进 `out\2026-11-10_trans<N>_过渡图_*.png`
- 色图：`work\trans<N>_cm.png`，拷进 `ComfyUI\input\cm_trans<N>.png`
- 深度图：`work\trans<N>_depth.png`，拷进 `ComfyUI\input\dep_trans<N>.png`
- 目标图：`AB<N>_00001_.png`，副本进 `out\2026-11-10_AB<N>_*.png`
- 提示词中间文件：`C:\MOSS-Deploy\work\_prompt_achain.txt`、`_region_trans<N>.txt`

---

## 9. 相关文档

**GrabTag 本身（2026-11-11 重建）**：`notes\机制-GrabTag-当前实现.md` —— 参考侧分区引用的完整实现：
`--ref-query-mask-por` + `--ref-labels` + 反向指派，四臂实测（gt4 `vs参考 121.13` 优于整图参考 127.80），
含裁片预算表、掩码陷阱、待验证项。**要动 GrabTag 就读这份，不要读旧的 `机制-MOSS-GrabTag-当前实现.md`（已作废）。**

**两步生成的实验底账**：`notes\2026-11-10-汇总-GrabTag参考图探索的全部结论.md` —— 十二条结论 + 参考注入区间数据 + 已排除方向 + 未解问题
（⚠️ 其中「GrabTag 走 `--color-map`」这条已被推翻，文档开头有说明）。本节其余文档是它的展开。

**两条路线的专门文档：**

- `notes\路线-单A复刻-参考图直接复刻与提示词微调.md` —— **单 A 主路线**：四件套、四 seed 表、四个变体对照、微调边界
- `notes\2026-11-10-分析-参考图强弱由什么决定-三开关四象限.md` —— 为什么 control 一挂上参考就变弱（四象限实测）

**机制与过程：**

- `notes\机制-control三参数-strength-start-end.md` —— strength/start/end 的原生语义与四档实测
- `notes\2026-11-10-路线-两步生成-过渡图提取色图与深度图.md` —— 路线来源与过程记录
- `notes\2026-11-10-经验-文本先验与参考寻址的矛盾.md` —— 为什么不能靠整图参考
- `notes\2026-11-10-核对-四星2参考图与生成图描述.md` —— 反写核对方法论（目视三次全错的教训）
- `notes\2026-11-10-汇总-参考图六条失败路径与复刻上限.md` —— 六条已排除路径 + vision token 上限无效 + 步数不提升精度
