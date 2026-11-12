# Changelog

All notable changes to this project. Versions are tagged on `main`.

---

## v1.0.0 — 2026-11-12

First public release. Three modules, one repository.

### GrabTag — binding parts of a reference onto the canvas

`--image` cuts the reference into named crops, `--ref-labels` names them, `--ref-query-mask-por` constrains which patch of canvas each crop may govern.

- Up to 8 crops, one per reference slot; masks are **canvas coordinates**, applied at image-token level (`comfy/ldm/moss_image/model.py:409-415`) before the reference attends to anything.
- A crop is only read when the prompt names its label — no global "look like this image" bleed.
- **Reference-image OOM is fixed by default** since 2026-11-09: `MOSS_NO_REF_PRECOMPUTE=1` skips the precomputed-KV tensor in `comfy/model_base.py:2963-2965`. Measured on 1216×1632 with ~7752 reference tokens: the old build crashed twice, the new one finishes in **61 s** with the most detail preserved. `MOSS_REF_POOL=2` remains available as a memory/detail trade.
- Delivery pipeline: `tools/pick_parts.py` (crops + masks) and `tools/extract_colormap.py` (colour map from a transition image).

### region prompt — every region gets its own sentence

One colour map to delimit regions, plus one captioned sentence per region.

- Three-part format: `the <hex> area is <tag>, <position>; its shape is: <trunk>. Its colours, patterns and materials: <details>`.
- **Two injection points, one per purpose** — `--region-prompt-head` is prepended to the prompt (positional hints, so the skeleton is built first), `--region-prompt` is appended (a colour-to-material mapping, applied once the image exists). This split is a consequence of the injection point, not a stylistic choice.
- Resolution ceiling is **16 px per cell** (VAE stride); it can place things, not specify anything finer.
- Colour map rules measured, not assumed: shapes must hug the silhouette (rectangles produce multiple people, 41% → 81%), background must be mid-grey 128 (white destroys the pose), region count is capped by the number of non-overlapping parts (bleed measured `0.000%` at 3 / 5 / 8 / 9 regions — the real bottleneck is mask pixel overlap).
- Delivery pipeline: `ground_regions` → `describe_crops` / `describe_parts` / `describe_subzones` → `bbox_to_layout` / `parts_to_layout`.

### Three SOPs — repeatable flows

| SOP | What it does | Metric |
|---|---|---|
| SOP-1 reproduce | reproduce the same outfit from one reference | vs-reference 126.04 |
| SOP-2 adjust one part | change a single part, everything else untouched | ice outfit 19.17 |
| SOP-3 change the pose | keep character and outfit, replace the pose | two cases: kneeling + standing split |

- SOP-3 runs two parallel branches that only meet at step 3: the upper branch cuts 8 crops from the source reference ("what things look like"), the lower branch produces a transition image and derives a colour map plus a second depth map from it ("where things go"). All geometry comes from the depth map; the reference channel lends appearance only.
- Supporting tools: `pick_parts.py`, `depth_to_mask.py` (Otsu + morphology + largest component + hole filling), `clean_depth.py`, `detail_colormap.py`.
- Four self-contained samples under `examples/`, each with `00-*` … `05-*` step artefacts and its own README carrying per-arm numbers and the traps hit.

### Documentation

- **Bilingual README**: `README.md` (English) and `README.zh.md` (简体中文), each with a switch line at the top.
- Three pipeline diagrams under `docs/`: `pipeline-sop1.png`, `pipeline-sop2.png`, `pipeline-sop3.png`.
- 15 notes documents, covering GrabTag internals, the region prompt manual, three localisation mechanisms (GrabTag vs layout vs colour map), `ref_tag` writing rules, and the three SOP flows.

### Verified before release

| Item | Result |
|---|---|
| `git fsck --strict` | clean |
| Markdown relative links | 0 broken in both languages |
| Images | 18 per language, 0 missing |
| Mermaid diagrams | 3 per language, all parse |
| CRLF | 0 (`.gitattributes` pins `text eol=lf`) |
| Scripts `--help` | all rc=0 |

### Known limits

- High-frequency fabric motifs are never transferred by the region channel; they need crops plus captions. Both the colour map and layout bbox only say "this patch is yours".
- Gold vertical stripes at 6 per leg, diamonds at 4 per leg and floral ornaments at 3 per leg are **not** reached in the reference reproduction; shoes remain dark grey round-toed (documented boundary, not a regression).
- Writing `sheer fabric` in a region prompt is fine at 8 steps but gets amplified into full transparency at 24 steps; the trunk must be rewritten as explicitly opaque.
- `tools/pick_parts.py:209-217`'s `--shape-source` is silently ignored when `nonwhite` is used.
- The GitHub About panel and Topics are not set programmatically; the copy lives at the end of both READMEs.
