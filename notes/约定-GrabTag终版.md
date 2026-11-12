# GrabTag 终版约定（2026-11-11）

> **一条规则，无例外。** 三条通道各管一件事，谁都不越界。

---

## 零、一句话

**参考图负责「这是什么」，色图负责「在哪」，文本分前后：前部只指位置，后部只写细节。**

---

## 一、三条通道的分工

| 通道 | 参数 | 管什么 | 不管什么 |
|---|---|---|---|
| **参考（GrabTag）** | `--image` + `--ref-labels` + `--ref-query-mask-por` | **每个部位长什么样** | 不管位置、不管细节密度 |
| **深度图** | `--depth-map` | **画面里有几个人、姿态** | 不管长相、不管装饰 |
| **色图 + 文本** | `--color-map` + `--region-prompt` | **细节纹样画在哪一块** | 不管形状轮廓、不管整体布局 |

**判据**：想知道某条信息该放哪，问「它属于'是什么'还是'在哪'」。**是什么 → 参考；在哪 → 色图。**

---

## 二、三步操作

### 第 1 步：切裁片 + 掩码

按**人体部位**切参考图，一块一部位。8 块上限。

- 裁片：最长边 512 px（合计约 3147 tok）
- 掩码：**必须在 `ComfyUI\input\` 根目录**，用统一前缀防撞旧文件
- 命名：`gt2_<部位>.png` / `gtm2_<部位>.png`

### 第 2 步：写前部提示词

**每个部位一句，格式固定：**

```
Her <部位> is <tag>.
```

八句实例：

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

**三条硬性要求：**

1. **必须有 `<tag>` 引用**——空挂参考等于没挂（实测 131.01，比不挂还差）
2. **必须反向**——主语是画布部位、宾语是裁片。正向写「`<tag>` 是什么」会画出漂浮物（实测差 5.85）
3. **不要写形貌**——不写材质、不写轮廓、不写"到哪结束"。**形貌由裁片自己说**（见第四节）

**末尾两句不要省**，省了会出现漂浮的辫子和装饰片。

### 第 3 步：加色图细节

```powershell
--color-map cm_mask3.png `
--region-prompt $legs --region-prompt $sash --region-prompt $bodice
```

- 色块数 ≤ 3，**形状必须贴合衣物轮廓**（矩形会画出多主体）
- 每块配一条 `--region-prompt`，格式：`the <hex色号> area carries <细节描述>`
- 细节描述写**数量、排列、材质**，不写形状轮廓

---

## 三、参数（照抄，不要改）

```powershell
--control-strength 1.0      # 总强度，必须满
--depth-strength   1.0      # 硬约束，降了就画出多个人
--color-strength   0.4      # 唯一可调的旋钮（0.3–0.5）
--control-end      1.0      # 实测无影响，保持 1.0
--ref-no-pos       1
--fast --cfg 1.0 --steps 8
```

**三个开关的作用，记住就不会错：**

| 参数 | 降低会怎样 | 能不能降 |
|---|---|---|
| `depth-strength` | **直接画出多个人 + 色图矩形显形**（非白 41%→73.7%） | **不能** |
| `color-strength` | 画风变软、越来越像没给色图 | 能，0.3–0.5 |
| `control-end` | 实测无任何变化（131.45 vs 131.49） | 无所谓 |

---

## 四、为什么前部不写形貌

**实测对比**（其余参数全同）：

| 前部写法 | 胸衣区 | 腿区 | 整图 vs参考 |
|---|---|---|---|
| **只写 tag** | **107.0** | 113.2 | 126.71 |
| tag + 形貌 | 112.9 | **109.9** | 126.70 |
| tag + 形貌 + 边界词 | 113.6 | 110.0 | 126.58 |

**形貌描述给腿赚 3.2、给胸衣赔 6.6，净收益为负。**

原因：裁片已经携带了完整形貌信息，文本再描述一遍，等于让模型在两个来源之间做取舍；而**反写出来的形貌描述是降维概括**（把「露腰挂脖短上衣 + 宝石阵列 + 珍珠链」压成 `fitted bust silhouette`），概括一旦进 prompt，就把细节压平了。

**补边界词救不回来**（112.9→113.6，噪声级）——问题不在「没说到哪结束」，在「概括本身丢失了结构」。

---

## 五、三条禁止

1. **不写形貌**（材质、轮廓、边界都不要）——见第四节
2. **色块不超过 3 个，且必须贴合衣物**——矩形会画出多个人
3. **不把 `depth-strength` 往下调**——这是出现多主体的直接原因

---

## 六、为什么这样分工（机制）

```
参考裁片 → vision token → Qwen3.5 文本编码器 ─┐
                                              ├→ 拼成一条序列 → DiT
前部提示词（只指位置）→ 文本 token ────────────┘

深度图  ┐
        ├→ concat(256) → video_embedder(384) → 加进同一条序列
色图    ┘   （各自乘自己的 strength）
```

- **参考走的是「视觉 token 前挂着名字」**：`<hair>: <|vision_start|>…`，模型看到的是「这个名字对应这团视觉特征」
- **深度图锁的是「人体轮廓有多硬」**：降到 0.5，就没有东西把多个色块收束成一个人
- **色图给的是「这块区域归谁」**：它只有 16 px 一格的分辨率（VAE stride-16），所以能管位置，管不了纹样细节

---

## 七、跑之前对着这张表检查

| 检查项 | 合格线 |
|---|---|
| 裁片数量 = `--ref-labels` 数量 = 掩码数量 | 三者一致 |
| 前部提示词的 `<tag>` 拼写 | 与 `--ref-labels` 逐字一致 |
| 每句是否只写「部位 + tag」 | 有材质/轮廓词就删 |
| 末尾两句防漂浮声明 | 在 |
| 色块数量 | ≤ 3，且贴合衣物轮廓 |
| 每条色块是否有对应的 `--region-prompt` | 一一对应 |
| `depth-strength` | 1.0 |
| 常驻负向四项 | `worst quality, bad anatomy, watermark, jpeg artifact` |

---

## 八、出处

- 裁片与掩码：`notes\机制-GrabTag-当前实现.md`
- 三个定位系统的分工：`notes\机制-三个定位系统-GrabTag-layout-色图.md`
- 强度拆分的内核改动：`notes\2026-11-11-经验-色图与深度图共享strength导致多主体.md`
- 前部形貌的对照实验：`f1` / `f3` / `f4`（`C:\MOSS-Deploy\ComfyUI\output-moss\`）
- 反向指派与 tag 的实现：`C:\MOSS-Deploy\ComfyUI\comfy_extras\nodes_moss_image.py:151-160`、`C:\MOSS-Deploy\moss_run.py:441-445`
