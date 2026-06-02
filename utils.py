"""通用工具集：IDS（表意文字描述序列）解析 + JSON / IDS 文件 I/O。

这里只放**与具体项目无关、可复用**的代码：
  - IDS 字符串的拆解（拍平的部件列表）与结构树解析（保留顶层结构 / 视觉侧）；
  - 读写 JSON、解析 CHISE 风格的 IDS .txt 数据文件。
项目特定的算法（主体识别、通假候选生成）放在 build.py。
"""

import json
import re


# ──────────────────────────────────────────────
# JSON / IDS 文件 I/O
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
    """解析 CHISE 风格的 IDS .txt 文件。

    每行格式为 `<codepoint>\\t<char>\\t<IDS>[\\t@apparent=<IDS>][\\t...]`，
    `;;` 开头为注释。返回 { char: {Codepoint, IDS, IDS_apparent} } 字典。
    """
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
# IDS 部件拆解（拍平）
# ──────────────────────────────────────────────
# Ideographic Description Characters (IDC) 表意文字描述字符：
# 1. Unicode range: [⿰-⿿] ⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿼⿽⿾⿿
# 2. Extended IDC (Non-abstract IDC): &U-i001+2FF1; &U-i001+2FFB; &U-i002+2FF1;
# 3. 不在 IDC 区块的: U+303E 形似但不相等, U+31EF 减去笔画, U+2B1A 指无法分割的整体字
# 4. 全角问号字符 U+FF1F ？ 例如 U-0002B756	𫝖	⿸厃？
IDC_REGEX = r'[⿰-⿿]|&U-i\d+\+2FF[1B];|〾|㇯|⬚|？'


def get_ids_components_list(ids_str, remove_char=None):
    """将 IDS 字符串拍平为组件列表（保留重复项，丢弃结构信息）。"""
    if not ids_str:
        return []

    # 1. 移除 IDC 结构符
    cleaned = re.sub(IDC_REGEX, '', ids_str)

    # 2. 提取实体组件（例如 &CDP-8BBF;）
    entities = re.findall(r'&[^;]+;', cleaned)

    # 3. 提取普通汉字（移除实体后剩余的部分）
    temp_str = re.sub(r'&[^;]+;', '', cleaned)
    chars = list(temp_str)  # 转为 list，保留重复项

    # 4. 合并
    all_comps = chars + entities

    # 5. 如需移除目标字符（例如 '女'）
    if remove_char:
        all_comps = [c for c in all_comps if c != remove_char]

    return all_comps


# ──────────────────────────────────────────────
# 顶层 IDS 结构解析
# ──────────────────────────────────────────────
# 与 get_ids_components_list 不同，下面这组函数保留 IDS 的「顶层结构」：
# 一个结构符（IDC）+ 它直接管辖的若干子部件，而不是把所有部件拍平。
# 这是「替换偏旁但保留主体」所必需的——我们要知道某个部件长在哪个位置。

# 二元结构符（管辖 2 个操作数）
BINARY_IDC = set("⿰⿱⿴⿵⿶⿷⿸⿹⿺⿻⿼⿽")
# 三元结构符（管辖 3 个操作数）
TERNARY_IDC = set("⿲⿳")
# 一元结构符（镜像 / 旋转，管辖 1 个操作数）
UNARY_IDC = set("⿾⿿")
# 扩展 IDC 实体形式，例如 &U-i001+2FF1;
EXT_IDC_RE = re.compile(r"^&U-i\d+\+2FF[0-9A-Fa-f];$")

# (结构符, 子部件下标) → 视觉「侧」。lead = 偏旁/外框惯常所在的一侧（左/上/外），
# trail = 主体惯常所在的一侧（右/下/内），mid = 居中或重叠。
# 这样 ⿺辶畐 的「畐」(trail) 与 ⿰示畐 的「畐」(trail) 能跨结构匹配，
# 而 ⿰喿刂 的「喿」(lead) 与 ⿰扌喿 的「喿」(trail) 不会匹配。
_SIDE_TABLE = {
    "⿰": ("lead", "trail"),          # ⿰ 左右
    "⿱": ("lead", "trail"),          # ⿱ 上下
    "⿲": ("lead", "mid", "trail"),   # ⿲ 左中右
    "⿳": ("lead", "mid", "trail"),   # ⿳ 上中下
    "⿴": ("lead", "trail"),          # ⿴ 全包围
    "⿵": ("lead", "trail"),          # ⿵ 上包围
    "⿶": ("lead", "trail"),          # ⿶ 下包围
    "⿷": ("lead", "trail"),          # ⿷ 左包围
    "⿸": ("lead", "trail"),          # ⿸ 左上包围
    "⿹": ("lead", "trail"),          # ⿹ 右上包围
    "⿺": ("lead", "trail"),          # ⿺ 左下包围
    "⿻": ("mid", "mid"),             # ⿻ 重叠
    "⿼": ("lead", "trail"),
    "⿽": ("lead", "trail"),
}


def side_bucket(operator, idx, n):
    """返回某结构符下第 idx 个部件（共 n 个）的视觉侧：lead / mid / trail。"""
    sides = _SIDE_TABLE.get(operator)
    if sides and idx < len(sides):
        return sides[idx]
    if idx == 0:
        return "lead"
    if idx == n - 1:
        return "trail"
    return "mid"


def _idc_arity(token):
    """返回结构符 token 的元数；非结构符（叶子部件）返回 0。"""
    if token in TERNARY_IDC:
        return 3
    if token in BINARY_IDC:
        return 2
    if token in UNARY_IDC:
        return 1
    if EXT_IDC_RE.match(token):
        last = token.rsplit("+", 1)[1].rstrip(";")[-1].upper()
        return 3 if last in ("2", "3") else 2
    return 0


def tokenize_ids(ids_str):
    """把 IDS 切成 token 列表：&...; 实体视为单个 token，其余按字符切分。"""
    tokens = []
    i, n = 0, len(ids_str)
    while i < n:
        c = ids_str[i]
        if c == "&":
            j = ids_str.find(";", i)
            if j == -1:
                tokens.append(c)
                i += 1
            else:
                tokens.append(ids_str[i:j + 1])
                i = j + 1
        else:
            tokens.append(c)
            i += 1
    return tokens


def _parse_node(tokens, pos):
    """递归下降解析，返回 (node, next_pos)。
    node 形如 ('L', token) 叶子，或 ('O', operator, [child, ...]) 结构节点。"""
    if pos >= len(tokens):
        return None, pos
    tok = tokens[pos]
    pos += 1
    arity = _idc_arity(tok)
    if arity == 0:
        return ("L", tok), pos
    children = []
    for _ in range(arity):
        child, pos = _parse_node(tokens, pos)
        if child is None:
            break
        children.append(child)
    return ("O", tok, children), pos


def parse_ids_tree(ids_str):
    """把 IDS 字符串解析为结构树。空串或解析失败返回 None。"""
    if not ids_str:
        return None
    node, _ = _parse_node(tokenize_ids(ids_str), 0)
    return node


def serialize_tree(node):
    """把结构树序列化回 IDS 字符串（用于生成可比较的部件签名）。"""
    if node is None:
        return ""
    if node[0] == "L":
        return node[1]
    return node[1] + "".join(serialize_tree(c) for c in node[2])


def top_level_components(ids_str):
    """返回顶层结构：(operator, [child_sig, ...])。
    若是单一部件（无结构符）则返回 (None, [整字签名])。"""
    node = parse_ids_tree(ids_str)
    if node is None:
        return None, []
    if node[0] == "L":
        return None, [node[1]]
    return node[1], [serialize_tree(c) for c in node[2]]
