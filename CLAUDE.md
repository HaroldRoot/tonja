# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

通假字生成工具 (Word Obfuscation). Despite the name "通假字" (phonetic loan characters), this is **not** a real loan-character dictionary. The goal is to obfuscate Chinese text by swapping a character's radical/component for a different one, producing a character that **looks** similar but is technically wrong. Example: 操你妈逼 → 懆称冯福 (操/懆 share 喿, 你/称 share 尔, etc.).

The premise is that humans recognize the shared component instantly through visual association, producing a "cognitive corruption" aesthetic where text feels familiar but every glyph is subtly off.

## Running

Use `F:\anaconda3\python.exe` as the interpreter (the default `python` on this machine is a broken env). From bash:

```bash
PYTHONPATH= /f/anaconda3/python.exe build.py
```

Dependencies: `pypinyin` (used by the fallback). Standard library otherwise.

## Architecture

The project splits into an **offline Python data pipeline** that produces a mapping file, and a **static browser frontend** that applies the mapping.

### Data pipeline (Python)

Decomposes CJK characters using **IDS** (Ideographic Description Sequence) — formula-like strings describing glyph structure using IDC structural operators (⿰⿱⿲… in `U+2FF0–U+2FFF`). Source data is [IDS-UCS-Basic.txt](IDS-UCS-Basic.txt) (CJK Unified Ideographs U+4E00–U+9FA5), tab-separated lines of `<codepoint>\t<char>\t<IDS>[\t@apparent=<IDS>]`.

- [utils.py](utils.py) — **reusable** IDS / IO toolkit, project-agnostic (meant to be copied into future projects). Holds: JSON read/write (`load_json`, `save_json`), CHISE IDS-file parsing (`parse_ids_file`, `choose_ids`), the flat component extractor (`get_ids_components_list` + `IDC_REGEX`), and the **top-level structure parser** (`tokenize_ids` → `parse_ids_tree` → `top_level_components`, plus `side_bucket`) that keeps the operator and which *visual side* each child sits on (`lead`/`mid`/`trail`) instead of flattening.
- [build.py](build.py) — **project-specific** pipeline. Imports from utils. Run `PYTHONPATH= /f/anaconda3/python.exe build.py` for the full run, or `--stage {basic,mapping}` for one stage.
  - **Stage `basic`** parses the IDS file → `all_basic_hanzi.json` (per-char decomposition records).
  - **Stage `mapping`** runs the core algorithm → `mapping.json`.

### The mapping algorithm (build.py, stage `mapping`)

Each compound character = **radical** (high-frequency, swappable component) + **body** (low-frequency, recognizable component). The algorithm computes per-char top-level structure (preferring the `@apparent` IDS), counts how many distinct chars each component appears in (`comp_freq`), and picks each char's **body** = its least-frequent non-trivial top-level component (freq ≥ 2). Candidates come from three mechanisms, in priority order:

1. **(A) Containment** — src is wholly the body of dst, i.e. dst = src + an added radical. E.g. 我 → 俄 `⿰亻我`/哦 `⿰口我`; 早 → 章/草/卓. No structure constraint (src is fully preserved, so always recognizable).
2. **(B) Shared body** — src and dst share a sub-body in the **same visual side**, with a **compatible operator**. E.g. 操 `⿰扌喿` → 懆 `⿰忄喿`. Same operator required, with the single exception `⿺→⿰` (for 逼 `⿺辶畐` → 福 `⿰示畐`); the reverse `⿰→⿺` and all other cross-structure are forbidden. **Only consulted when (A) yields nothing** — if a char is containable it's already holistically recognizable, so shared-body swaps would only hurt recognition.
3. **(C) Strip-radical fallback** — when (A) and (B) both yield nothing, if the char's body is itself a real single char with the **identical pinyin**, map to it (erase the radical). E.g. 莱 `⿱艹来` → 来 (both *lái*); 痹 `⿸疒畀` → 畀 (both *bì*).

Tunables at the top of build.py: `MAX_CANDIDATES`, `MIN_BODY_LEN`, `TRIVIAL_BODIES`, `ALLOWED_CROSS`. Output is written compact (`save_json(..., compact=True)`).

### Frontend (static, no build step)

- [index.html](index.html) — single page, all CSS inlined. UI strings are Chinese.
- [app.js](app.js) — fetches `mapping.json` (a `{ char: [candidates] }` object), then on convert walks the input by code point and replaces each char that has candidates with a **random** pick. Re-clicking "开始转换" yields different output. Chars with no candidates pass through unchanged. Also drives the rotating **typewriter title** (`initTitleTypewriter`), which cycles between two taglines and respects `prefers-reduced-motion`.

Serve over HTTP (not `file://`) so `fetch('mapping.json')` works, e.g. `python -m http.server`.

## Key files

- `mapping.json` — the lookup the frontend consumes, `{ char: [candidate, ...] }`. Committed (the frontend needs it); regenerate with `PYTHONPATH= /f/anaconda3/python.exe build.py`.
- `all_basic_hanzi.json` — large (~4.8MB) intermediate from stage `basic`; gitignored and regenerable.

## Conventions

- All source data and generated JSON is UTF-8; always open files with `encoding="utf-8"`.
- Code comments and CLI/UI text are in Chinese — match this when editing.
- `save_json` defaults to `indent=4, sort_keys=True`; pass `compact=True` for minified output.
