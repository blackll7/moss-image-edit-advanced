# GrabTag · `ref_tag` 写法：可见细节优先（2026-11-10 实测）

> 触发：用户 m01045「现在先把 grabtag 的效果做好」。
> 本文件是**标签写法标准**；A 链封装见 `2026-11-09-GrabTag-A链-moss_main-通道与转发.md`。
> `10-GrabTag-机制说明-给AI读.md` 已于 2026-11-10 按用户要求删除（判定为老文件），备份在 `notes/_archive/`，**不再作为依据**。

## 1 结论

`ref_tag` 写**品类词**（`trousers, harem pants`）时，出图会退回底模默认款——参考图里的紫色菱形拼片、星纹、金属香球、金线裤缝全部消失。
把它改写成**可见特征**（颜色 / 材质 / 纹样 / 结构 / 数量）后，同一张卡、同一深度、同 seed，这些特征回来，且**两个 seed 都成立**（9001、4242）。

这是 A 链里唯一不需要改任何参数、也不改提示词模板就能提质的杠杆：模板仍是「一句话枚举 11 件」，只是 `tags.json` 里那 11 句变具体了。

## 2 实测对照

条件：`moss_main.py --card v2sop_ref.png --pose v2sop_depth.png --tags <tags.json> --seed 9001`（achain 档：ai-toolkit / 8 步 / cfg1.0 / 1216×1632 / 参考原尺寸）。

| 特征（参考卡里都有） | `tags.json`（品类词） | `tags2.json`（可见细节） |
|---|---|---|
| 袖子/裤脚的紫色菱形拼片 | 无（纯蓝渐变） | **出现**（袖、裤脚都有） |
| 深蓝披帛上的星纹/花枝刺绣 | 无 | 出现（星形与花枝） |
| 腰侧金属香球 + 米色流苏 | 蓝色圆球 | 银灰镂空球 + 流苏 |
| 裤面金色竖缝线 | 无 | 出现 |
| 胸衣银色花丝 + 宝石 | 简化成普通挂脖 | 花丝与宝石更接近 |
| 画风、脸、金发编发 | — | 两版都维持 |

产物：`out\2026-11-10_GrabTag标签质量_品类词vs可见细节_并排.png`（卡 / v1 / v2 三格）、`out\2026-11-10_GrabTag_tagsv2_可见细节.png`；数据 `out\2026-11-10_GrabTag_tagsv2.json`（源文件 `C:\MOSS-Deploy\work\reg_ice3\tags2.json`）。

## 3 写法规则（六条）

1. **每条 = 颜色/材质 + 品类 + 纹样或结构 + 位置/数量**，5–12 个英文词。例：
   `pale ice-blue sheer harem pants, gold vertical seam lines, violet diamond panels at the cuffs, white four-point star motifs`
2. **禁止单独品类词**：`trousers`、`shoes`、`hair`、`bodice` 一律不算 tag——那是底模已经会画的东西，写进去等于没写。
3. **只写看得到的**：`violet diamond panels`、`silver filigree`、`gold chain fringe` 可以；`silk`、`velvet`、`satin` 这类看不见的材质不要猜（除非 crop 上确实有光泽/织纹特征）。
4. **左右对称件分别写、但用同一句描述**（`sleeve_r` / `sleeve_l` 都写 `translucent pale-blue puff sleeve with violet diamond lattice and gold trim, gold armband cuff`）。
5. **`ref_tag` 不写落点**：位置写「在哪件上」可以（`at the cuffs`、`hanging at the hip`），不要写成「在画面左下」这种生成侧语言——那是 `paint_prompt` 的活。
6. **每条都必须对得上一张 crop**：写不出细节 = crop 没截到重点，回去重截（`plan --for ref` 的 montage 逐格看）。

## 4 流程位置

```
参考卡
 └─ plan --for ref          → crops/r*.png + montage.png
      └─ 逐格看图写 ref_tag  → tags.json（11 条左右）
           └─ moss_main.py --card … --pose … --tags tags.json
                └─ 一句话枚举进提示词 → moss_run.py
```

- 条数不用刻意增减（11 条够用，实测与顺序无关）。
- `ref_tag` 是**参考侧**字段：它只说「这块是什么」；`paint_prompt` 才是带落点的生成侧描述，不参与 A 链拼句。
- 写完后建议先跑 `--dry-run` 看一眼拼出来的 prompt 是否是「颜色+材质+纹样」的句子，而不是一串品类名词。

## 5 未做

- 没有改 `moss_main.build_prompt` 模板（用户 11-10 决策「提示词可以不动」）。
- 没有把「必须含颜色/材质」做成 lint 硬校验（`moss_region_caption` 的 `[lint]` 只作用于 `paint_prompt`）；要不要加一条 `ref_tag` 自查，等这一类写法再积累两轮再说。
