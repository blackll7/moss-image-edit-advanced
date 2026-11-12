# MOSS GrabTag / region prompt / 三条 SOP

本仓库只收录 MOSS-Image 出图工作流里的**三块可复用资产**，不含模型、素材库、过程稿与本机部署。

| 块 | 解决什么 | 入口 |
|---|---|---|
| **一、GrabTag** | 让参考图的「某个部位」被模型准确定位：裁片 + `<tag>` + 色图 + 掩码 | [`notes/手册-GrabTag.md`](notes/手册-GrabTag.md) |
| **二、region prompt** | 给每个色区写「位置 + 形状 + 颜色纹样材质」，把整图描述拆成逐区描述 | [`notes/手册-region-prompt.md`](notes/手册-region-prompt.md) |
| **三、三条 SOP** | 把上面两块串成可执行流程：复刻 / 改部件 / 换姿势 | [`notes/SOP-1-原图复刻流程.md`](notes/SOP-1-原图复刻流程.md) |

---

## 一、GrabTag

### 执行文件

| 文件 | 作用 |
|---|---|
| [`tools/extract_colormap.py`](tools/extract_colormap.py) | 从过渡图按调色板提取色图（GrabTag 两步生成的第二步输入之一） |

```bash
python tools/extract_colormap.py 过渡图.png --palette palette11.json --out 色图.png --stats
```

### 文档

| 文件 | 内容 |
|---|---|
| [手册-GrabTag.md](notes/手册-GrabTag.md) | 是什么、两种用法、参数 |
| [手册-GrabTag-使用.md](notes/手册-GrabTag-使用.md) | 逐步骤操作 |
| [机制-GrabTag-当前实现.md](notes/机制-GrabTag-当前实现.md) | 代码层怎么走通（参考 latent → attention KV） |
| [机制-三个定位系统-GrabTag-layout-色图.md](notes/机制-三个定位系统-GrabTag-layout-色图.md) | GrabTag vs layout vs 色图，三套定位机制的区别与重叠 |
| [流程-GrabTag两步生成-锁定版.md](notes/流程-GrabTag两步生成-锁定版.md) | 两步生成的锁定流程 |
| [2026-11-10-GrabTag-ref_tag-可见细节写法.md](notes/2026-11-10-GrabTag-ref_tag-可见细节写法.md) | `ref_tag` 的六条写法规则：颜色/材质 + 品类 + 纹样 + 位置 |

---

## 二、region prompt

### 执行文件

按调用顺序排列：

| 文件 | 作用 |
|---|---|
| [`tools/ground_regions.py`](tools/ground_regions.py) | Qwen3-VL 做 2D grounding，把参考图按部位裁出来 → `grounding.json` |
| [`tools/describe_crops.py`](tools/describe_crops.py) | 对每块裁图详细反写，产出 `--region-prompt` 草稿 |
| [`tools/describe_parts.py`](tools/describe_parts.py) | 按人体部位切图、逐块反写，主干与细节分离 → `parts.json` |
| [`tools/describe_subzones.py`](tools/describe_subzones.py) | 把一个部位的掩码竖向切段，逐段反写（拿到「几个」这类数量信息） |
| [`tools/region_ask.py`](tools/region_ask.py) | 给定一张图 + 一个位置，问「这块是什么」 |
| [`tools/bbox_to_layout.py`](tools/bbox_to_layout.py) | `grounding.json` 的 bbox + 描述 → MOSS `layout.json` |
| [`tools/parts_to_layout.py`](tools/parts_to_layout.py) | `parts.json` → 主干提示词 + layout 两条通道 |

### 文档

| 文件 | 内容 |
|---|---|
| [手册-region-prompt.md](notes/手册-region-prompt.md) | 三段式格式、每段写什么、长度预算、常见错误 |

---

## 三、三条 SOP

| SOP | 用途 | 关键产出 |
|---|---|---|
| [SOP-1 原图复刻](notes/SOP-1-原图复刻流程.md) | 照着一张参考图生成同款，换姿势 / 换画风前先拿到干净基准 | vs 参考 126.04 |
| [SOP-2 原图调整](notes/SOP-2-原图调整流程.md) | 在 SOP-1 产物上只改一个部件（例：裤子化成冰衣） | 冰衣 19.17 |
| [SOP-3 更换姿势](notes/SOP-3-更换姿势流程.md) | 人物与服装不变，换一个身体姿势 | 614 行完整流程 + 两个案例 |

### SOP 专用执行文件

| 文件 | 作用 |
|---|---|
| [`tools/pick_parts.py`](tools/pick_parts.py) | 从 `parts_all.json` 选关键部件 → 切裁片 + 切掩码 |
| [`tools/depth_to_mask.py`](tools/depth_to_mask.py) | 深度图 → 人物剪影 mask + 背景刷黑的深度图（Otsu + 形态学 + 最大连通域 + 填洞） |
| [`tools/clean_depth.py`](tools/clean_depth.py) | 把深度图背景刷纯黑（SOP 第 0 步） |
| [`tools/detail_colormap.py`](tools/detail_colormap.py) | 把 `details[]` 变成分区色图 + region prompt 文案 |

### 样本

四个自包含样本，每个都有 `00-*` 到 `04/05-*` 的分步产物 + README：

```
examples/
├── SOP-1-20261112-四星2冰蓝舞娘/          36 文件 / 6.2 MB
├── SOP-2-20261112-四星2冰衣-24step/       38 文件 / 7.5 MB
├── SOP-3-20261112-四星2跪姿/               9 文件 / 4.1 MB
└── SOP-3-20261112-四星2-standing-split/   25 文件 / 7.1 MB
```

样本内部结构（以 SOP-3 standing-split 为例）：

```
00-depth/        第 0 步：深度图刷黑（ex3_black.png 喂 --depth-map，ex3_mask.png 检查用）
01-transition/   第 1 步：纯 T2I 过渡图（只传 --depth-map，control 0.6 / end 0.6）
02-colormap/     第 2 步：色图 + 第二深度图 + 8 张画布掩码 cvm_*.png
03-prompt/       主 prompt（五块结构）+ region prompt（三段式）
04-output/       第 3 步各档产物（含失败版，便于对比）
README.md        逐档量化数据与踩坑记录
```

---

## 依赖（不在本仓库）

本仓库只有脚本与文档，**不含**：

- MOSS-Image 模型、ComfyUI 部署、`moss_run.py` / `moss_main.py`（本机在 `C:\MOSS-Deploy\`）
- 参考图、素材库、训练集、过程稿
- 三个 SOP 里引用的规则文档（`notes/规则-*.md`）与经验卡 —— 那是工作区的内部资产，需要时另行同步

脚本里的本机绝对路径（`C:\MOSS-Deploy\…`）按原样保留，便于对照实际部署；换机器时需要改这些常量。

---

## 三条已验证的关键结论

1. **掩码是画布坐标，不是参考图坐标** —— `--ref-query-mask-por` 的掩码描述「画布上哪块区域允许读第 i 张参考」，换姿势后新旧几何对不上（`drape` IoU 0.00%），必须从新色图反推 `cvm_*.png`。

2. **`--control-strength` 与 `--image-strength` 各管一件事** —— 前者是色图 + 深度图的总闸（`1.0` 会让参考裁片被当成装饰画进画面，拼贴 73.4%；`0.9` 是平衡点），后者管参考对画面的整体影响（`0.5` 把拼贴压到 4.3% 而纹样不退化）。

3. **24 步会把材质词放大** —— region prompt 里写 `sheer fabric`，8 步 fast 下量刚好，24 步会被材质先验放大成完全透明（裤腿从 (129,167,185) 蓝掉到 (175,181,182) 灰白）。提高 `--image-strength` 无效，必须把 trunk 改成显式不透明。
