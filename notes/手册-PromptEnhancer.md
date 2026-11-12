# 手册 · PromptEnhancer（提示词编译规范）

> **来源**：`moss-image-prompt-skill`（本机技能，约 47 KB）。这份手册是它的**可查阅摘要 + 与本地代码的对应**，两者冲突时以技能原文为准。
> **原文位置**：`C:\Users\black\.dsh\skills\moss-image-prompt-skill\`
>
> **它解决什么**：把「Danbooru tag / 参考图 / 模糊需求」编译成一对能直接喂 MOSS-Image 的正负提示词，并附采样参数。

---

## 一、默认参数（先抄这个，再谈别的）

| 项 | 默认 | 备注 |
|---|---|---|
| 分辨率 | **面积 0.6 MP**，比例自拟 | 我们常用 1216×1632 ≈ 1.98 MP，属偏高但已验证 |
| Steps | **16** | 我们草稿档用 8（`--fast` 的 DMD 蒸馏），已产线化 |
| CFG | **3.0** | 我们草稿档用 1.0（配 fast 必须） |
| SLG | `single_layers` **22**，`scale 3.0`，`mode simple` | **画面无文字时可跳过**；MOSS 里 `--slg-single` 默认空 = 不启用，**实测开启会多出漂浮物，见 §9** |

**要文字精细**：1.6 MP + 50 步 + **必开 SLG**。

---

## 二、证据四级（判断一条写法的可信度）

| 级 | 含义 | 怎么用 |
|---|---|---|
| **A** | 受控对照证实（有 A/B 对照且人工复核） | 可直接当规则 |
| **B** | 单次观察复现（一个场景有效，未做对照） | 可试，别当铁律 |
| **C** | 机理假说（未独立拆解验证） | **不得当规则执行**，仅供推理 |
| **D** | 禁用（实测无效） | 清单见 §10 |

---

## 三、五步流程（不得跳步）

1. **词条清洗**（§5）
2. **确定媒介与场景光影**（§6）
3. **设计构图**（分块还是单段短文，§4）
4. **确定年龄身材 + 表情肢体**（§7）
5. **按模板生成 + 逐条自查**（§8）

---

## 四、闭合标签分块 `<|概念|>…<|/概念|>`

### 为什么

Qwen3.5 的预训练语料里 `<|...|>` 就是聊天模板的定界符，它认识这个结构。**实测进 DiT 前的净有效信噪比**：

| 格式 | 相对信噪比 |
|---|---|
| 逗号一路连写 | 1× |
| `Style: …\nScene: …` 换行 | 3.2× |
| **`<|概念|>…<|/概念|>`** | **12.7×** |

> 证据等级 A

### 五条编写规则

| 规则 | 说明 |
|---|---|
| **按人物或空间层次分块，不按零散属性分块** | 一人一块，写全该角色的方位/发色/瞳色/服装/配饰/灯光 |
| **块内仍要写方位词** | 标签只负责隔离，不能替代 `On the left…` 这类介词 |
| **按从左到右定调顺序排** | 第 1 块全局画风与光影 → 第 2 块主要人物 → 第 3 块次要人物（开头 `In sharp contrast, NO…`）→ 第 4 块文字/UI |
| **一行一块、成对闭合、不嵌套、总数 3–5 块** | 块内不再套子块 |
| **不同画风不要分块** | 写成两个块会在画面正中切出**上下漫画分镜线** |

### 什么时候**不用**分块（写一段 85 词以内的连贯短文）

- 全身双人紧密交叠（`hug` / `carrying` / `grappling`）
- 单人胸上特写怼脸
- 需要 2D 人物与 3D 实景融在同一物理空间且不切分镜线

> 分块会导致上下半身断裂或被切出漫画分格线。

---

## 五、词条清洗（如果输入是 Danbooru tag）

| 动作 | 例子 |
|---|---|
| **保留**角色名 | `lillie (pokemon)`、`higuchi madoka` —— 有助于还原原作发型神态，不会拉回二次元 |
| **删除**画师名 | `ie (raarami)`、`bartolomeobari`、`mika pikazo`、`kantoku` 等——训练语料重打标时已抹掉，写了等于浪费 token |
| **删除**版权大词 | `pokemon`、`nintendo`、`naruto`、`genshin impact`——会引出漫展假发感 |
| **删除**打码与渲染词 | `censored, mosaic censoring, 3d, animated, game asset, visual novel cg, motion lines, request inset, english text, watermark` |
| **改写**二次元符号 | `anger vein` → `furrowed brows, glaring with defiant eyes`；`heart-shaped pupils` → `glossy, watery dazed eyes`；`nose blush` → `faint pink blush on cheeks`；`genderswap` → `delicate feminine features` |
| **替换**纯色背景 | `white background` → 具体场景 + 光照（`dimly lit bedroom, warm wooden bar counter`） |

### booru tag 部分的两条保留规则

1. **不删核心动作与人数 tag**：画面里有男方躯干或手时，不能写 `solo`，要保留 `1girl, 1boy, hetero`
2. **核心局部状态词原样留在 tag 部分**：`school uniform, white shirt, blue skirt, rolled-up sleeves, wet hair`

---

## 六、媒介与光影（写在提示词第 1 句）

### 三条铁律

| 铁律 | 说明 |
|---|---|
| **相机型号必须和整句一起写** | 只写 `Contax T2`、`Hasselblad` 单独一个词**没有任何可辨认差异**（已列禁用） |
| **光影词写在人物与衣物之前** | 单向因果，写在后面只画出灯管而不染色 |
| **暗室/逆光要直接写出正面暗部** | 只写「夜间黑房间」仍会把脸补成惨白 |

### 12 种三次元风格的开头词组（选一个放最前）

| # | 风格 | 开头词组要点 |
|---|---|---|
| 1 | 90s 一次性胶片硬直闪 | `raw 1990s disposable 35mm film snapshot, harsh direct on-camera flash, hard black drop shadow, dark corner vignette` |
| 2 | 暗室单束光伦勃朗 | `dramatic low-key chiaroscuro, lit only by a single narrow warm beam from the side, zero front fill light` |
| 3 | 90s 港片霓虹 | `1990s Hong Kong arthouse cinema film still, lush emerald-green and warm amber tungsten neon, slow-shutter motion blur` |
| 4 | 银盐黑白高反差 | `monochrome silver gelatin print, high-contrast grayscale, coarse Ilford HP5 grain`（**要删正文所有颜色词**） |
| 5 | 落日逆光金边 | `warm golden hour backlit portrait, glowing golden rim light on stray hair, natural lens flare` |
| 6 | 漂白冷峻银灰 | `gritty desaturated bleach-bypass cinema still, cold metallic silver-teal grading` |
| 7 | 赛博青/品红双色片 | `split two-tone colored gel lighting, electric cyan-blue left side, hot magenta-pink right side` |
| 8 | 1880s 湿版蛋白印相 | `antique 1880s sepia wet-plate albumen print, heavy vintage chemical edge staining, Petzval brass lens swirl` |
| 9 | 1994 家用 VHS | `1994 lo-fi home VHS camcorder still, horizontal CRT scanlines, RGB chromatic bleeding` |
| 10 | 红外夜视 CCTV | `green monochrome night-vision infrared security footage, glowing white infrared eyes, timestamp` |
| 11 | 日系空气感过曝胶片 | `airy Japanese overexposed pastel film, high-key diffused daylight, low-contrast milky lifted shadows` |
| 12 | 好莱坞青橙宽银幕 | `cinematic 35mm anamorphic widescreen, teal-and-orange grading, oval vertical bokeh orbs, horizontal blue flare` |

### 避免 AI 摆拍证件照感的 5 项

1. **特殊机位与遮挡物**（行车记录仪视角写明仪表盘与雨刮器）
2. **一侧加虚化前景**（越肩后脑勺、虚化侧脸、门框）
3. **写明灯具形态与面部受光位置**（`two harsh glowing emerald-green tubes diagonal across the upper-left ceiling, catching his nose tip`）
4. **写明年代色调与胶片颗粒**
5. **加打破精致感的日常小道具**（嘴角牙签、凌乱碎发、旧皮马甲）

---

## 七、年龄、骨相与身材

### 15–16 岁少女的三条写法

| 要点 | 写法 |
|---|---|
| **双向排除**（Qwen3.5 能理解自然语言约束） | `neither a big-headed 10-year-old child nor a mature 20-year-old woman` |
| **少女骨相** | `softly tapered chin` + `slender graceful neck`（幼童是圆脸短脖） |
| **避开正脸瞪眼** | `three-quarter angle tilted slightly back` + `half-lidded, languid eyes with wistful teenage aloofness` |

### 三条禁忌

| 禁忌 | 原因 |
|---|---|
| 不写 `flat chest` | 应写 `small perky A-cup breasts`；`flat chest` 放**负面**里防失去立体光影 |
| 不叠加显老词 | `woman, gorgeous, makeup, wide hips, curvy, C-cup` 会画成 25 岁 |
| 不叠加显幼词 | `very young, babyface, round chubby cheeks, button nose` 会画成 6–10 岁 |

### 图内印字会把年龄体型带偏

- 印 `"LOLITA"` / `"148cm"` → 画成幼童
- 印 `"AGE : 19"` → 连带把身材画胖；要在正文写 `very slender, petite skinny teenage frame` 并在负面加 `fat, chubby, curvy, thick thighs`

### 全身镜头必须写脚与地面的关系

删掉脚部与支点描写会让**头身比缩水成五头身儿童**。悬空要写 `legs hang freely in mid-air well above the floor`，负面加 `feet on floor, standing, touching the ground`。

---

## 八、多主体（2–6 人）

| 做法 | 说明 |
|---|---|
| **按位置分区** | 2 人 → 左/右；4 人 → 四象限；6 人 → 沙发前排 + 后排五人 |
| **每人写全差异** | 左侧 `European girl with visible freckles`，右侧 `Japanese girl with spotless porcelain skin and zero freckles` |
| **第 2 段开头切断前文** | `In sharp contrast, the girl on the right has NO glasses…` |
| **负面加防双胞胎** | `twins, identical faces, same hair color, attribute bleeding, clone` |
| **开头可加群像句** | `Featuring exactly [N] distinct girls, each appearing once, in an asymmetric ensemble composition (not a rigid grid).` |
| **分块后仍要写全发色发型** | 从 tag 部分移进人物块时别漏写 |

---

## 九、与 MOSS 本地代码的对应

| 技能说的 | MOSS 里的参数 | 收口 |
|---|---|---|
| SLG `single_layers` 22 | `--slg-single 22 --slg-mode simple --slg-scale 3.0` | `C:\MOSS-Deploy\moss_run.py:243` 注释原文 `official recommendation, layer 22 (0-index)` |
| SLG 默认不启用 | `--slg-single` 默认 `""`，`:244` 条件 `slg_mode != "off" and (slg_single or slg_double)` | 我们**此前所有实验都没开 SLG** |
| 16 步 / CFG 3.0 | `--steps 16 --cfg 3.0`（默认 `--steps 50 --cfg 3.0`） | `:1033-1034` |
| 0.6 MP | `--w 1216 --h 1632` ≈ 1.98 MP | 偏高但已验证 |

### ⚠️ SLG 在本项目的实测结论：**不要开**

| 臂 | vs参考 | 非白% | 锐度 | 左边缘非白 | 右边缘非白 |
|---|---|---|---|---|---|
| v9001 无 SLG | 127.58 | 35.4 | 5.03 | **0%** | **0%** |
| slg22 | **136.94** | 39.5 | 9.75 | **31.0%** | **31.6%** |

**画面左右各凭空多出一条巨大漂浮宝石垂链**，`vs参考` 退 9.36。技能也说 SLG 主要改善**文字清晰度**——我们画面无文字，不该开。

---

## 十、禁用清单（实测无效，别再当手段）

| 禁用 | 原因 |
|---|---|
| 只写相机型号名（`Contax T2`） | 无可辨认差异，真正起作用的是同句的硬直闪/全景深/颗粒 |
| 只写 `wet plate collodion` | 无效，要写药水边缘腐蚀黄斑与折痕 |
| 只写 `CCTV` | 无效，要写荧光绿红外 + 反光白瞳 + 俯拍时间戳 |
| 只写 `3D render / CGI / Unreal Engine` | 退化为廉价磨皮塑料人偶或 2.5D 厚涂 |
| 写画师名 / `XXX style` | 训练语料重打标时已抹掉 |
| 写 `censored` 一类打码词 | 会退回二维或三维渲染 |
| `flat chest` 写在正面 | 应放负面 |
| 单人胸上特写时分块 | 会导致上下半身断裂 |

---

## 十一、专项：三类画面

### 11.1 日系写真集内页

- 开头用 `high-resolution Japanese gravure photobook page layout, full-bleed vertical bedroom photograph framed by a clean thin white magazine border, soft diffused natural bedroom window light`（**不要**用哈苏那套，二选一）
- 发型写 `loose twin braids, airy wispy bangs, delicate flyaway strands`（不要写 `neat`）
- 眼神写 `shy seductive gaze` 或 `watery, flustered gaze full of reluctant submission`（不要写 `looking gently`）
- 白色元素多时**不要**写 `bright background` / `daylight`，会过曝发白；负面加 `overexposed, washed out, whiteout`

### 11.2 游戏实机截图

四步结构：
1. 开头 `screenshot, video_game_capture, [genre], [game_name].`
2. 写明实机机位（`third-person over-the-shoulder gameplay camera`），排除宣传图
3. **四角 HUD 部件与引号内数值都要写**（左上血条、顶部罗盘 `"W" "NW" "N"`、右下计数器 `"1248"`）
4. 结尾 `No title logo, desktop borders, subtitles, or promotional text`

**不支持**：只靠提示词生成 UE5 / FF7 重制级的写实 3D 渲染人物。

### 11.3 多分镜漫画（Layout JSON）

- 主立绘用 `"label": "character"`，**局部特写必须用 `"object"`**（否则每个特写框里多画一颗头）
- 双人拆两个独立 bbox，X 坐标之间留 30–140 px
- 小分镜用 `waist-up / thigh-up medium shot`，不要 `full-body`（会画成四头身小人）
- 旁白用直角矩形框、对话用圆角椭圆带尾、咆哮用锯齿框（**超过 15 字不要用锯齿框，会吞字**）
- **竖排气泡里的数字改汉字**（`"720日元"` → `"七百二十日元"`），姓名不留半角空格
- 修气泡时只改出错项，token 长度差控制在 ±15 内，否则固定 seed 下人物会走样

---

## 十二、五个实践要点

1. **先在纸上定光影，再写人**（单向注意力）
2. **第 1 块定调**，最需要定调的内容放最前
3. **块内仍要写方位词**，标签不是万能的
4. **负面提示词固定就不要动**（固定 seed 下改负面开头会让整图漂移）
5. **改 prompt 时变量分开**，一次只改一处

---

## 出处

- 技能原文：`C:\Users\black\.dsh\skills\moss-image-prompt-skill\`
- 与 MOSS 的 SLG 实测：`notes\2026-11-11-经验-SLG22会多出漂浮物.md`（若尚未建立，见本手册 §9 表格）
- 分块格式在本项目的实测：`notes\SOP-三步出图.md` §提示词格式
