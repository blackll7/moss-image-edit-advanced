# region prompt 使用手册

> **一句话**：画一张「分区色图」，每个色块配一句话，告诉模型「这块区域要画成什么样」。
>
> **它解决的问题**：提示词说「裤子上有菱形」，模型可能画到披风上、可能画五个、可能画成一坨。分区后可以说「**这块**区域里的菱形是这样排的」。

---

## 一、它是什么，不是什么

| | |
|---|---|
| **是** | 画布侧的**区域指派**：一张色图划定区域 + 每区一句文案 |
| **不是** | 参考图绑定（那是 `--image` + `--ref-labels`，见 `手册-GrabTag.md`） |
| **不负责** | 形状轮廓、整体布局、姿态（形状交给深度图，长相交给参考裁片） |
| **分辨率上限** | **16 px 一格**（VAE stride 16）——能定位置，定不了比 16 px 更细的东西 |

**判断该不该用**：当你要「这个纹样必须出现在这块布料上」时用它；当你要「这个部位长成那样」时用 GrabTag。

---

## 二、两样东西

### 1. 一张色图

PNG，尺寸 = 生成画布尺寸（如 1216×1632）。

**画法**：

| 规则 | 原因 |
|---|---|
| **形状必须贴合衣物轮廓** | 矩形会画出多个人（实测非白 41%→81%） |
| **色块数上限 = 互不重叠的部位数**（不是固定的 3） | 实测 3/5/8/9 区色块泄漏全 **0.000%**，颜色从来不是瓶颈；真正的瓶颈是**掩码像素重叠**——重叠 >90% 的两块在色图里后画的会盖掉先画的（`veil` 盖 `bodice` 让胸衣饱和从 33.38 掉到 29.11） |
| **背景必须是中灰 `(128,128,128)`** | 白底会毁姿态（画成正面站定）、黑底也偏 |
| 每块用纯色填充 | 模型只认「这块归你」，不认颜色本身 |
| **>3 区时必须 `--control-strength 1.0 --depth-strength 1.0`** | 3 区以上色块的分区暗示会压过人体轮廓，靠深度图把它"消化"成布料分区 |

```powershell
# 用掩码拼一张 3 区的色图（掩码来自 GrabTag 那一步，或自己画）
$py = 'C:\MOSS-Deploy\venv\Scripts\python.exe'
& $py -c @"
import numpy as np
from PIL import Image
W,H = 1216,1632
plan = {'legs':'#ff00ff', 'sash':'#0000ff', 'bodice':'#9fe8e0'}   # 部位 -> 纯色
base = np.full((H,W,3), 128, np.uint8)                             # 中灰底，必须
for pid, hexc in plan.items():
    m = np.asarray(Image.open(r'C:\MOSS-Deploy\ComfyUI\input\gtm2_%s.png' % pid)
                   .convert('L').resize((W,H), Image.NEAREST)) > 127
    base[m] = tuple(int(hexc[i:i+2],16) for i in (1,3,5))
Image.fromarray(base).save(r'C:\MOSS-Deploy\ComfyUI\input\cm_mask3.png')
"@
```

**色号怎么选**：用 `tools\detail_colormap.py:36` 里那张 **10 色板**，按顺序取前 N 个即可：

```
#ff00ff  #0000ff  #00ff00  #ff8000  #8000ff
#00ffff  #ff0000  #80ff00  #ff0080  #0080ff
```

- **2–4 色**最小色差 **255**（很安全）
- **5 色起降到 127**（最接近的一对是 `#ff00ff ↔ #8000ff`，洋红↔紫）
- 与中灰底 `(128,128,128)` 的距离恒在 255–382

**所以色号本身不需要挑**——实测 9 区混用这套色板，生成图里落在色板色 ±40 内的像素占比 **0.000%**，模型从不会把区域 ID 画出来。**别自己发明新颜色**（尤其是接近参考图主色的），那才会被当成填色指令。

### 2. 每区一句文案

**格式固定**：

```
the <色号> area carries <描述>.
```

**描述写什么**：

| 该写 | 不该写 |
|---|---|
| 数量（`four large diamond appliqués`） | 轮廓（`a fitted silhouette`） |
| 排列（`arranged horizontally across the front`） | 材质大类（`made of fabric`） |
| 每条装饰的颜色 + 材质（`violet crystal set in gold filigree`） | 位置方位（`on the upper body`） |
| 附属细节（`three dangling teardrop crystals`） | 整体风格 |

**三条实例**（可直接改）：

```
the #ff00ff area carries gold-thread vertical stripes running parallel down the front of each leg; navy-edged diamond appliqués in four rows per leg, each diamond set with a pale blue gem, linked by gold chains hung with red-brown beads and small silver star pendants.

the #0000ff area carries four large diamond-shaped appliqués in faceted violet crystal set in gold filigree, arranged horizontally across the front center; three dangling teardrop-shaped clear crystals along the lower edge.

the #9fe8e0 area carries a central ornamental motif of gold filigree with purple and white mosaic tiles; an oval pearl in a scalloped gold bezel surrounded by six small sapphire cabochons; two fan-shaped mosaic panels flanking it, each of twelve diamond-cut purple glass tiles in three rows of four.
```

**细节文案从哪来**：`tools\describe_parts.py` 能自动反写每个部位（`parts_all.json` 的 `details[]` 字段），比手写全。

---

## 三、完整命令（直接改路径就能跑）

```powershell
$py = 'C:\MOSS-Deploy\venv\Scripts\python.exe'

& $py 'C:\MOSS-Deploy\moss_run.py' --port 8190 `
  --image '你的参考图.png:raw' `
  --depth-map 'C:\MOSS-Deploy\ComfyUI\input\你的深度图.png' `
  --color-map 'cm_mask3.png' `
  --region-prompt 'the #ff00ff area carries ...' `
  --region-prompt 'the #0000ff area carries ...' `
  --region-prompt 'the #9fe8e0 area carries ...' `
  --control-strength 1.0 --color-strength 0.4 --depth-strength 1.0 --control-end 1.0 `
  --w 1216 --h 1632 --steps 8 --cfg 1.0 --fast --seed 9001 `
  --edit-format ai-toolkit --ref-no-pos 1 `
  --negative 'worst quality, bad anatomy, watermark, jpeg artifact' `
  --prompt (Get-Content '你的主提示词.txt' -Raw -Encoding UTF8) `
  --prefix 'rg_test'
```

**成功的日志长这样**：

```
[moss] region prompts = 3 (appended to prompt as a colour key)
[moss] done in 0.9 min
[moss] out=rg_test_00001_.png
```

---

## 四、参数表（这张表是核心，别改错）

| 参数 | 值 | **重要性** |
|---|---|---|
| `--control-strength` | **1.0** | 总强度，必须满 |
| `--depth-strength` | **1.0** | **绝对不能降**——降到 0.5 直接画出多个人（非白 41%→73.7%），且色块矩形边界会原样显形 |
| `--color-strength` | **0.4**（0.3–0.5） | **唯一可调的旋钮**：高了画风变硬、低了不像参考 |
| `--control-end` | 1.0 | 实测无影响（0.5 vs 1.0 几乎同一张图） |
| `--color-map` | `cm_mask3.png` | 相对 `ComfyUI\input\` |
| `--region-prompt` | 可重复 | 每条对应一个色号 |
| `--fast --cfg 1.0 --steps 8` | — | 草稿档，约 0.9 min |

**为什么 depth 不能降**（这是最反直觉的一条）：

`MOSSImageControl` 把色图和深度图拼在同一个 256 通道里，深度图负责锁「画面里有几个人」。它一弱，色图的分区暗示就压过人体轮廓 → 模型把每个色块画成一个独立的人/区域。

**给色图配 depth 的最强约束，色图的矩形边界才会被"消化"成布料分区。**

---

## 四·五、色区数能划几个（实测，2026-11-12）

**结论：上限 = 互不重叠的部位数。跟颜色数量无关。**

**五档实测**（8 步 fast / seed 9001 / 8 张裁片 8 张掩码 / 同一条主提示词）：

| 臂 | 色区数 | 覆盖% | vs参考 | 非白% | 上半 | 腰 | 下半 | **色块泄漏%** |
|---|---|---|---|---|---|---|---|---|
| z3 | 3 | 26.73 | 130.32 | 31.2 | 136.65 | 115.69 | 131.00 | 0.000 |
| z5 | 5 | 42.11 | 129.35 | 33.6 | 136.87 | 115.66 | 128.21 | 0.000 |
| z8 | 8 | 54.20 | 129.62 | 31.1 | 136.14 | 115.71 | 129.69 | 0.000 |
| **z9** | **9** | 58.89 | **128.04** | 33.7 | 135.84 | 115.70 | **125.89** | **0.000** |
| z10 | 10 | 63.57 | 129.57 | 31.3 | 136.32 | 115.89 | 129.27 | **0.042** |

色块泄漏判据 = 生成图里落在任一色板色 ±40 内的像素占比。**颜色从来不是瓶颈**（3/5/8/9 区全 0.000%）。

**真正的瓶颈是掩码像素重叠**。`z10` 把 `veil` 加进去后胸衣被漂白：

| 臂 | 胸衣局部亮度 | 胸衣局部饱和 |
|---|---|---|
| z8 | 185.9 | 32.78 |
| **z9** | **186.0** | **33.38**（最好） |
| z10 | 187.4 | **29.11**（掉 4 点） |

因为 `veil` 与 `bodice` 的像素重叠 **97.85%**，色图按 zones 顺序后画直接盖掉先画。

### 加色区前的三件事

**① 量像素级重叠**（不是 bbox 重叠）

```python
A = np.asarray(Image.open('e9m_veil.png').convert('L')) > 127
B = np.asarray(Image.open('e9m_bodice.png').convert('L')) > 127
overlap = (A & B).sum() / min(A.sum(), B.sum()) * 100   # 97.85%
```

本案例三对：

| 配对 | 像素重叠 | 处理 |
|---|---|---|
| `sleeve_l` ↔ `sleeve_r` | 100% → 修完 **0.00%** | grounding 把左右袖框成同一块，用人物中轴镜像修（中轴 = 各部位 bbox 中心的中位数） |
| `veil` ↔ `bodice` | **97.85%** | 真重叠（薄纱半透明压在胸衣上，像素级混合），**合并成一个区** |
| `sash` ↔ `sash_point` | **96.40%** | 真重叠，**合并成一个区** |

**② 真重叠只能合并，不能硬分**

薄纱是半透明的，像素值是「纱色 × 透明度 + 底色 × (1−透明度)」的混合，**没有纯纱色像素**，颜色分割只能抓到 6.4% 且碎成一地，边缘检测也没有闭合边界。合并后在文案里带一句「外面罩着两条淡青白薄纱」即可。

**③ 部位掩码要先做减法**

`legs` 的 bbox 覆盖了腰带和垂布，所以它的掩码里混着它们：

```
legs 14.89% − sash − sash_point − drape = 8.17%（纯净裤子）
```

不做减法就切子区，深度颜色会被归到「裤脚」里（实测第一次切分时洋红跑到了腰带和披风上）。

### 一个部位内部拆子区（这才是色图相对 layout 的真优势）

layout 只能画矩形（一部位一框），色图能画任意形状（**一个部位内部可以切多块**）。

`tools\split_zone_by_color.py` 在部位掩码内做 K-means，按平均亮度从暗到亮编号：

```powershell
& $py 'E:\DSH-MOSS工作区\tools\split_zone_by_color.py' `
  --ref '参考图.png' --mask 'C:\MOSS-Deploy\ComfyUI\input\legs_pure.png' `
  --k 3 --out-dir 'C:\MOSS-Deploy\ComfyUI\input' --out-prefix 'lp'
```

腿的实测：

| 子区 | 占比 | 平均 RGB | 是什么 |
|---|---|---|---|
| `lp_0` | 2.33% | (45,50,70) | 深蓝裤脚（含右侧披风） |
| `lp_1` | 3.14% | (99,115,135) | 中蓝过渡带 |
| `lp_2` | 2.70% | (168,182,192) | 浅蓝裤腿主体 |

**效果**（8 步 fast，其余全同）：

| 臂 | vs参考 | 下半 | 腿区纹理 |
|---|---|---|---|
| 8 区（legs 一整块） | 128.75 | 126.75 | 24.84 |
| **9 区（legs 拆三块）** | **126.95** | **122.13** | **23.45** |
| 参考图 | — | — | 19.62 |

**下半改善 7.56**，纹理密度也更接近参考。因为腿的 8 条细节不再挤在一个色区里互相稀释。

---

## 五、跑前检查表

| 检查项 | 合格线 |
|---|---|
| 色图尺寸 | = 生成画布尺寸 |
| 背景色 | 中灰 `(128,128,128)` |
| 色块数 | **≤ 互不重叠的部位数**（先查掩码两两像素重叠，>90% 的合并） |
| 每个色块形状 | 贴合衣物轮廓（**不能是矩形**） |
| 每条 `--region-prompt` | 有对应的色号，且色号与色图一致 |
| `--depth-strength` | **1.0** |
| `--control-strength` | **1.0**（>3 区时更要确认） |
| 深度图 | 有，且**四角已刷纯黑**（见 SOP-1 第 0 步，用 `tools\depth_to_mask.py`） |
| 常驻负向四项 | 在 |

---

## 六、六个坑（都踩过）

| 坑 | 症状 | 修法 |
|---|---|---|
| **色块画成矩形** | 直接画出多个人（非白 81%） | 用掩码切，别用矩形 |
| **白底当背景** | 姿态被拉成正面站定 | 改成中灰 128 |
| **降了 `depth-strength`** | 多主体 + 色块矩形显形 | 必须 1.0 |
| **掩码把黑背景算成前景** | 色区面积凭空大 30–50%，形状跑到背景上 | 前景判据要排除纯黑：`(min(RGB)<=238) & (max(RGB)>=16)`；参考图是黑底时必须这么做 |
| **两个色区落进同一片像素** | 后画的盖掉先画的（如胸衣被漂白、饱和掉 4 点） | 先量像素重叠，>90% 就合并成一个区，文案里带一句说明 |
| **文案写轮廓/材质大类** | 该部位形貌过度泛化 | 只写数量、排列、颜色材质 |
| **文案用制图式措辞** | 画面里冒出英文标题（实测裤腿上印了「Veil of the Azure Deepwater」） | 去掉 `fully visible` / `per leg visible` / `partially visible` 这类词，并在负向加 `text, letters, caption, title` |
| **色号与文案对不上** | 文案完全没生效 | 逐条核对 `#hex` |

---

## 七、和 GrabTag 的边界

| | GrabTag | region prompt |
|---|---|---|
| 坐标系 | **参考图**（裁片） | **生成图画布**（色图） |
| 输入 | `--image` + `--ref-labels` + `--ref-query-mask-por` | `--color-map` + `--region-prompt` |
| 管什么 | 每个部位**长什么样** | 细节纹样**画在哪一块** |
| 分辨率 | vision 侧 384 缩略图 | **16 px 一格** |

**两者能同时用**：GrabTag 管轮廓与归属、region prompt 管纹样密度，中间由深度图锁住单人。完整配方见 `约定-GrabTag终版.md`。

**但各自都能单独跑通**——先单独验证一个，再加另一个。这样出问题才知道是谁的锅。

---

## 八、出处

- 注入链：`C:\MOSS-Deploy\ComfyUI\custom_nodes\comfyui-moss-ref-bias\moss_control_embedder.py:97-100`（色图与深度图各自乘自己的 strength）
- 节点：`C:\MOSS-Deploy\ComfyUI\comfy_extras\nodes_moss_image.py` 的 `MOSSImageControl`（`color_strength` / `depth_strength`）
- 16 px 的上限与「可分辨 vs 可影响」：`notes\对比-色图与layout-定位到注入层.md` §2.5
- 为什么降 depth 会多主体：`notes\2026-11-11-经验-色图与深度图共享strength导致多主体.md` §4.3
- 色图要按部位划：`notes\2026-11-11-经验-色图要按部位划不能按颜色反推.md`
- **色区数上限与三对重叠的完整实测**：`notes\2026-11-12-经验-色图区数上限-不重叠部位数.md`
- 色板定义：`E:\DSH-MOSS工作区\tools\detail_colormap.py:36`（10 色）
- 子区切分工具：`E:\DSH-MOSS工作区\tools\split_zone_by_color.py`（部位掩码内 K-means 切子区）
