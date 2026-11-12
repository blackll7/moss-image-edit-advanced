# SOP-2 · 原图调整流程

> **一句话**：手上已经有一张能用的成图（或 SOP-1 的产出），要在**不换姿势、不换构图**的前提下，用提示词把**某个部件**变成原图里没有的样子（材质、形态、通透度）。
> **与 SOP-1 的区别**：SOP-1 是「把参考图复刻出来」，SOP-2 是「复刻的基础上改一件事」。
> **首个案例**：把灯笼裤改成「冰衣」（裤化成冰与水、透明可见腿、轮廓保留、菱形片与金边仍是硬的）—— 定义见 `E:\BaiduNetdiskDownload\image\迁移产出\回归测试-20261029\V60-四星2-冰衣\00-prompt-sources.md`。

---

## 零、核心原则（实测得来）

### 1. 只动一个部位的三处文案，其余全不动
改造的是提示词，但**流程、裁片、掩码、色图、参数都与 SOP-1 完全一致**。只改：
- 前部 prompt 里该部位那一段（写"变成什么"）
- 该色区的 region prompt（写"看到什么"）
- 负向（压制这个改造容易溢出的东西）

**其余部位一个字都不改** —— 这样万一结果不对，能确定是这一处的责任。

### 2. 目标部位必须同时保留色区与裁片（否则改不动）
**实测对比**：

| 臂 | 色区 | 裁片 | 结果 |
|---|---|---|---|
| **ICE-A** | 保留 `#ff00ff` | 保留 `sop_legs.png` | **裤子变成半透明冰与水，腿透出来** ✓ |
| ICE-B | **去掉** | 保留 | **还是深蓝布料**，颜色反而更深 ✗ |

**原因**：去掉色区后，腿部没有「这部分归你」的指派，模型退回自己的先验（深蓝灯笼裤），文本完全被裁片压制。**色区不只是管位置，它同时也是「允许改动」的授权。**

### 3. 写「没有布料」，不要写「布料变成了冰」
差分表述明确得多：

| 差 | 好 |
|---|---|
| `the trousers have turned into ice` | `the #ff00ff area carries **no cloth at all**: her legs are covered only by clear ice and flowing water` |
| `ice with a frosted look` | `clear and colourless, tinted only faintly blue-white, **no white frost, no milky surface**` |
| `she looks nude` | `the original harem-pant outline survives only as the boundary of that water`（保留轮廓，避免真裸） |

---

## 一、操作步骤

### 第 0 步：先跑一次 SOP-1 拿到基线
SOP-2 的输入是 SOP-1 的产物（`parts_all.json` / `picked.json` / 裁片 / 掩码 / 色图）。没有基线就先按 `notes\SOP-1-原图复刻流程.md` 跑一遍。

### 第 1 步：确认目标部位在裁片与色区里都在
```powershell
# 看 picked.json 里有没有这个部位
Get-Content 'C:\MOSS-Deploy\work\picked.json' | ConvertFrom-Json | Select-Object -ExpandProperty picked
```
没有就回到 SOP-1 第二步把它加进来（`--pick legs` 强制指定）。

**同时检查三件事**（2026-11-12 补）：

| 检查 | 怎么查 | 不合格怎么办 |
|---|---|---|
| **掩码面积对吗** | 对比 `parts_all.json` 的 `area_pct` | 差 30% 以上说明前景判据把黑背景算进去了（`pick_parts.py` 要 `--bg-min`） |
| **和目标部位重叠的色区有几个** | 两两算 `(A&B).sum()/min(A.sum(),B.sum())` | >90% 的必须合并——否则改动的色区会被后画的盖掉 |
| **目标部位是不是一大块** | 看它的 `details[]` 条数 | 条数多（如腿 8 条）就该拆子区，见下 |

### 第 1·五步（可选）：把目标部位拆成子区

**这对 SOP-2 特别有用**：改造往往只作用于部位的一部分（冰衣案例里「腰口一圈冰」「裤脚一圈冰」「中间化成水」是三段不同的东西），一整块写一段文案会互相稀释。

```powershell
# 1) 先扣掉别的部位（legs 的 bbox 覆盖了腰带和垂布）
#    legs_pure = legs & ~sash & ~sash_point & ~drape
# 2) 再按颜色切
& 'C:\MOSS-Deploy\venv\Scripts\python.exe' 'E:\DSH-MOSS工作区\tools\split_zone_by_color.py' `
    --ref '参考图.png' --mask 'C:\MOSS-Deploy\ComfyUI\input\sopm_legs.png' `
    --k 3 --out-dir 'C:\MOSS-Deploy\ComfyUI\input' --out-prefix 'lp'
```

按平均亮度从暗到亮编号。腿的实测（扣掉重叠后 8.17%）：

| 子区 | 占比 | 平均 RGB | 可以对应冰衣的哪一段 |
|---|---|---|---|
| `lp_0` | 2.33% | (45,50,70) | 深蓝裤脚 → 冻着菱形片的冰圈 |
| `lp_1` | 3.14% | (99,115,135) | 中蓝过渡 → 化开的水 |
| `lp_2` | 2.70% | (168,182,192) | 浅蓝主体 → 融水贴腿 |

**每块的 region prompt 只写它自己那一段改造**，不再挤在一句里。

> ⚠️ 拆子区会占用色区名额。色区数上限 = 互不重叠的部位数（见 `notes\手册-region-prompt.md` §四·五），本案例 9 区。要先算清楚再拆。

### 第 2 步：写三处文案

**① 前部 prompt 里该部位的块**（`prompt_ice_blocks.txt` 的 `<|legs|>` 块为范例）：
- 先说「不再是布」，再说「现在是冰」，最后说「透过它看得见皮肤」
- **光影/氛围词写在第 1 块**（单向因果注意力，后面的词对前面的权重为 0）

**② 该色区的 region prompt**：
- 开头必须是 `the #hex area carries ...`
- 先写**否定**（`no cloth at all`），再写**实体**（冰圈在哪、水在哪），最后写**禁止词**（no white frost / no milky / no plastic）
- 长度按色区面积给（`--chars-per-pct 50`）

**③ 负向**：把这次改造最容易溢出的东西补上
- 冰衣案例：`snowflake, snow crystals, ice crystals, water ripples, puddle, gradient background, blue background, scenic background, particles, sparkles, glow, bokeh`
- **文案里有制图式措辞时必加**：`text, letters, caption, title`。实测 region prompt 里那些 `fully visible` / `per leg visible` / `partially visible` 会让模型以为在画技术图解，于是自己在裤腿上印了个标题「Veil of the Azure Deepwater」
- ⚠️ **`--fast` + `cfg 1.0` 下 CFG 不启用，负向大部分无效**（实测改负向后字节变了、视觉没差别）。但加 `text, letters, caption, title` 这一组**实测有效**，水印消失了。要压背景仍然只能靠正面写死，或改用 `--no-fast --cfg 3.5`

### 第 3 步：跑
参数与 SOP-1 完全一致（五处不能改的那五个）。只换掉**三处文案**：

| 参数 | 传什么 | 注意 |
|---|---|---|
| `--prompt-file <路径>` | 前部提示词**文件** | ⚠️ **不要用 `--prompt <路径>`** —— `--prompt` 收的是提示词正文，传路径等于把路径字符串当提示词（`moss_run.py:1084-1086`：只有 `args.prompt_file` 才会 `open(...).read()`） |
| `--region-prompt '<内联文本>'` | 色区文案，逐条重复 | 这个本来就是内联文本，用法无误 |
| `--negative '<内联文本>'` | 负向 | 同上 |

**这一条踩过坑**：早期所有写成 `--prompt 'C:\...\xxx.txt'` 的实验，模型收到的是路径字符串本身，分块文本从未进入模型 —— 表现为「改了 prompt 文件、图像完全不变」。

### 第 4 步：验收
| 项 | 怎么看 |
|---|---|
| **目标改动有没有发生** | 分区 `vs参考` 应显著上升（ICE-A 腿区 **18.92**，正常复刻是 107–110 的绝对差，这里看的是与基线图之差） |
| **有没有溢出到别处** | 四角亮度 / 背景饱和度；对比未改部位（胸衣、腰）应当**基本不变** |
| **轮廓还在不在** | 目标部位的外沿是否仍是原形状（冰衣案例：灯笼裤的桶形轮廓） |
| **保留件还在不在** | 菱形片、金边、流苏这些「不该动」的硬装饰有没有跟着化掉 |

---

## 二、实测记录（冰衣，2026-11-12）

| 臂 | 改动 | 结果 |
|---|---|---|
| ICE-B | **去掉** `legs` 色区，只靠前部文案 | **失败**：仍是深蓝布料、颜色更深、多出雪花符号 |
| ICE-A | 3 区色图，`legs` 文案换冰衣（旧写法 `--prompt <路径>`） | 裤子化成冰与水、腿透出、菱形片仍是硬的，**但背景被染满**（非白 **75.6%**、饱和度 **33.36**） |
| ICE-A2 | 同上 + 负向补背景 | 与 ICE-A 视觉几乎无差别 |
| **ICE-A4** | 改用 `--prompt-file` + 把空白背景约束顶到第 1 块最前面 | **成功且干净**：背景纯白（非白 **33.4%**、饱和度 **17.22**，完全回到正常水平）、腿透过冰清晰可见、菱形片仍是硬的、整体接近「无色偏青白」 |
| icel1 | ICE-A4 + 光效模板（`sun from behind … caustic ripple patterns …`） | `icea4 vs icel1 = 2.75`（噪声级）—— **8 步 fast 下焦散表现不出来**，要更高步数 |

**量化（1216×1632 / 8 步 fast / seed 9001）**：

| 臂 | vs参考 | 非白% | 锐度 | 饱和度 |
|---|---|---|---|---|
| sop2（无冰衣基线） | 126.04 | 35.2 | 7.09 | 17.84 |
| icea（旧写法） | 115.70 | **75.6** | 8.21 | **33.36** |
| **icea4（新写法）** | 128.76 | **33.4** | 6.96 | **17.22** |
| icel1（加光效） | 128.93 | 33.6 | 7.11 | 17.55 |

- `icea vs icea4 = 17.28` —— **`--prompt-file` 与背景前置这两个修正合起来的效果**
- `sop2 vs icea4 = 10.63`（腿区差值更小，因为背景干净后整体更接近参考）
- **改造是实打实的**：icea4 与基线的差异集中在腿（裤子没了），胸衣/腰/披风基本不变

**icea4 仍有的不足**：整体略偏蓝（目标图更「无色」）；腿的透出度不如目标图（目标几乎全透，生成偏乳白）。

---

## 三、已知边界

| 边界 | 说明 | 绕法 |
|---|---|---|
| **`--prompt <路径>` 不生效** | `--prompt` 收正文、`--prompt-file` 才读文件；写成路径时模型收到的是路径字符串，表现为「改了文件、图不变」 | **一律用 `--prompt-file`** |
| **负向在 fast 下几乎无效** | `--fast` 强制 `cfg 1.0`，无 CFG → 负向权重≈0 | 正面写死（尤其把背景约束顶到第 1 块）；或 `--no-fast --cfg 3.5`（24 步，约 4 min） |
| **材质类词会溢到背景** | `ice` / `water` / `bubble` 同时暗示了氛围 | 第 1 块写死 `plain off-white background, nothing else in frame` |
| **「透明」容易画成「乳白」** | 模型对 `transparent` 的默认理解是半透明白 | 写 `see-through, skin colour and light intact through it` + 负向 `milky, frosted` |
| **去掉色区就改不动** | 色区同时承担「指派」与「授权」 | 保留该区，只在文案里改 |
| **硬装饰会跟着化掉** | 菱形片、金边属于「同一区域」 | 在该区文案里单独声明 `stay hard and in place, resting on the outermost surface` |
| **掩码把黑背景算成前景** | 参考图无 alpha 且是黑底时（本案例纯黑占 44.89%），`min(RGB)<=238` 会把黑背景全算前景，掩码虚高 30–50%，改造会溢到背景上 | 前景判据加 `& (max(RGB)>=16)`，`pick_parts.py` 用 `--bg-min 16` |
| **两个色区像素重叠 >90%** | 后画的盖掉先画的，被盖的那个部位颜色被漂白（实测胸衣饱和 33.38 → 29.11） | 合并成一个区，文案里带一句说明（如「外面罩着两条淡青白薄纱」） |
| **画面里冒出英文标题** | region prompt 的 `fully visible` / `per leg visible` 被读成制图标注 | 去掉这类词 + 负向加 `text, letters, caption, title`（这组在 fast 下实测有效） |

---

## 四、与 SOP-1 的参数一致性

**五处不能改的照抄 SOP-1**：

| 参数 | 值 |
|---|---|
| `--control-strength` | 1.0 |
| `--depth-strength` | 1.0 |
| `--color-strength` | 0.40 |
| `--ref-no-pos` | 1 |
| `--image ... :raw` | 必须带 |

**其余**：`--w 1216 --h 1632 --steps 8 --cfg 1.0 --fast --edit-format ai-toolkit`。

---

## 五、跑前检查表

- [ ] SOP-1 的基线已跑过（有 `parts_all.json` / `picked.json` / 裁片 / 掩码 / 色图）
- [ ] 目标部位**在裁片和色区里都在**
- [ ] **目标部位掩码面积 ≈ `area_pct`**（差得多说明黑背景被算进前景）
- [ ] **和目标部位重叠 >90% 的色区已合并**
- [ ] 目标部位细节条数多的话**已拆子区**（冰衣案例：腰口冰 / 中间水 / 裤脚冰 分三段写）
- [ ] 前部文案写了「不再是 X，现在是 Y，透过它看得见 Z」
- [ ] region prompt 以 `the #hex area carries` 开头，先否定再实体
- [ ] 保留件（硬装饰）单独声明「仍是硬的、在原来位置」
- [ ] 色区数 **≤ 互不重叠的部位数**、背景中灰
- [ ] 负向含 `text, letters, caption, title`（文案有制图式措辞时必加）
- [ ] 知道这次**没动**哪些部位（验收时用来对比）

---

## 出处

- 冰衣定义：`E:\BaiduNetdiskDownload\image\迁移产出\回归测试-20261029\V60-四星2-冰衣\00-prompt-sources.md`（1266 字角色描述）
- 目标图：同目录 `四星2-冰衣-v3透冰-white.png`
- 流程基础：`notes\SOP-1-原图复刻流程.md`
- 负向失效依据：`C:\MOSS-Deploy\moss_run.py` 的 `--fast` 默认开、强制 `cfg 1.0`
- 产物：`icea_00001_.png`（成功）、`icea2_00001_.png`（负向加强，视觉无差）、`iceb_00001_.png`（去色区，失败）
- 色区数上限与三对重叠：`notes\2026-11-12-经验-色图区数上限-不重叠部位数.md` 与 `notes\手册-region-prompt.md` §四·五
- 子区切分工具：`E:\DSH-MOSS工作区\tools\split_zone_by_color.py`
