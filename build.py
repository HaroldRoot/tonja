import argparse
import collections
import json
import os
import sys

from utils import (
    get_ids_components_list,
    parse_ids_tree,
    serialize_tree,
    side_bucket,
    top_level_components,
)

# ──────────────────────────────────────────────
# 文件路径常量
# ──────────────────────────────────────────────
IDS_SOURCE_FILE = "IDS-UCS-Basic.txt"
ALL_BASIC_HANZI_FILE = "all_basic_hanzi.json"
MAPPING_FILE = "mapping.json"

# 一个部件在多少个字里出现，超过这个比例就认定它是「偏旁」而非「主体」。
# 主体（被保留、有辨识度的部分）应当是出现频率较低的那个部件。
# 这里用绝对计数而非比例：出现次数越少 = 越独特 = 越可能是主体。
MAX_CANDIDATES = 20          # 每个字最多保留多少个通假候选，控制 mapping.json 体积
MIN_BODY_LEN = 1             # 主体签名最短长度（过滤掉空主体）

# 过于常见、单独作为「主体」没有辨识度的部件——即便偶然成为某字的最低频部件也跳过。
# 这些大多是独体笔画或极简部件，共享它们不会让两个字「看起来像」。
TRIVIAL_BODIES = set("一丨丶丿乙亅丷冂冖凵") | {""}


# ──────────────────────────────────────────────
# 公共 I/O 工具
# ──────────────────────────────────────────────

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data, path, compact=False):
    with open(path, "w", encoding="utf-8") as f:
        if compact:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, f, ensure_ascii=False, indent=4, sort_keys=True)


def parse_ids_file(filepath):
    """解析单个 IDS .txt 文件，返回 { char: {Codepoint, IDS, IDS_apparent} } 字典。"""
    records = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith(";;") or not line:
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            codepoint, character, ids = parts[0], parts[1], parts[2]
            if len(character) != 1:
                continue
            ids_apparent = ""
            for part in parts[3:]:
                if part.startswith("@apparent="):
                    ids_apparent = part.split("=", 1)[1]
                    break
            records[character] = {
                "Codepoint": codepoint,
                "IDS": ids,
                "IDS_apparent": ids_apparent,
            }
    return records


def choose_ids(info):
    """优先使用表观结构（@apparent），它更贴近肉眼看到的字形；否则用功能结构。"""
    return info.get("IDS_apparent") or info.get("IDS") or ""


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
# 思路（见 IDEA.md）：
#   一个合体字 = 偏旁(radical) + 主体(body)。主体是有辨识度、出现频率低的部件；
#   偏旁是高频、可被替换的部件。把「主体 + 它所在的视觉侧」作为分组键，
#   同组的字互为通假候选——它们共享主体，只是偏旁不同，于是肉眼能联想原字，
#   而结构符可以不同（逼 ⿺辶畐 与 福 ⿰示畐 同属「畐 · trail」组）。
#   ⿰喿刂 的「喿」在左(lead)，与 ⿰扌喿 的「喿」在右(trail)不同组，自动排除。

def _structure_of(ids):
    """返回 (operator, [(child_sig, side), ...])；非合体字返回 (None, [])。"""
    op, children = top_level_components(ids)
    if op is None or len(children) < 2:
        return None, []
    n = len(children)
    return op, [(sig, side_bucket(op, i, n)) for i, sig in enumerate(children)]


def stage_mapping(all_basic=None):
    print("=== Stage: mapping ===")
    if all_basic is None:
        if not os.path.exists(ALL_BASIC_HANZI_FILE):
            sys.exit(f"错误：找不到 {ALL_BASIC_HANZI_FILE}，请先运行 --stage basic")
        all_basic = load_json(ALL_BASIC_HANZI_FILE)

    # 1) 解析每个字的顶层结构（优先表观结构）。
    structured = {}            # char -> [(child_sig, side), ...]
    for char, info in all_basic.items():
        op, parts = _structure_of(choose_ids(info))
        if parts:
            structured[char] = parts

    # 2) 统计每个部件签名在多少个不同的字里出现（用于区分偏旁 / 主体）。
    comp_freq = collections.Counter()
    for parts in structured.values():
        for sig, _side in set(parts):     # 同一字内去重，避免叠字重复计数
            comp_freq[sig] += 1

    # 3) 按「主体签名 + 视觉侧」分组。主体 = 字内频率最低且非平凡的部件。
    pools = collections.defaultdict(list)     # (body_sig, side) -> [char, ...]
    body_of = {}                               # char -> (body_sig, side)
    for char, parts in structured.items():
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
        _freq, body_sig, side = cands[0]
        body_of[char] = (body_sig, side)
        pools[(body_sig, side)].append(char)

    # 4) 为每个字生成候选列表：同组内的其他字。
    mapping = {}
    for char, key in body_of.items():
        siblings = [c for c in pools[key] if c != char]
        if not siblings:
            continue
        # 确定性排序：先按「替换后偏旁越常见越自然」（偏旁高频优先），再按字符。
        siblings.sort(key=lambda c: (-_radical_freq(structured[c], key[0], comp_freq), c))
        mapping[char] = siblings[:MAX_CANDIDATES]

    save_json(mapping, MAPPING_FILE, compact=True)
    pairs = sum(len(v) for v in mapping.values())
    print(f"生成 {MAPPING_FILE}：{len(mapping)} 个可替换字，共 {pairs} 条候选\n")
    return mapping


def _radical_freq(parts, body_sig, comp_freq):
    """该字中「非主体」部件的最高频率，用来衡量这个字的偏旁有多常见。"""
    others = [comp_freq[sig] for sig, _ in parts if sig != body_sig]
    return max(others) if others else 0


# ──────────────────────────────────────────────
# 管线驱动
# ──────────────────────────────────────────────

STAGES = {
    "basic": stage_basic,
    "mapping": stage_mapping,
}

FULL_PIPELINE = ["basic", "mapping"]


def main():
    parser = argparse.ArgumentParser(description="通假字数据管线")
    parser.add_argument(
        "--stage",
        choices=list(STAGES.keys()),
        help="只运行指定阶段（默认：全流程）",
    )
    args = parser.parse_args()

    if args.stage:
        STAGES[args.stage]()
    else:
        # 全流程：把 stage_basic 的结果直接传给 stage_mapping，省去一次磁盘读取。
        all_basic = stage_basic()
        stage_mapping(all_basic)
        print("全流程完成。")


if __name__ == "__main__":
    main()

