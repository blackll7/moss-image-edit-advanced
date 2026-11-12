# MOSS GrabTag / region prompt / 三条 SOP

在 MOSS-Image（Qwen3.5-9B 文本编码器 + 5B 单流 DiT）上做**可控换装出图**的一套工具与流程。

解决的问题：参考图给得再清楚，「哪个部位长什么样」也很难稳定落到生成结果里。这三块分别负责**定位**、**描述**、**串流程**。

| 块 | 解决什么 | 一句话机制 |
|---|---|---|
| **一、GrabTag** | 让参考图的某个部位被模型准确定位 | 把参考切成裁片，每片挂一个 `<tag>`，用画布掩码限定「哪块区域能读哪张裁片」 |
| **二、region prompt** | 让每个区域有独立的文字描述 | 按色图把整图描述拆成逐区三段式（位置 / 形状 / 颜色纹样材质） |
| **三、三条 SOP** | 把上面两块串成能重复执行的流程 | 复刻基准 → 只改一个部件 → 换姿势而保服装 |

---

## 环境要求

| 项 | 版本 |
|---|---|
| Python | 3.10+（实测 3.12.14） |
| Pillow | 13.0.0 |
| numpy | 2.5.4 |
| opencv-python | 仅 `tools/depth_to_mask.py` 需要 |
| MOSS-Image + ComfyUI | 不在本仓库，需自行部署（本机在 `C:\MOSS-Deploy\`） |

脚本里的 `C:\MOSS-Deploy\…` 是原机器的部署路径，换机器时改这些常量即可。涉及视觉模型反写的脚本（`ground_regions` / `describe_*` / `region_ask`）需要能访问对应的模型服务。

---

## 快速开始

以 SOP-3 的 standing split 样本为例（框内是产物，可对照）：

```bash
# 第 0 步：深度图 → 人物剪影 + 背景刷黑
python tools/depth_to_mask.py 姿势深度图.png input/s4 --width 1216 --height 1632 --feather 2

# 第 1 步：纯 T2I 过渡图（只传深度图，control 收在 0.6）
python C:/MOSS-Deploy/moss_run.py --fast --w 1216 --h 1632 --seed 9001 \
  --depth-map input/s4_black.png --control-strength 0.6 --control-end 0.6 \
  --prompt-file work/prompt_trans.txt

# 第 2 步：从过渡图提色图（10 区）+ 反推第二深度图 + 从色图反推画布掩码
python tools/extract_colormap.py output/过渡图.png --palette palette11.json --out input/s4_cm.png --stats

# 第 3 步：A+B 精修（8 裁片 + 色图 + 深度图 + 画布掩码）
python C:/MOSS-Deploy/moss_run.py --fast --w 1216 --h 1632 --seed 9001 \
  --edit-format ai-toolkit --image "input/e9_legs.png:raw, …" \
  --ref-labels 'legs,drape,bodice,…' \
  --ref-query-mask-por "input/cvm_legs.png, …" \
  --color-map input/s4_cm.png --depth-map input/s4_depth2.png \
  --control-strength 0.9 --control-start 0 --control-end 1.0 \
  --image-strength 0.5 --ref-no-pos 1 \
  --prompt-file work/prompt_main_blocks.txt \
  --region-prompt-file work/rp_s4.txt
```

完整命令与每步的检查点见 [SOP-3](notes/SOP-3-更换姿势流程.md)，产物对照见 [`examples/SOP-3-…-standing-split/`](examples/)。

---

## 一、GrabTag

### 执行文件

| 文件 | 作用 |
|---|---|
| [`tools/extract_colormap.py`](tools/extract_colormap.py) | 从过渡图按调色板提取色图（GrabTag 两步生成的第二步输入之一） |

### 文档

| 文件 | 内容 |
|---|---|
| [手册-GrabTag.md](notes/手册-GrabTag.md) | 是什么、两种用法、参数 |
| [手册-GrabTag-使用.md](notes/手册-GrabTag-使用.md) | 逐步骤操作 |
| [机制-GrabTag-当前实现.md](notes/机制-GrabTag-当前实现.md) | 代码层怎么走通（参考 latent → attention KV） |
| [机制-三个定位系统-GrabTag-layout-色图.md](notes/机制-三个定位系统-GrabTag-layout-色图.md) | GrabTag vs layout vs 色图，三套定位机制的区别与重叠 |
| [流程-GrabTag两步生成-锁定版.md](notes/流程-GrabTag两步生成-锁定版.md) | 两步生成的锁定流程 |
| [2026-11-10-GrabTag-ref_tag-可见细节写法.md](notes/2026-11-10-GrabTag-ref_tag-可见细节写法.md) | `ref_tag` 六条规则：颜色/材质 + 品类 + 纹样 + 位置 |

---

## 二、region prompt

### 执行文件（按调用顺序）

| 文件 | 作用 |
|---|---|
| [`tools/ground_regions.py`](tools/ground_regions.py) | Qwen3-VL 做 2D grounding，按部位裁图 → `grounding.json` |
| [`tools/describe_crops.py`](tools/describe_crops.py) | 对每块裁图详细反写，产出 `--region-prompt` 草稿 |
| [`tools/describe_parts.py`](tools/describe_parts.py) | 按人体部位切图、逐块反写，主干与细节分离 → `parts.json` |
| [`tools/describe_subzones.py`](tools/describe_subzones.py) | 把部位掩码竖向切段逐段反写（拿到「几个」这类数量信息） |
| [`tools/region_ask.py`](tools/region_ask.py) | 给定一张图 + 一个位置，问「这块是什么」 |
| [`tools/bbox_to_layout.py`](tools/bbox_to_layout.py) | `grounding.json` 的 bbox + 描述 → MOSS `layout.json` |
| [`tools/parts_to_layout.py`](tools/parts_to_layout.py) | `parts.json` → 主干提示词 + layout 两条通道 |

### 文档

| 文件 | 内容 |
|---|---|
| [手册-region-prompt.md](notes/手册-region-prompt.md) | 三段式格式、每段写什么、长度预算、常见错误 |

---

## 三、三条 SOP

| SOP | 用途 | 参考指标 |
|---|---|---|
| [SOP-1 原图复刻](notes/SOP-1-原图复刻流程.md) | 照参考图生成同款，拿到干净基准 | vs 参考 126.04 |
| [SOP-2 原图调整](notes/SOP-2-原图调整流程.md) | 在 SOP-1 产物上只改一个部件（例：裤子化成冰衣） | 冰衣 19.17 |
| [SOP-3 更换姿势](notes/SOP-3-更换姿势流程.md) | 人物与服装不变，换一个身体姿势 | 614 行，跪姿 + standing split 两个案例 |

### SOP 专用执行文件

| 文件 | 作用 |
|---|---|
| [`tools/pick_parts.py`](tools/pick_parts.py) | 从 `parts_all.json` 选关键部件 → 切裁片 + 切掩码 |
| [`tools/depth_to_mask.py`](tools/depth_to_mask.py) | 深度图 → 人物剪影 mask + 背景刷黑的深度图（Otsu + 形态学 + 最大连通域 + 填洞） |
| [`tools/clean_depth.py`](tools/clean_depth.py) | 深度图背景刷纯黑（SOP 第 0 步） |
| [`tools/detail_colormap.py`](tools/detail_colormap.py) | `details[]` → 分区色图 + region prompt 文案 |

### 样本

四个自包含样本，每个都有 `00-*` 到 `05-*` 的分步产物 + 自己的 README：

```
examples/
├── SOP-1-20261112-四星2冰蓝舞娘/          36 文件 / 6.2 MB
├── SOP-2-20261112-四星2冰衣-24step/       38 文件 / 7.5 MB
├── SOP-3-20261112-四星2跪姿/               9 文件 / 4.1 MB
└── SOP-3-20261112-四星2-standing-split/   25 文件 / 7.1 MB
```

SOP-3 样本内部结构：

```
00-depth/        深度图刷黑（ex3_black.png 喂 --depth-map，ex3_mask.png 检查用）
01-transition/   过渡图（只传 --depth-map，control 0.6 / end 0.6）
02-colormap/     色图 + 第二深度图 + 8 张画布掩码 cvm_*.png
03-prompt/       主 prompt（五块结构）+ region prompt（三段式）
04-output/       各档产物（含失败版，便于对比）
README.md        逐档量化数据与踩坑记录
```

---

## 脚本参数速查

| 脚本 | 必填参数 | 常用可选 |
|---|---|---|
| `extract_colormap.py` | `--out` | `--palette`（默认 palette11.json）、`--stats` |
| `ground_regions.py` | `--image` `--outdir` | `--labels` `--max-edge` |
| `describe_crops.py` | `--indir` `--out` | `--only` `--max-edge` |
| `describe_parts.py` | `--grounding` `--image` `--out` | `--max-edge` |
| `describe_subzones.py` | `--ref` `--mask-dir` `--out` | `--segments` |
| `region_ask.py` | — | `--region x,y,w,h` / `--point x,y` / `--question` |
| `bbox_to_layout.py` | `--grounding` | `--tags` `--out` |
| `parts_to_layout.py` | `--parts` | `--min-area` `--max-area` `--prompt` `--layout` |
| `pick_parts.py` | `--parts` `--ref` | `--w` `--h` `--prefix` `--max` |
| `depth_to_mask.py` | `<输入>` `<输出前缀>` | `--width` `--height` `--feather` `--roi` `--keep-floor` |
| `clean_depth.py` | `--depth` | `--ref` `--out` |
| `detail_colormap.py` | `--parts` | `--picked` `--input-dir` `--out-colormap` `--out-prompts` |

全部支持 `--help`。

---

## 依赖（不在本仓库）

- MOSS-Image 模型、ComfyUI 部署、`moss_run.py` / `moss_main.py`
- 参考图、素材库、训练集、过程稿
- 三个 SOP 里引用的规则文档（`notes/规则-*.md`）与经验卡 —— 那是工作区的内部资产，需要时另行同步

---

## 三条已验证的关键结论

1. **掩码是画布坐标，不是参考图坐标** —— `--ref-query-mask-por` 的掩码描述「画布上哪块区域允许读第 i 张参考」，换姿势后新旧几何对不上（`drape` IoU 0.00%），必须从新色图反推 `cvm_*.png`。

2. **`--control-strength` 与 `--image-strength` 各管一件事** —— 前者是色图 + 深度图的总闸（`1.0` 会让参考裁片被当成装饰画进画面，拼贴 73.4%；`0.9` 是平衡点），后者管参考对画面的整体影响（`0.5` 把拼贴压到 4.3% 而纹样不退化）。

3. **24 步会把材质词放大** —— region prompt 里写 `sheer fabric`，8 步 fast 下量刚好，24 步会被材质先验放大成完全透明（裤腿从 (129,167,185) 蓝掉到 (175,181,182) 灰白）。提高 `--image-strength` 无效，必须把 trunk 改成显式不透明。

---

## 校验记录

入库前跑过一遍实测：

| 项 | 结果 |
|---|---|
| `git fsck --strict` | 无异常 |
| 133 个文件 blob 与索引比对 | 全部一致，0 异常 |
| Markdown 相对链接 | 有效 25 个，断开 0 |
| PNG 可读性 | 84 张全部可打开（48 张为 1216×1632 主画布） |
| 12 个脚本 `--help` | 全部 rc=0，无 Warning |
| 示例 JSON 交叉引用 | SOP-1/SOP-2 各 11 部件 / 7 picked，裁片与掩码缺失 0 |
