# SOP-1 · 原图复刻流程

> **一句话**：手上有一张参考图，要生成同款同姿势的成图，用这条流程。
> **实测**：1216×1632 / 8 步 fast，全流程 **1.0 min**，`vs参考 126.04`（旧单 A 配方 127.58），单人无多主体。
> **前置**：`notes\约定-GrabTag终版.md`（GrabTag 规则）、`notes\手册-region-prompt.md`（色图规则）、`notes\手册-PromptEnhancer.md`（提示词规范）。

---

## 零、总览

```
参考图
 ├─[0] 提深度图 → 背景刷纯黑                              tools\depth_to_mask.py
 ├─[1] 按部位切块 → 逐块反写 → {trunk, details[]}       tools\describe_parts.py
 ├─[2] 选关键部件（≤8）→ 裁片 + 掩码                     tools\pick_parts.py
 └─[3] 细节 → 分区色图 + region prompt                   tools\detail_colormap.py
        ↓
   一条 moss_run.py 命令
```

**三处产物分工**：
| 通道 | 管什么 | 由谁产出 |
|---|---|---|
| 裁片（参考侧） | **是什么** —— 形貌、材质、纹样 | 第 2 步 |
| 分区色图（画布侧） | **在哪** —— 区域归属 | 第 3 步 |
| 提示词 | **指位置**（前部）+ **补细节**（后部） | 第 1 步的 trunk/details |

> ⚠️ **第 0 步不能省**（2026-11-12 实测）：深度图的背景常常不是均匀的「远」，而是一角很亮。MOSS 的深度语义是「近处白、远处黑」，那个亮角就被读成「这里有一块很近的东西」，模型会在画布对应侧**补画近景装饰**。实测参考图 1216×1632 的深度图四角亮度 `[152.7, 153.8, 243.1, 247.0]`，右下/右上接近纯白 → 24 步生成时画面左右各多出一条贯穿全高的装饰带（左右边缘非白 **99.7%**）。把背景刷成纯黑（四角 0.0）后带子消失、左右边缘非白降到 **0.0%**。

---

## 零·五、第 0 步：深度图背景刷纯黑

### 命令（用工具，不要手写阈值）

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\depth_to_mask.py' `
    '你的深度图.png' `
    'C:\MOSS-Deploy\ComfyUI\input\s1' `
    --feather 2
```

**输出到 `ComfyUI\input\`**（`--depth-map` 只认那个目录，传别处会 `Invalid image file`）。两个文件：
- `s1_black.png` → 喂 `--depth-map`（原深度值，背景全 0）
- `s1_mask.png` → 喂 `--mask` / `--ref-query-mask`（纯黑白，白=人物）

### 它做了什么

| 步骤 | 作用 |
|---|---|
| **Otsu 阈值** | 自适应，不用手调；只在 ROI 内统计，避免四角亮角干扰 |
| **形态学闭/开运算** | `CLOSE (13,13)` 补小洞，`OPEN (5,5)` 去毛刺 |
| **地面宽段过滤** | `y >= 图高×0.86` 的行里丢掉宽度 > 300 px 的连续段（地面横跨全宽），保留窄段（脚） |
| **最大连通域** | 只留最大的那块 |
| **填洞 / 羽化** | 补内部小洞；边缘羽化（只给 mask） |

### 为什么不用手写阈值

**2026-11-12 实测的坑**（都试过）：

| 手写方案 | 结果 |
|---|---|
| 全局 `a[a<58]=0` | 背景是从上到下渐变、四角偏亮的灰，与人物暗部重叠 → 残留大片灰、切出怪异多边形 |
| 行内自适应 `thr=max(110,mx-55)` | 人物只剩 **4.49%**（躯干被切掉） |
| `m[1480:,:]=0` 切地面 | **切掉脚** → 生成多肢体 |
| `m[:130,:]=0` 切顶部 | **切掉抬起的脚尖**（脚尖从 y=100 起） |
| 矩形挖空 | 留下方块边，形状失真 |

**正确做法**：Otsu 定阈值 + **地面按「段宽度」过滤**（地面横跨全宽→宽段；脚只有几十像素→窄段）+ 最大连通域。

### 什么时候还能用 clean_depth.py

`tools\clean_depth.py` 走的是另一条路：按「参考图白底 ∪ 深度图亮度 ≥250」刷黑。它适合**参考图与深度图同尺寸、背景同源**的情况，靠 `--bg-max`（默认 238）微调。

**两者都能用，但口径以 `depth_to_mask.py` 为准**（它不依赖参考图，也能处理带地面/渐变背景的深度图）。

### 检查点

- 日志 `[depth_to_mask] 四角(刷后)` 应全是 `0`
- 人物占比 **10–20%**（站姿）或 25–40%（跪坐/蹲姿），**bbox 不贴画布任何一边**
- **两只脚都在**（如果姿势有两只脚可见）
- 日志 `[depth_to_mask] 地面过滤` 那行的像素数**只应减少一部分**（实测 `448797 → 275652`）。减到接近 0 说明 `--floor-max-width` 设小了，脚也被当地面切了

---

## 一、第一步：切块反写 + 主干/细节分离

### 做什么
把参考图按人体部位切成小块，逐块做多模态反写，然后**把主干和细节分开**。

### 命令
```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\describe_parts.py' `
    --image 'C:\MOSS-Deploy\ComfyUI\input\v2sop_ref.png' `
    --out   'C:\MOSS-Deploy\work\parts_all.json'
```

### 输出
`parts_all.json`，每个部位含：

| 字段 | 内容 | 用途 |
|---|---|---|
| `trunk` | 形状 / 主色 / 材质 / 轮廓（合计约 1100 字） | 汇入主提示词，**只用来指位置** |
| `details[]` | 纹样 / 数量 / 位置 / 质感（合计约 9300 字） | 留给 region prompt |
| `bbox_px` | 像素坐标 | 切裁片、切掩码 |
| `area_pct` | 画布占比 | 第二步打分、第三步定文案预算 |

**trunk 与 details 的比例约 1:8.5** —— 细节天然比主干多，但主干不该进 region prompt，细节不该进主提示词。

### 检查点
- `parts_all.json` 里每个部位都有 `trunk` 和 `details`
- `bbox_px` 数值落在 0–W / 0–H 之间

---

## 二、第二步：选关键部件 → 裁片 + 掩码

### 做什么
从 `parts_all.json` 里选 **≤8 个**关键部件（`--ref-query-mask-por` 的硬上限），切裁片、切掩码。

### 选择规则（脚本按此打分）
1. **面积大**（×10 权重）—— 决定整体轮廓
2. **位置易漂**（`sash` / `waist` / `belt` / `point` / `cuff`，+5）
3. **需配对**（`point` / `inner` / `lining`，+3）
4. **细节条数**（每条 +0.5，封顶 8）

排除：`hair` / `orb` / `face` / `head`（黑名单）、面积 < `--min-area`（默认 3.0%，可降到 2.5% 把鞋捞回来）。

### 命令
```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\pick_parts.py' `
    --parts  'C:\MOSS-Deploy\work\parts_all.json' `
    --ref    'C:\MOSS-Deploy\ComfyUI\input\v2sop_ref.png' `
    --w 1216 --h 1632 `
    --input-dir 'C:\MOSS-Deploy\ComfyUI\input' `
    --prefix sop --max 8 --size 512 --min-area 2.5 `
    --out-selection 'C:\MOSS-Deploy\work\picked.json'
```

### 输出
| 产物 | 位置 | 说明 |
|---|---|---|
| 裁片 | `ComfyUI\input\sop_<id>.png` | 最长边 512 |
| 掩码 | `ComfyUI\input\sopm_<id>.png` | 画布同尺寸，**bbox ∩ 参考图非背景** |
| 选择结果 | `work\picked.json` | 第三步校验用 |
| 三行命令 | 屏幕 | 直接粘到 `moss_run.py` |

### 脚本处理的三件事
| 情况 | 处理 |
|---|---|
| **grounding 把左右袖框成同一块**（重叠 100%） | 按 IoU > 0.8 去重保留一个；**但重叠 100% 往往是 grounding 的错，不是真重叠**——见下方「两类掩码 bug」 |
| **`veil` 与 `bodice` 重叠 90%** | 同上；这是真重叠，只能合并 |
| **掩码做成矩形会多主体** | 改用 bbox ∩ 非背景 |

**背景判据必须同时用 `min(RGB)` 和 `max(RGB)`**：
```python
fg = (arr.min(axis=2) <= 238) & (arr.max(axis=2) >= 16)
```
- 只用 `min(RGB) <= 238`：会**把纯黑背景全算成前景**。本案例参考图没有 alpha 通道、纯黑占 **44.89%**（它是黑底），前景被判成 75.65%，各掩码面积虚高 30–50%（`shoes` 5.43% → 实际 2.57%、`sleeve_r` 4.15% → 2.35%）
- 只用 `max(RGB)`：会把浅蓝衣服（`(200,230,240)` max=240）也当背景，色图上留下大量空洞
- 参数：`--bg-max`（默认 238）/ `--bg-min`（默认 16）

### 两类掩码 bug（2026-11-12 实测）

**① 黑背景被算成前景** —— 症状是掩码面积比 `area_pct` 大很多、形状跑到背景上。修法是 `--bg-min`，见上。

**② grounding 的 bbox 本身是错的** —— 症状是两个部位像素重叠 **100%**。本案例：
```
sleeve_r bbox = (184, 301, 451, 610)   ← 画面左侧
sleeve_l bbox = (184, 300, 451, 610)   ← 完全同一块
```
人物左臂在画面右侧。**用人物中轴镜像修**（中轴 = 各部位 bbox 中心的中位数，本案例 x = 517）：
```python
axis = np.median([(p['bbox_px'][0]+p['bbox_px'][2])/2 for p in parts])
mir  = (int(2*axis - x1), y0, int(2*axis - x0), y1)
# sleeve_l: (583, 301, 850, 610)，框内前景 99.27%，与 sleeve_r 重叠 0.00%
```

### 检查点
- 掩码面积 ≈ `area_pct`（差太多说明背景判据不对）
- **两两像素重叠 < 90%**（`(A&B).sum()/min(A.sum(),B.sum())`）；100% 就是 grounding 的错，别急着去重
- 裁片里能看到对应部位

---

## 三、第三步：细节 → 分区色图 + region prompt

### 做什么
选若干色区，用掩码的形状画色图（中灰底），再把该区的 `details[]` 拼成文案。

### 四条硬规则
1. **色区形状贴合衣物轮廓**（用掩码，不用矩形）
2. **色区数上限 = 互不重叠的部位数**（不是固定的 3）——实测 3/5/8/9 区色块泄漏全 **0.000%**，颜色从不是瓶颈；真瓶颈是掩码像素重叠（>90% 的合并）。本案例 11 部位里两对真重叠 ⇒ 上限 9 区
3. **背景中灰 `(128,128,128)`**（白底会把姿态拉成正面站定）
4. **>3 区时必须 `--control-strength 1.0 --depth-strength 1.0`**（否则退化成多个人）

### 命令
```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\detail_colormap.py' `
    --parts  'C:\MOSS-Deploy\work\parts_all.json' `
    --picked 'C:\MOSS-Deploy\work\picked.json' `
    --zones 'legs,sash,bodice' `
    --input-dir 'C:\MOSS-Deploy\ComfyUI\input' --prefix sop `
    --w 1216 --h 1632 `
    --out-colormap 'C:\MOSS-Deploy\ComfyUI\input\cm_sop.png' `
    --out-prompts  'C:\MOSS-Deploy\work\region_prompts_sop.txt'
```

### 选哪些色区
优先挑**面积大 + 细节多 + 你真正在意**的部位。实测腿（14.89%）最受益，胸衣/腰（4–5%）写多了反而压过裁片。

**加色区之前先做两件事**（详见 `notes\手册-region-prompt.md` §四·五）：

1. **量两两像素重叠**，>90% 的合并成一个区（真重叠分不开，硬分会互相盖）
2. **给要拆的部位做减法**：`legs 14.89% − sash − sash_point − drape = 8.17%（纯净裤子）`

### 一个部位内部拆子区（色图相对 layout 的真优势）

layout 只能画矩形（一部位一框），色图能画任意形状——**一个部位内部可以切多块**，让每块只写自己那几条文案，不再互相稀释。

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\split_zone_by_color.py' `
    --ref  '你的参考图.png' `
    --mask 'C:\MOSS-Deploy\ComfyUI\input\sopm_legs.png' `
    --k 3 --out-dir 'C:\MOSS-Deploy\ComfyUI\input' --out-prefix 'lp'
```

按平均亮度从暗到亮编号输出 `lp_0.png` … `lp_2.png` 与 `lp_report.txt`。腿的实测：

| 子区 | 占比 | 平均 RGB | 是什么 |
|---|---|---|---|
| `lp_0` | 2.33% | (45,50,70) | 深蓝裤脚 |
| `lp_1` | 3.14% | (99,115,135) | 中蓝过渡带 |
| `lp_2` | 2.70% | (168,182,192) | 浅蓝裤腿主体 |

**效果**（8 步 fast，其余全同）：下半 `vs参考` 从 126.75 降到 **122.13**（改善 7.56），腿区纹理 24.84 → 23.45（更接近参考的 19.62）。

### 文案自动截断
按面积配预算（`--chars-per-pct 50`，`--min-chars 120`）：

| 色区 | 面积 | 实际 |
|---|---|---|
| legs | 17.08% | 6/8 条，869 字 |
| sash | 4.20% | 2/8 条，258 字 |
| bodice | 4.68% | 2/10 条，206 字 |

**依据**：色图面积决定文本话语权。小色区里写长文案，文本会压过视觉裁片。

### 检查点
- 色区合计覆盖 < 70%
- 每条文案都以 `the <#hex> area carries ...` 开头

---

## 四、生成：一条命令

```powershell
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'C:\MOSS-Deploy\moss_run.py' --port 8190 `
  --image 'sop_legs.png:raw,sop_drape.png:raw,sop_sash_point.png:raw,sop_bodice.png:raw,sop_sash.png:raw,sop_sleeve_r.png:raw,sop_shoes.png:raw' `
  --ref-labels 'legs,drape,sash_point,bodice,sash,sleeve_r,shoes' `
  --ref-query-mask-por 'sopm_legs.png,sopm_drape.png,sopm_sash_point.png,sopm_bodice.png,sopm_sash.png,sopm_sleeve_r.png,sopm_shoes.png' `
  --color-map 'cm_sop.png' `
  --depth-map 'C:\MOSS-Deploy\ComfyUI\input\sop_depth_black.png' `
  --control-strength 1.0 --color-strength 0.4 --depth-strength 1.0 --control-end 1.0 `
  --w 1216 --h 1632 --steps 8 --cfg 1.0 --fast --seed 9001 `
  --edit-format ai-toolkit --ref-no-pos 1 `
  --negative 'worst quality, bad anatomy, watermark, jpeg artifact, multiple people, character sheet, turnaround, two figures' `
  --prompt-file 'C:\MOSS-Deploy\work\prompt_sop_blocks.txt' `
  @rArgs `
  --prefix 'sop2'
```

其中 `$rArgs` 由下面的片段生成（每条 region prompt 一个 `--region-prompt`）：

```powershell
$rArgs = @()
Get-Content 'C:\MOSS-Deploy\work\region_prompts_sop.txt' -Encoding UTF8 |
  Where-Object { $_.Trim() } |
  ForEach-Object { $rArgs += @('--region-prompt', $_) }
```

> ⚠️ **`--prompt` 与 `--prompt-file` 不是同义词**：`--prompt` 收的是提示词**正文**，`--prompt-file` 才是**读文件**（`moss_run.py:1084-1086` 只有后者会 `open(...).read()`）。写成 `--prompt '<路径>'` 会把路径字符串当提示词送进模型。

### 参数照抄表（这五处不能改）

| 参数 | 值 | 不改的理由 |
|---|---|---|
| `--control-strength` | **1.0** | 降到 0.5 会让深度图轮廓约束被砍半 → 多主体（非白 41%→81%） |
| `--depth-strength` | **1.0** | 降了必多主体（`dt05` 实测非白 73.7%） |
| `--color-strength` | **0.4** | 升到 1.0 画风变硬（锐度 5.0→8.0） |
| `--ref-no-pos` | **1** | 不传则参考复刻自己的布局，压过一切 |
| `--image ... :raw` | **必须带** | 不带会走缩略图路径，裁片细节全丢 |

### 提示词文件模板
见 `C:\MOSS-Deploy\work\prompt_sop_blocks.txt`（`<|...|>` 五块，引用 7 个 tag）。格式规范见 `notes\SOP-三步出图.md` §提示词格式 与 `notes\手册-PromptEnhancer.md` §四。

**要点**：
- 第 1 块写风格与光影（单向因果，光影在前）
- 块按人体从上到下
- `<tag>` 是**引用裁片**（与 `--ref-labels` 逐字对应），`<|块名|>` 是**分块标记**，两者不混用
- 前部**只指位置，不写形貌**（写形貌给腿赚 3.2、给胸衣赔 6.6）

---

## 五、实测数据

### 8 步 fast（草稿档，看趋势）

| 臂 | vs参考 | 非白% | 锐度 | 胸衣 | 腰 | 腿 | 耗时 |
|---|---|---|---|---|---|---|---|
| **sop2 本流程** | **126.04** | 35.2 | 5.39 | 119.9 | 126.3 | **108.5** | 0.89 min |
| sop1 全写文案 | 126.46 | 34.6 | 5.00 | 120.6 | 125.8 | **107.4** | 1.00 min |
| v9001 旧单 A 配方 | 127.58 | 35.4 | 5.03 | **115.3** | **121.8** | 110.4 | 0.99 min |

**读法**：分区数字越小越像参考。

- **腿最好（107.4–108.5）** —— 最大色区，region prompt 吃得下
- **胸衣/腰不如旧配方（119.9 vs 115.3 / 126.3 vs 121.8）** —— 小色区写文案反而压过裁片
- **整体 `vs参考` 最好（126.04）** —— 加权后仍是本流程占优

### 修正掩码 + legs 拆三子区之后（2026-11-12）

| 臂 | 色区 | vs参考 | 非白% | 上半 | 腰 | 下半 | 腿区纹理 |
|---|---|---|---|---|---|---|---|
| 旧掩码 8 区 | 8 | 129.62 | 31.1 | 136.14 | 115.71 | 129.69 | 24.02 |
| 新掩码 8 区（修黑背景） | 8 | 128.75 | 33.7 | 135.91 | 117.47 | 126.75 | 24.84 |
| **新掩码 9 区（legs 拆三块）** | 9 | **126.95** | 33.5 | 136.82 | 115.36 | **122.13** | **23.45** |
| 参考图 | — | — | — | — | — | — | 19.62 |

**两处改善**：修黑背景后下半 129.69 → 126.75；再拆 `legs` 三子区后 → **122.13**（累计 7.56）。腿区纹理 24.84 → 23.45，也更接近参考的 19.62。

---

## 六、已知边界

| 边界 | 说明 |
|---|---|
| **深度图背景必须刷黑** | 不刷的话，深度图里「一角接近纯白」会被读成「那里有很近的东西」，24 步下画面左右各多一条贯穿全高的装饰带（边缘非白 99.7%）。用 `tools\depth_to_mask.py` 刷到四角 0.0（实测后边缘非白降到 0.0%）。**8 步 fast 有时能侥幸避开，24 步必出** |
| **小色区别写长文案** | 4–5% 的色区写 8 条细节会退化；要么按面积截断，要么干脆不写 |
| **脚部始终差** | 分区 `vs参考` 144.5–156.1（参考尖头高跟 vs 生成圆头平底） |
| **掩码是近矩形** | 参考图前景占 30.8%（修黑背景后），`bbox ∩ 非背景` 仍接近矩形；靠 `strength 1.0` + 负向压住多主体 |
| **grounding 同框有两类** | ①**真重叠**：`veil`/`bodice` 像素重叠 **97.85%**（薄纱半透明压在胸衣上）、`sash`/`sash_point` **96.40%** → 只能合并成一个区 ②**定位错**：`sleeve_l`/`sleeve_r` **100%** 是 grounding 把左右袖框成同一块 → 用人物中轴镜像修，修完重叠 0.00% |
| **黑底参考图的掩码会虚高** | 参考图无 alpha 且纯黑占 44.89% 时，`min(RGB)<=238` 会把黑背景算成前景，掩码虚高 30–50%。必须 `& (max(RGB)>=16)` |
| **`hair` / `orb` 默认不选** | hair 被 veil 遮挡、orb 面积小；需要它们时用 `--blacklist ''` 或 `--pick` 强制 |

---

## 七、跑前检查表

- [ ] `parts_all.json` 存在且每个部位有 `trunk` + `details`
- [ ] **深度图背景已刷纯黑**（`depth_to_mask.py` 输出 `[depth_to_mask] 四角(刷后)` 全是 0）
- [ ] `picked.json` 里 ≤8 个部件
- [ ] 所有裁片和掩码都在 `ComfyUI\input\` **根目录**（子目录报 `Invalid image file`）
- [ ] 掩码是黑底白区、尺寸 = 画布尺寸
- [ ] **掩码没把黑背景算进去**（面积 ≈ `area_pct`；参考图是黑底时必须有 `--bg-min`）
- [ ] **两两掩码像素重叠 < 90%**（100% 说明 grounding 框错了，用中轴镜像修）
- [ ] 色图色区数 **≤ 互不重叠的部位数**、背景中灰
- [ ] `--image` 每张都带 `:raw`
- [ ] `--ref-labels` / `--image` / `--ref-query-mask-por` 三者顺序一一对应
- [ ] 负向含 `multiple people, character sheet, turnaround, two figures`；**文案里有制图式措辞时再加 `text, letters, caption, title`**
- [ ] 提交前查 `/queue`，`queue_running` 为 0

---

## 八、出问题时

| 症状 | 先查 |
|---|---|
| 画出 2–3 个人 | `--control-strength` / `--depth-strength` 是不是降了 |
| **画面左右各多一条贯穿全高的装饰带** | **深度图背景没刷黑**（四角有接近纯白的亮角）；先跑 `tools\depth_to_mask.py` 看 `四角(刷后)` 是否全 0 |
| 姿态变成正面站定 | 色图背景是不是白底（必须中灰 128） |
| 裁片没起作用 | `--image` 是否带 `:raw`；`--ref-labels` 与 prompt 里的 `<tag>` 是否逐字一致 |
| 色图有大片空洞 | 背景判据是不是只用 `max(RGB)`（要同时用 `min(RGB)`） |
| **色区形状跑到背景上、面积虚高** | 掩码把纯黑背景算成前景了（参考图是黑底时要 `& max(RGB)>=16`） |
| **画面里冒出英文标题/水印** | 文案里的 `fully visible` / `per leg visible` 太像制图标注；去掉这类词并在负向加 `text, letters, caption, title` |
| **某部位的颜色被漂白/变淡** | 它和另一个色区的掩码重叠 >90%，后画的盖掉先画的；合并成一个区 |
| 小部位画错/消失 | 该色区文案太长，压过了裁片 |

---

## 出处

- 工具：`E:\DSH-MOSS工作区\tools\depth_to_mask.py`（第 0 步：深度图背景刷纯黑 + 出人物剪影 mask）/ `describe_parts.py` / `pick_parts.py` / `detail_colormap.py`
- GrabTag 规则：`notes\约定-GrabTag终版.md`
- 色图规则：`notes\手册-region-prompt.md`
- 提示词规范：`notes\手册-PromptEnhancer.md`
- 提示词格式：`notes\SOP-三步出图.md` §提示词格式
- strength 拆分依据：`notes\2026-11-11-经验-色图与深度图共享strength导致多主体.md`
