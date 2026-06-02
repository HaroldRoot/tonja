"""通假字数据管线（本项目特定）。

把 CJK 基本汉字按 IDS 拆解，为每个字生成「偏旁不同、主体相同」的形近候选，
产出前端使用的 mapping.json。通用的 IDS 解析 / 文件 I/O 在 utils.py。
"""

import argparse
import collections
import os
import sys
import time

from pypinyin import Style, lazy_pinyin

from utils import (
    choose_ids,
    get_ids_components_list,
    load_json,
    parse_ids_file,
    save_json,
    side_bucket,
    top_level_components,
)

# ──────────────────────────────────────────────
# 文件路径常量
# ──────────────────────────────────────────────
IDS_SOURCE_FILE = "IDS-UCS-Basic.txt"
ALL_BASIC_HANZI_FILE = "all_basic_hanzi.json"
MAPPING_FILE = "mapping.json"
REPORT_FILE = "report.md"

# 一个部件在多少个字里出现，超过这个比例就认定它是「偏旁」而非「主体」。
# 主体（被保留、有辨识度的部分）应当是出现频率较低的那个部件。
# 这里用绝对计数而非比例：出现次数越少 = 越独特 = 越可能是主体。
MAX_CANDIDATES = 20          # 每个字最多保留多少个通假候选，控制 mapping.json 体积
MIN_BODY_LEN = 1             # 主体签名最短长度（过滤掉空主体）

# 过于常见、单独作为「主体」没有辨识度的部件——即便偶然成为某字的最低频部件也跳过。
# 这些大多是独体笔画或极简部件，共享它们不会让两个字「看起来像」。
TRIVIAL_BODIES = set("一丨丶丿乙亅丷冂冖凵") | {""}


# ──────────────────────────────────────────────
# Stage 1: 生成 all_basic_hanzi.json
# ──────────────────────────────────────────────

def stage_basic():
    print("=== Stage: all_basic_hanzi ===")
    if not os.path.exists(IDS_SOURCE_FILE):
        sys.exit(f"错误：找不到 {IDS_SOURCE_FILE}")

    all_basic = {}
    for char, info in parse_ids_file(IDS_SOURCE_FILE).items():
        ids, ids_apparent = info["IDS"], info["IDS_apparent"]
        all_basic[char] = {
            "Codepoint": info["Codepoint"],
            "IDS": ids,
            "IDS_components": get_ids_components_list(ids),
            "IDS_apparent": ids_apparent,
            "IDS_apparent_components": get_ids_components_list(ids_apparent),
        }

    save_json(all_basic, ALL_BASIC_HANZI_FILE)
    print(f"生成 {ALL_BASIC_HANZI_FILE}：{len(all_basic)} 个基础汉字\n")
    return all_basic


# ──────────────────────────────────────────────
# Stage 2: 生成 mapping.json（核心算法）
# ──────────────────────────────────────────────
# 一个合体字 = 偏旁(radical) + 主体(body)。主体是有辨识度、出现频率低的部件。
# 「原字 src 能替换成候选字 dst」有两种来源：
#
#   (A) 包含（containment）：src 整体就是 dst 的主体，dst 相当于「给 src 添了个偏旁」。
#       例如 我 → 俄(⿰亻我)、哦(⿰口我)；早 → 章(⿱立早)、草(⿱艹早)、卓(⿱⺊早)。
#       src 被完整保留，肉眼一定认得出，所以不限制 src 自身结构（独体字也行）。
#
#   (B) 同主体（shared body）：src 与 dst 共享同一个子主体 B，只是各自的偏旁不同。
#       例如 操(⿰扌喿) → 懆(⿰忄喿)；你(⿰亻尔) → 称(⿰禾尔)。
#       这种情况下必须满足下面的结构约束。
#
# 结构约束（仅作用于情况 B）：
#   - 主体 B 在 src、dst 中必须位于相同的视觉侧（同为 trail 等）；
#   - 顶层结构符必须相同（⿰↔⿰、⿱↔⿱…），唯一例外是允许 ⿺ → ⿰
#     （为了 逼 ⿺辶畐 → 福 ⿰示畐），且方向单一——反向的 ⿰ → ⿺ 不允许。
#     其余跨结构一律禁止：于是 早 ⿱日十 不会跨成 叶 ⿰口十，
#     麻 ⿸广林 不会跨成 諃 ⿰言林，痹 ⿸疒畀 不会跨成 睤 ⿰目畀。
#
# 兜底（情况 A、B 都没有候选时）：
#   (C) 去偏旁（strip radical）：若 src 的主体 B 本身是个真字，且与 src 同音（拼音完全
#       相同），就把 src 映射成 B —— 相当于「擦掉偏旁」。例如 莱(⿱艹来) → 来，读音都是 lái。

ALLOWED_CROSS = {("⿺", "⿰")}   # (源结构, 目标结构) 唯一允许的跨结构方向


def _structure_of(ids):
    """返回 (operator, [(child_sig, side), ...])；非合体字返回 (None, [])。"""
    op, children = top_level_components(ids)
    if op is None or len(children) < 2:
        return None, []
    n = len(children)
    return op, [(sig, side_bucket(op, i, n)) for i, sig in enumerate(children)]


def _op_compatible(op_src, op_dst):
    """情况 B 的结构兼容性：同结构，或唯一允许的 ⿺→⿰ 跨结构。"""
    return op_src == op_dst or (op_src, op_dst) in ALLOWED_CROSS


def _radical_freq(parts, body_sig, comp_freq):
    """dst 中「非主体」部件的最高频率，用来衡量被添加 / 替换的偏旁有多常见。
    越常见 = 拼出来越像个真字，排序时优先。"""
    others = [comp_freq[sig] for sig, _ in parts if sig != body_sig]
    return max(others) if others else 0


def _same_pinyin(a, b):
    """两个单字读音是否完全相同（忽略声调，取首选读音）。"""
    pa = lazy_pinyin(a, style=Style.NORMAL)
    pb = lazy_pinyin(b, style=Style.NORMAL)
    return bool(pa) and pa == pb


def stage_mapping(all_basic=None):
    print("=== Stage: mapping ===")
    if all_basic is None:
        if not os.path.exists(ALL_BASIC_HANZI_FILE):
            sys.exit(f"错误：找不到 {ALL_BASIC_HANZI_FILE}，请先运行 --stage basic")
        all_basic = load_json(ALL_BASIC_HANZI_FILE)

    # 1) 解析每个字的顶层结构（优先表观结构）。
    structured = {}            # char -> (op, [(child_sig, side), ...])
    for char, info in all_basic.items():
        op, parts = _structure_of(choose_ids(info))
        if parts:
            structured[char] = (op, parts)

    # 2) 统计每个部件签名在多少个不同的字里出现（用于区分偏旁 / 主体）。
    comp_freq = collections.Counter()
    for _op, parts in structured.values():
        for sig, _side in set(parts):     # 同一字内去重，避免叠字重复计数
            comp_freq[sig] += 1

    # 3) 确定每个字的主体（频率最低且非平凡的顶层部件），并建立
    #    主体签名 → [(字, 结构符, 视觉侧)] 索引，供两种匹配查询。
    body_of = {}                                       # char -> (body_sig, body_side)
    chars_with_body = collections.defaultdict(list)    # body_sig -> [(char, op, side)]
    for char, (op, parts) in structured.items():
        # 候选主体：排除平凡部件；必须至少在 2 个字里出现，才有替换余地。
        cands = [
            (comp_freq[sig], sig, side)
            for sig, side in parts
            if sig not in TRIVIAL_BODIES and len(sig) >= MIN_BODY_LEN and comp_freq[sig] >= 2
        ]
        if not cands:
            continue
        # 频率最低 = 最有辨识度的主体；同频时取签名较长者更稳健。
        cands.sort(key=lambda t: (t[0], -len(t[1])))
        _freq, body_sig, body_side = cands[0]
        body_of[char] = (body_sig, body_side)
        chars_with_body[body_sig].append((char, op, body_side))

    # 4) 为每个字生成候选：先「包含」（整字作主体，更像原字），后「同主体」。
    #    by_mechanism 记录每个字的映射出自哪种机制（A/B/C），供报告分类统计。
    mapping = {}
    by_mechanism = {"A": [], "B": [], "C": []}
    for src in all_basic:
        contain, shared, seen = [], [], set()

        # (A) 包含：dst 的主体就是整字 src —— 给 src 添偏旁即得 dst，不限结构。
        for dst, _op_dst, _side_dst in chars_with_body.get(src, ()):
            if dst == src or dst in seen:
                continue
            seen.add(dst)
            rf = _radical_freq(structured[dst][1], src, comp_freq)
            contain.append((-rf, dst))

        # (B) 同主体：与 src 共享同一子主体，且满足结构 / 视觉侧约束。
        #     仅当没有包含候选时才考虑——若 src 能被整体包含进别的字（如 早→章草卓），
        #     说明 src 本身就是个被熟知、可整体认读的字，再拆成同主体的字（隼夲卑卒）
        #     反而破坏整体识别，降低肉眼联想原字的成功率。
        if not contain and src in body_of:
            body_sig, body_side = body_of[src]
            op_src = structured[src][0]
            for dst, op_dst, side_dst in chars_with_body.get(body_sig, ()):
                if dst == src or dst in seen:
                    continue
                if side_dst != body_side or not _op_compatible(op_src, op_dst):
                    continue
                seen.add(dst)
                rf = _radical_freq(structured[dst][1], body_sig, comp_freq)
                shared.append((-rf, dst))

        contain.sort()
        shared.sort()
        siblings = [c for _rf, c in contain] + [c for _rf, c in shared]
        mechanism = "A" if contain else ("B" if shared else None)

        # (C) 兜底：A、B 都没有候选时，若主体本身是个同音真字，就「去偏旁」映射过去。
        #     例如 莱 ⿱艹来 既不被别的字包含、也找不到同主体兄弟，但「来」是真字且同音 lái。
        if not siblings and src in body_of:
            body_sig, _body_side = body_of[src]
            if len(body_sig) == 1 and body_sig in all_basic and _same_pinyin(src, body_sig):
                siblings = [body_sig]
                mechanism = "C"

        if siblings:
            mapping[src] = siblings[:MAX_CANDIDATES]
            by_mechanism[mechanism].append(src)

    save_json(mapping, MAPPING_FILE, compact=True)
    pairs = sum(len(v) for v in mapping.values())
    print(f"生成 {MAPPING_FILE}：{len(mapping)} 个可替换字，共 {pairs} 条候选\n")
    return mapping, by_mechanism, all_basic


# ──────────────────────────────────────────────
# 报告：把映射结果按机制分类写成 markdown
# ──────────────────────────────────────────────

_MECHANISM_TITLES = {
    "A": "A · 包含（src 是 dst 的主体，给 src 添偏旁）",
    "B": "B · 同主体（src 与 dst 共享子主体，偏旁不同）",
    "C": "C · 去偏旁兜底（主体本身是同音真字）",
}


def write_report(mapping, by_mechanism, all_basic, elapsed):
    """把统计与逐字映射写成 markdown 报告（report.md，已 gitignore）。"""
    total = len(all_basic)
    mapped = len(mapping)
    unmapped = sorted(c for c in all_basic if c not in mapping)

    lines = [
        "# 通假字映射报告",
        "",
        "## 总览",
        "",
        f"- 参与字数：**{total}**",
        f"- 得到映射：**{mapped}**（{mapped / total:.1%}）",
        f"- 未获映射：**{len(unmapped)}**（{len(unmapped) / total:.1%}）",
        f"- 脚本用时：**{elapsed:.2f} s**",
        "",
        "### 按机制分类",
        "",
        "| 机制 | 字数 |",
        "| --- | --- |",
    ]
    for key in ("A", "B", "C"):
        lines.append(f"| {_MECHANISM_TITLES[key]} | {len(by_mechanism[key])} |")
    lines.append("")

    # 各机制逐字列出 src → 候选。
    for key in ("A", "B", "C"):
        chars = by_mechanism[key]
        lines.append(f"## {_MECHANISM_TITLES[key]}（{len(chars)} 字）")
        lines.append("")
        if not chars:
            lines.append("（无）")
            lines.append("")
            continue
        for src in chars:
            lines.append(f"- {src} → {' '.join(mapping[src])}")
        lines.append("")

    # 未获映射的字。
    lines.append(f"## 未获映射（{len(unmapped)} 字）")
    lines.append("")
    lines.append("".join(unmapped) if unmapped else "（无）")
    lines.append("")

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"生成 {REPORT_FILE}：{mapped} 映射 / {len(unmapped)} 未映射，用时 {elapsed:.2f}s\n")


# ──────────────────────────────────────────────
# 管线驱动
# ──────────────────────────────────────────────

STAGE_CHOICES = ["basic", "mapping"]


def main():
    parser = argparse.ArgumentParser(description="通假字数据管线")
    parser.add_argument(
        "--stage",
        choices=STAGE_CHOICES,
        help="只运行指定阶段（默认：全流程）",
    )
    args = parser.parse_args()

    start = time.perf_counter()
    if args.stage == "basic":
        stage_basic()
    elif args.stage == "mapping":
        mapping, by_mechanism, all_basic = stage_mapping()
        write_report(mapping, by_mechanism, all_basic, time.perf_counter() - start)
    else:
        # 全流程：把 stage_basic 的结果直接传给 stage_mapping，省去一次磁盘读取。
        all_basic = stage_basic()
        mapping, by_mechanism, all_basic = stage_mapping(all_basic)
        write_report(mapping, by_mechanism, all_basic, time.perf_counter() - start)
        print("全流程完成。")


if __name__ == "__main__":
    main()
