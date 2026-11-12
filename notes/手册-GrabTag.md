# GrabTag 使用手册

> **一句话**：把参考图按人体部位切成几块，每块起个名字，然后在提示词里说「这个部位用这个名字的那块」。
>
> **它解决的问题**：参考图只有一张时，模型分不清你要它参考的是上衣还是裤子。切开后就能逐部位指名道姓。

---

## 一、它是什么，不是什么

| | |
|---|---|
| **是** | 参考侧的**部位绑定**机制：`--image` 切块 + `--ref-labels` 命名 + `--ref-query-mask-por` 限定每块能管画面哪一块 |
| **不是** | 色图分区（那是 `--color-map`，见 `手册-region-prompt.md`） |
| **不负责** | 布局、姿态、画风、整体构图 |

**判断该不该用**：当你要「照着这张图的上衣、那条图的裤子」时用它；当你要「这块区域画成这个纹样」时用 region prompt。

---

## 二、三步

### 第 1 步：切裁片

按人体部位切，**一部位一块**，最多 8 块。

```powershell
# 需要 Python + Pillow；bbox 是参考图上的像素坐标 (x0,y0,x1,y1)
$py = 'C:\MOSS-Deploy\venv\Scripts\python.exe'
& $py -c @"
from PIL import Image
im = Image.open(r'C:\MOSS-Deploy\ComfyUI\input\你的参考图.png').convert('RGB')
# 每块单独存，最长边 512 足够（合计约 3147 tok）
for name, box in {'hair':(377,14,645,361), 'bodice':(522,328,704,554)}.items():
    c = im.crop(box)
    c.thumbnail((512,512), Image.LANCZOS)
    c.save(r'C:\MOSS-Deploy\ComfyUI\input\gt2_%s.png' % name)
"@
```

**要求**：
- 文件名用 `gt2_<部位>.png`，**放 `ComfyUI\input\` 根目录**
- 最长边 512（更大没用，vision 侧本来就缩到 384）

**怎么找 bbox**：用 `tools\ground_regions.py`（`qwen3-vl-plus` 做 2D grounding），或手量。产出格式 `[{id, label, bbox_px}]`。

### 第 2 步：切掩码

掩码 = **这块裁片在画布上允许负责的区域**。同尺寸的黑白图，白色 = 允许。

```powershell
& $py -c @"
import numpy as np
from PIL import Image
W,H = 1216,1632
plans = {'hair':(377,14,645,361), 'bodice':(522,328,704,554)}   # 画布上对应位置
for name, (x0,y0,x1,y1) in plans.items():
    m = np.zeros((H,W), np.uint8); m[y0:y1, x0:x1] = 255
    Image.fromarray(m).save(r'C:\MOSS-Deploy\ComfyUI\input\gtm2_%s.png' % name)
"@
```

**三个坑**：
1. **必须放 `ComfyUI\input\` 根目录**——子目录会报 `Invalid image file`
2. **用统一前缀**（如 `gtm2_`）——input 里可能有同名的旧文件，会被静默用错
3. 掩码是「画布坐标系」的，不是裁片坐标系

### 第 3 步：写提示词

**每个部位一句，格式固定 `Her <部位> is <tag>.`，不写任何形貌描述。**

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

**三条硬性要求**：

| 要求 | 违反的后果 |
|---|---|
| **必须有 `<tag>` 引用** | 空挂参考 = 完全没用（实测 vs参考 131.01，比不挂还差） |
| **必须反向**（部位 → 裁片） | 正向写「`<tag>` 是什么」会画出漂浮物（实测差 5.85） |
| **不写形貌**（材质/轮廓/边界） | 给腿赚 3.2、给胸衣赔 6.6，净收益为负 |
| **末尾两句别省** | 省了会冒出漂浮的辫子和装饰片 |

---

## 三、完整命令（直接改路径就能跑）

```powershell
$py   = 'C:\MOSS-Deploy\venv\Scripts\python.exe'
$ids  = @('hair','veil','bodice','sleeve_r','sash','sash_point','drape','legs')
$img  = ($ids | ForEach-Object { "gt2_$_.png:raw" }) -join ','
$msk  = ($ids | ForEach-Object { "gtm2_$_.png" }) -join ','

& $py 'C:\MOSS-Deploy\moss_run.py' --port 8190 `
  --image $img `
  --ref-labels ($ids -join ',') `
  --ref-query-mask-por $msk `
  --depth-map 'C:\MOSS-Deploy\ComfyUI\input\你的深度图.png' `
  --control-strength 1.0 --depth-strength 1.0 --control-end 1.0 `
  --w 1216 --h 1632 --steps 8 --cfg 1.0 --fast --seed 9001 `
  --edit-format ai-toolkit --ref-no-pos 1 `
  --negative 'worst quality, bad anatomy, watermark, jpeg artifact' `
  --prompt (Get-Content '你的前部提示词.txt' -Raw -Encoding UTF8) `
  --prefix 'gt_test'
```

**成功的日志长这样**：

```
[moss] ref-labels 'hair,veil,bodice,...': 用自定义 tag 代替 Picture N 标记参考
[moss] references=8
[moss] done in 1.0 min
[moss] out=gt_test_00001_.png
```

**看到 `[moss-ref-label] ref_labels 数量 N != 参考数 M，回退到 Picture N` 就是数量没对上**，先修这个。

---

## 四、参数表

| 参数 | 值 | 说明 |
|---|---|---|
| `--image` | `a.png:raw,b.png:raw,...` | **必须带 `:raw`**（不缩放到 384） |
| `--ref-labels` | `a,b,...` | 与 `--image` **同序同数**，不能有空格 |
| `--ref-query-mask-por` | `ma.png,mb.png,...` | 与上面同序同数，路径相对 `input\` |
| `--ref-no-pos` | `1` | 让参考不再按其自身布局复刻 |
| `--control-strength` | `1.0` | **必须满** |
| `--depth-strength` | `1.0` | **必须满**（降了直接画出多个人） |
| `--control-end` | `1.0` | 实测无影响 |
| `--fast --cfg 1.0 --steps 8` | — | 草稿档，约 1 min |

---

## 五、跑前检查表

| 检查项 | 合格线 |
|---|---|
| 裁片数 = `--ref-labels` 数 = 掩码数 | 三者一致 |
| 每张裁片文件名 | `gt2_<部位>.png`，在 `input\` 根目录 |
| prompt 里的 `<tag>` 拼写 | 与 `--ref-labels` **逐字一致** |
| 每句是否只写「部位 + tag」 | 有材质/轮廓词就删掉 |
| 末尾两句防漂浮声明 | 在 |
| 深度图 | 有（`--depth-map`） |
| 常驻负向四项 | 在 |

---

## 六、五个坑（都踩过）

| 坑 | 症状 | 修法 |
|---|---|---|
| **裁片数与标签数不一致** | 日志报「回退到 Picture N」，参考全部失效 | 数一遍 |
| **掩码放子目录** | `Invalid image file: xxx.png` | 挪到 `input\` 根目录 |
| **掩码撞旧文件** | 不报错，但效果莫名其妙 | 换前缀 |
| **prompt 里没有 `<tag>`** | 图与不挂参考几乎一样 | 每句都要有 |
| **写了形貌描述** | 复杂部位（胸衣）细节变糊 | 删掉，只留部位 + tag |

---

## 七、和 region prompt 的边界

| | GrabTag | region prompt |
|---|---|---|
| 坐标系 | **参考图**（裁片） | **生成图画布**（色图） |
| 管什么 | 每个部位**长什么样** | 细节纹样**画在哪一块** |
| 参数 | `--image` / `--ref-labels` / `--ref-query-mask-por` | `--color-map` / `--region-prompt` |

**两者可以同时用**（这才是完整配方，见 `约定-GrabTag终版.md`），但**各自都能单独跑通**——先单独验证一个，再加另一个。

---

## 八、出处

- 实现：`C:\MOSS-Deploy\ComfyUI\comfy_extras\nodes_moss_image.py:151-160`（标记）、`C:\MOSS-Deploy\ComfyUI\custom_nodes\comfyui-moss-ref-bias\moss_ref_mask.py:41-93`（掩码节点）、`C:\MOSS-Deploy\ComfyUI\comfy\ldm\moss_image\model.py:419-442`（注意力落点）
- 四臂实测与裁片预算：`notes\机制-GrabTag-当前实现.md`
- 和另一个功能怎么配合：`notes\约定-GrabTag终版.md`
- 为什么不写形貌：同上 §四
