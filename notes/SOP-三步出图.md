> ⚠️ **这份文档的「三步流程」部分已被 [SOP-1-原图复刻流程.md](SOP-1-原图复刻流程.md) 取代**（那条是定稿版，含两个脚本与实测数据）。
> **仍然有效的部分**：§提示词格式（<|概念|> 闭合标签分块 + 拆法表 + 常见错误）—— 那一节是 SOP-1 的格式依据，继续维护在这里。

# SOP · 三步出图（部位切分 → GrabTag 分割 → 细节分区）

> **这条 SOP 解决什么**：把一张参考图变成「主提示词 + GrabTag 掩码 + region prompt 色图」三样东西，让 MOSS 生成一张同款但可控的图。
>
> **它依赖两件事**：`手册-GrabTag.md`（参考侧）与 `手册-region-prompt.md`（画布侧）。这份文件只讲**怎么串起来**。

---

## 零、三步总览

```
参考图
  │
  ├─[1] 按部位切块 → 逐块反写 → { trunk, details[] }
  │        ├─ trunk  ──────────────→ 主提示词（前端：尺寸/颜色/位置）
  │        └─ details ─────────────→ region prompt（后端：纹样/材质）
  │
  ├─[2] trunk 里选 ≤8 个关键部件 → GrabTag 裁片 + 掩码 + tag 命名
  │
  └─[3] grounding 定位细节 → 分区色图（≤3 区）→ region prompt 文案
                                    │
                                    ↓
                         moss_run.py 一次生成
```

**三个产物**：`parts_all.json`（中间数据）/ `gt2_*.png` + `gtm2_*.png`（GrabTag 素材）/ `cm_*.png`（色图）

---

## 第一步：切块反写 + 主干细节分离

### 做什么

按人体部位把参考图切成小方块（**小方块 → 反写时注意力集中，描述更细**），逐块问多模态模型，产出两个字段。

### 输入 → 输出

| 输入 | 输出 |
|---|---|
| 参考图 + grounding 给的部位 bbox | `C:\MOSS-Deploy\work\parts_all.json`，每个部位：`{id, label, trunk, details[], bbox_px, bbox_abs, crop, area_pct}` |

**两个字段的分工**：

| 字段 | 内容 | 字数实测 | 去哪 |
|---|---|---|---|
| `trunk` | 形状 / 主色 / 材质 / 轮廓，一句话 | 合计 1101 字 | **主提示词前部** |
| `details[]` | 纹样 / 数量 / 位置 / 质感，8–22 词一条 | 合计 9299 字 | **region prompt 后部** |

**这个 1:8.5 的比例就是「主干 vs 细节」的自然分界，不需要人工划分。**

### 命令

```powershell
$py = 'C:\MOSS-Deploy\venv\Scripts\python.exe'
& $py 'E:\DSH-MOSS工作区\tools\describe_parts.py' `
  --image 'C:\MOSS-Deploy\ComfyUI\input\你的参考图.png' `
  --grounding 'C:\MOSS-Deploy\work\grounding.json' `
  --out 'C:\MOSS-Deploy\work\parts_all.json' `
  --shrink 0.92 --upscale 1.5
```

（`grounding.json` 由 `tools\ground_regions.py` 产出，含每个部位的 `pixel_box`。）

### 检查点

| 项 | 合格线 |
|---|---|
| 部位数 | 8–12 个 |
| 每个 `trunk` | 一句话、不超 60 词 |
| 每个 `details[]` | 3–8 条，**含数量词**（`four large diamond appliqués`） |
| `details` 里有没有轮廓词 | 有就删（轮廓归 trunk） |

---

## 第二步：选关键部件 → GrabTag 分割图

### 做什么

从 `trunk` 里挑出**最需要在画面上被精确定位的 ≤8 个部件**，每个做一张裁片 + 一张掩码，并给它一个 tag 名。

### 怎么选（这条决定成败）

**优先级从高到低**：

| 优先 | 判据 | 例子 |
|---|---|---|
| 1 | 面积大、决定整体轮廓 | `legs`（灯笼裤）、`drape`（垂布） |
| 2 | 位置容易漂移 | `sash`（腰带，容易画高/画低） |
| 3 | 有大块独特色彩/材质 | `bodice`、`veil` |
| 4 | 需要和小件配对 | `sash_point`（腰前短垂片） |
| — | **不要选**：面积太小（< 3% 画布）、形状模糊、与别的部件重叠严重 | `orb`（腰侧球）、`hair`（头发常被裙子挡住） |

**上限 8 个是真限制**（`MOSSSetRefQueryMaskPor` 只有 `image_0`…`image_7`）。

### 输入 → 输出

| 输入 | 输出 |
|---|---|
| `parts_all.json` 的 `bbox_px` | `ComfyUI\input\gt2_<tag>.png`（裁片，最长边 512）<br>`ComfyUI\input\gtm2_<tag>.png`（掩码，画布尺寸黑白图） |

### 命令

```powershell
$py = 'C:\MOSS-Deploy\venv\Scripts\python.exe'
& $py -c @"
import json, io, numpy as np
from PIL import Image
W,H = 1216,1632
picked = ['bodice','drape','legs','sash','sash_point','sleeve_r','veil','hair']   # ≤8
items = {i['id']: i for i in json.load(io.open(r'C:\MOSS-Deploy\work\parts_all.json', encoding='utf-8'))}
ref = Image.open(r'C:\MOSS-Deploy\ComfyUI\input\你的参考图.png').convert('RGB')
for pid in picked:
    x0,y0,x1,y1 = items[pid]['bbox_px']
    # 裁片
    c = ref.crop((x0,y0,x1,y1)); c.thumbnail((512,512), Image.LANCZOS)
    c.save(r'C:\MOSS-Deploy\ComfyUI\input\gt2_%s.png' % pid)
    # 掩码（画布坐标系，白色=允许这块裁片负责的区域）
    m = np.zeros((H,W), np.uint8); m[y0:y1, x0:x1] = 255
    Image.fromarray(m).save(r'C:\MOSS-Deploy\ComfyUI\input\gtm2_%s.png' % pid)
    print(pid, (x0,y0,x1,y1))
"@
```

### 写前部提示词

**格式固定：每句 = 画布部位 + is/are + `<tag>`，不写任何形貌。**

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

### 检查点

| 项 | 合格线 |
|---|---|
| 裁片数 = 标签数 = 掩码数 | ≤8，三者一致 |
| 每张掩码 | 白色区域 = 该部件在画布上的实际位置 |
| 每句提示词 | 有 `<tag>`、无形貌词 |
| 末尾两句防漂浮 | 在 |

---

## 第三步：细节反向定位 → region prompt

### 做什么

`details[]` 里那些「纹样/数量」要落到画布的具体区域上。做法是**先定位、再分区**。

### 怎么定位（两种）

| 方法 | 适用 | 做法 |
|---|---|---|
| **继承 bbox**（推荐） | 细节所属部位已经在第二步选进 GrabTag | 直接用该部位的 `bbox_px` 作为色块位置 |
| **单独 grounding** | 细节跨部位，或要更小的框 | `tools\ground_regions.py` 用「该细节的描述」当 query 反查 |

### 色图规则（三条，违反直接失败）

| 规则 | 违反的后果 |
|---|---|
| **形状必须贴合衣物轮廓**（用掩码，不能用 `draw.rectangle`） | 直接画出多个人 |
| **色块数 ≤ 3** | 更多色块被理解成更多主体 |
| **背景中灰 `(128,128,128)`** | 白底会把姿态拉成正面站定 |

### 命令

```powershell
& $py -c @"
import json, io, numpy as np
from PIL import Image
W,H = 1216,1632
# 三个色区 + 各自的纯色（互不相同、与灰底差距大）
plan = [('legs','#ff00ff'), ('sash','#0000ff'), ('bodice','#9fe8e0')]
base = np.full((H,W,3), 128, np.uint8)          # 中灰底，必须
for pid, hexc in plan:
    m = np.asarray(Image.open(r'C:\MOSS-Deploy\ComfyUI\input\gtm2_%s.png' % pid)
                   .convert('L').resize((W,H), Image.NEAREST)) > 127
    base[m] = tuple(int(hexc[i:i+2],16) for i in (1,3,5))
Image.fromarray(base).save(r'C:\MOSS-Deploy\ComfyUI\input\cm_3.png')
"@
```

### 写后部提示词

**每个色区一句，格式固定**：`the <#hex> area carries <details 用分号合并>.`

```
the #ff00ff area carries gold-thread vertical stripes running parallel down the front of each leg; navy-edged diamond appliqués in four rows per leg, each diamond set with a pale blue gem, linked by gold chains hung with red-brown beads and small silver star pendants.

the #0000ff area carries four large diamond-shaped appliqués in faceted violet crystal set in gold filigree, arranged horizontally across the front center; three dangling teardrop-shaped clear crystals along the lower edge.

the #9fe8e0 area carries a central ornamental motif of gold filigree with purple and white mosaic tiles; an oval pearl in a scalloped gold bezel surrounded by six small sapphire cabochons; two fan-shaped mosaic panels flanking it, each of twelve diamond-cut purple glass tiles in three rows of four.
```

### 检查点

| 项 | 合格线 |
|---|---|
| 色块数 | ≤3，且每个都有对应的 `--region-prompt` |
| 色块形状 | 来自掩码，不是矩形 |
| 背景色 | `(128,128,128)` |
| 每条文案 | 有对应 `#hex`、写的是数量/排列/材质，不写轮廓 |

---

## 提示词格式：`<|概念|>` 闭合标签分块

**用闭合标签把提示词切成 3–5 块，一行一块、成对闭合、不嵌套。**

依据（`moss-image-prompt-skill` 实测）：`<|...|>…<|/...|>` 结构进 DiT 前的净有效信噪比是**逗号拼接的 12.7 倍**、是 `Style: …\nScene: …` 换行格式的 **3.2 倍**。Qwen3.5 的原生聊天模板就是 `<|im_start|>` 这一套，所以它认识这个分隔符。

### 完整模板（八裁片版，实测单人）

```text
<|style_and_lighting|>A single standing woman in a full-body costume, seen from the front, on a plain off-white background, soft even studio light, no cast shadow on the background.<|/style_and_lighting|>
<|upper_body|>Her long braided hair is <hair>. Her head and shoulders are veiled by <veil>. Her upper chest and bust are covered by <bodice>. Her right upper arm carries <sleeve_r>.<|/upper_body|>
<|waist_and_hip|>Her waist is wrapped in <sash>. A short panel hangs down the front of her waist: <sash_point>. A long panel hangs from her left hip down to the floor: <drape>.<|/waist_and_hip|>
<|legs|>Her legs, from waist to ankle, are <legs>.<|/legs|>
<|constraints|>For every named body region, use the garment from the reference given for that region and no other. Do not draw any of these parts as separate objects beside the figure; each is worn on the body.<|/constraints|>
```

### 两条纪律（来自技能的单向注意力实测）

| 纪律 | 原因 |
|---|---|
| **第 1 块写风格与光影** | Qwen3.5 从左到右单向因果，光影词放在衣物名词后面时**只画出一根灯管而不染色**；放最前才能染全局 |
| **块按人体从上到下排** | 前面的块给后面的块定调；把最需要"定调"的部分放前面 |

### 拆法

| 段 | 去向 |
|---|---|
| 整段 `<\|…\|>` 文本 | 原样传给 `--prompt`（**不需要拆**，闭合标签本身就在 prompt 里） |
| `<hair>` 这类**裸尖括号**（不带竖线） | 与 `--ref-labels` 逐字对应，是 tag 引用不是块标记 |
| `the #hex area carries …` | 逐条 `--region-prompt` |

**注意区分两种尖括号**：`<|upper_body|>` 是**块标记**（带竖线，只能是 3–5 块），`<hair>` 是**tag 引用**（不带竖线，与裁片数量一致）。两者不要混用。

### 常见错误

| 错 | 对 |
|---|---|
| `<\|hair\|>` | `<hair>`（tag 引用不带竖线） |
| 块内再套块 | 一块一行、平铺 |
| 8 个块按部位拆 | 合并成 3–5 块（上/中/下/约束） |
| 光影写在第 2 块 | 放第 1 块 |

---

## 完整命令

```powershell
$py   = 'C:\MOSS-Deploy\venv\Scripts\python.exe'
$tags = @('hair','veil','bodice','sleeve_r','sash','sash_point','drape','legs')
$img  = ($tags | ForEach-Object { "gt2_$_.png:raw" }) -join ','
$msk  = ($tags | ForEach-Object { "gtm2_$_.png" }) -join ','

# 从 <> 分段文件里取 front / back
$src   = Get-Content '你的提示词.txt' -Raw -Encoding UTF8
$front = [regex]::Match($src, '<front>([\s\S]*?)</front>').Groups[1].Value.Trim()
$backs = [regex]::Matches($src, '(?m)^the #\w+ area carries .+$') | ForEach-Object { $_.Value }
$rArgs = @(); foreach ($b in $backs) { $rArgs += @('--region-prompt', $b) }

& $py 'C:\MOSS-Deploy\moss_run.py' --port 8190 `
  --image $img --ref-labels ($tags -join ',') --ref-query-mask-por $msk `
  --depth-map 'C:\MOSS-Deploy\ComfyUI\input\你的深度图.png' `
  --color-map 'cm_3.png' @rArgs `
  --control-strength 1.0 --color-strength 0.4 --depth-strength 1.0 --control-end 1.0 `
  --w 1216 --h 1632 --steps 8 --cfg 1.0 --fast --seed 9001 `
  --edit-format ai-toolkit --ref-no-pos 1 `
  --negative 'worst quality, bad anatomy, watermark, jpeg artifact' `
  --prompt $front --prefix 'sop3'
```

> ⚠️ **`--prompt` 与 `--prompt-file` 不是同义词**：上面用 `--prompt $front` 是**把变量内容（提示词正文）直接传进去**，这是对的；如果提示词存在文件里，必须用 `--prompt-file '<路径>'`。写成 `--prompt '<路径>'` 会把路径字符串当提示词送进模型，表现为「改了文件、图像完全不变」（`moss_run.py:1084-1086` 只有 `args.prompt_file` 才 `open().read()`）。

---

## 参数（照抄，三处不能改）

| 参数 | 值 | 为什么 |
|---|---|---|
| `--control-strength` | **1.0** | 低了深度图被砍半 |
| `--depth-strength` | **1.0** | **降到 0.5 直接画出多个人** |
| `--color-strength` | **0.4**（0.3–0.5） | 唯一可调旋钮：高了画风硬、低了不像参考 |
| `--ref-no-pos` | `1` | 不让参考复刻自己的布局 |
| `--fast --cfg 1.0 --steps 8` | — | 草稿档约 1 min |

---

## 跑前检查表（按顺序过一遍）

1. `parts_all.json` 的部位数 8–12、`details` 都带数量词
2. 选中的部件 ≤8 个，且都是面积大 / 容易漂 / 有大块独特色
3. 裁片 `gt2_*.png` 与掩码 `gtm2_*.png` 数量与标签一致，都在 `input\` 根目录
4. `<front>` 里每句都有 `<tag>`、无形貌词、末尾两句在
5. 色图 ≤3 区、形状来自掩码、背景中灰
6. `<back>` 每行有对应 `#hex`，且与色图里的色号一致
7. 深度图存在
8. 常驻负向四项在

---

## 现在缺什么（下一步要补）

| 缺的 | 影响 | 临时办法 |
|---|---|---|
| **第二步的挑选规则没有脚本** | 现在靠人判断选哪 8 个 | 按上面「怎么选」的四条优先级人工挑 |
| **第三步「细节单独 grounding」没有接成色图** | 细节跨部位时只能整块给 | 用该部位 bbox 近似 |
| **`<>` 拆分没有独立脚本** | 上面命令里用 `[regex]` 内联拆 | 已够用；要复用可抽成 `tools\split_prompt.py` |

---

## 出处

- 三步定义：用户 m06238 原话
- `trunk` / `details` 的结构与实测字数：`C:\MOSS-Deploy\work\parts_all.json`（11 部位）
- GrabTag 细节：`notes\手册-GrabTag.md`
- region prompt 细节：`notes\手册-region-prompt.md`
- 三 seed 验证（纯 tag + 3 色区 + `color 0.4 / depth 1.0`）：`notes\约定-GrabTag终版.md`
