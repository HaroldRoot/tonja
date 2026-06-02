# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

通假字生成工具 (Word Obfuscation). Despite the name "通假字" (phonetic loan characters), this is **not** a real loan-character dictionary. The actual goal (see [IDEA.md](IDEA.md)) is to obfuscate Chinese text by swapping a character's radical/component for a different one, producing a character that **looks** similar but is technically wrong. Example: 操你妈逼 → 懆称冯福 (操/懆 share 喿, 你/称 share 尔, etc.).

Two motivating use cases: a "cognitive corruption" horror aesthetic where text feels familiar but every glyph is subtly off, and bypassing AI content filters while staying human-readable through visual association. The premise is that humans recognize the shared component instantly but token-based LLMs generally cannot.

## Architecture

The project splits into an **offline Python data pipeline** that produces a mapping file, and a **static browser frontend** that applies the mapping.

### Data pipeline (Python)

Decomposes CJK characters using **IDS** (Ideographic Description Sequence) — formula-like strings describing glyph structure using IDC structural operators (⿰⿱⿲… in `U+2FF0–U+2FFF`). Source data is [IDS-UCS-Basic.txt](IDS-UCS-Basic.txt) (CJK Unified Ideographs U+4E00–U+9FA5), tab-separated lines of `<codepoint>\t<char>\t<IDS>[\t@apparent=<IDS>]`.

- [utils.py](utils.py) — IDS primitives. `IDC_REGEX` and the flat component extractors (`get_ids_components_list`, etc.) strip structural operators and split parts. The **top-level structure parser** (`tokenize_ids` → `parse_ids_tree` → `top_level_components`, plus `side_bucket`) is what the mapping algorithm relies on: it keeps the operator and which *visual side* each child sits on (`lead`/`mid`/`trail`), rather than flattening everything.
- [build.py](build.py) — staged pipeline. Run `python build.py` for the full run, or `python build.py --stage {basic,mapping}` for one stage.
  - **Stage `basic`** parses the IDS file → `all_basic_hanzi.json` (per-char decomposition records).
  - **Stage `mapping`** runs the core algorithm → `mapping.json`.

### The mapping algorithm (build.py, stage `mapping`)

Each compound character = **radical** (high-frequency, swappable component) + **body** (low-frequency, recognizable component). The algorithm:

1. Parse each char's top-level structure, preferring the `@apparent` (visual) IDS over the functional one.
2. Count how many distinct characters each component signature appears in (`comp_freq`).
3. For each char, pick its **body** = the least-frequent, non-trivial component (frequency ≥ 2 so a swap is possible). The group key is `(body_signature, visual_side)`.
4. Characters sharing a key become each other's loan-char candidates — same body in the same position, only the radical differs.

The `visual_side` in the key is what lets 逼 `⿺辶畐` and 福 `⿰示畐` match (畐 is `trail` in both, across different operators) while excluding 劋 `⿰喿刂` from 操's group (喿 is `lead` there, `trail` in 操). Tunables at the top of build.py: `MAX_CANDIDATES`, `MIN_BODY_LEN`, `TRIVIAL_BODIES`. Output is written compact (`save_json(..., compact=True)`).

### Frontend (static, no build step)

- [index.html](index.html) — single page, all CSS inlined. UI strings are Chinese.
- [app.js](app.js) — fetches `mapping.json` (a `{ char: [candidates] }` object), then on convert walks the input by code point and replaces each char that has candidates with a **random** pick. Re-clicking "开始转换" yields different output. Chars with no candidates pass through unchanged.

Serve over HTTP (not `file://`) so `fetch('mapping.json')` works, e.g. `python -m http.server`.

## Key files

- `mapping.json` — the lookup the frontend consumes, `{ char: [candidate, ...] }`. Committed (the frontend needs it); regenerate with `python build.py`.
- `all_basic_hanzi.json` — large (~4.8MB) intermediate from stage `basic`; gitignored and regenerable.
- `IDEA.md` — full design rationale; **gitignored on purpose** (the author keeps the idea draft private). Read it before changing pipeline logic, but never commit it or surface its contents publicly.

## Conventions

- All source data and generated JSON is UTF-8; always open files with `encoding="utf-8"`.
- Code comments and CLI/UI text are in Chinese — match this when editing.
- `save_json` defaults to `indent=4, sort_keys=True`; pass `compact=True` for minified output.
