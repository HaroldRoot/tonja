import re
import os
from datetime import datetime
import logging


# Ideographic Description Characters (IDC)
# 表意文字描述字符
# 1. Unicode range: [\u2FF0-\u2FFF] ⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿼⿽⿾⿿
# 2. Extended IDC (Non-abstract IDC): &U-i001+2FF1; &U-i001+2FFB; &U-i002+2FF1;
# 3. 不在 IDC 区块的: U+303E 形似但不相等, U+31EF 减去笔画, U+2B1A 指无法分割的整体字
# 4. 全角问号字符 U+FF1F ？ 例如 IDS-UCS-Ext-D.txt U-0002B756	𫝖	⿸厃？
IDC_REGEX = r'[\u2FF0-\u2FFF]|&U-i\d+\+2FF[1B];|\u303E|\u31EF|\u2B1A|\uFF1F'


def setup_logger():
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 生成带时间戳的日志文件名，例如: logs/mapping_update_20231027.log
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = os.path.join(log_dir, f"mapping_update_{timestamp}.log")
    
    logger = logging.getLogger("MappingUpdater")
    logger.setLevel(logging.INFO)
    
    # 清除旧的 handlers 避免重复打印
    if logger.hasHandlers():
        logger.handlers.clear()

    # File Handler (写入文件)
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    
    # Stream Handler (输出到控制台)
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter('%(message)s') # 控制台只打印简略信息
    console_handler.setFormatter(console_formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info(f"日志已初始化，写入文件: {log_filename}")
    return logger


def get_ids_components_list(ids_str, remove_char=None):
    """
    将 IDS 字符串解析为组件列表 (List)。
    """
    if not ids_str:
        return []
    
    # 1. 移除 IDC
    cleaned = re.sub(IDC_REGEX, '', ids_str)
    
    # 2. 提取实体组件 (例如 &CDP-8BBF;)
    entities = re.findall(r'&[^;]+;', cleaned)
    
    # 3. 提取普通汉字 (移除实体后剩余的部分)
    temp_str = re.sub(r'&[^;]+;', '', cleaned)
    chars = list(temp_str) # 转为 list，保留重复项
    
    # 4. 合并
    all_comps = chars + entities
    
    # 5. 如果需要移除目标字符 (例如 '女')
    if remove_char:
        # 使用列表推导式过滤，保留其他重复的组件
        all_comps = [c for c in all_comps if c != remove_char]
        
    return all_comps


def get_components_except_target_char(ids_str, target_char='女'):
    """
    将 IDS 字符串解析为组件集合。
    1. 移除指定的 IDC 结构符（包括 Unicode IDC 和 Extended IDC）。
    2. 将剩余部分中的 &...; 实体视为一个完整的组件。
    3. 将剩余的普通汉字视为组件。
    4. 返回一个字符集合 set。
    """
    if not ids_str:
        return set()
    
    # 1. 移除 IDC
    cleaned = re.sub(IDC_REGEX, '', ids_str)
    
    # 2. 提取实体组件 (例如 &CDP-8BBF;)
    # 使用 findall 找到所有 &...; 格式的字符串
    entities = set(re.findall(r'&[^;]+;', cleaned))
    
    # 3. 为了提取普通汉字，先将实体从字符串中移除，避免 & c d p ; 被拆成单字
    temp_str = re.sub(r'&[^;]+;', '', cleaned)
    
    # 4. 提取普通字符组件，并移除目标字符
    chars = set(temp_str)
    chars.discard(target_char)
    
    # 5. 合并实体集合和字符集合
    return chars | entities


def extract_single_component(ids_str, target_char='女'):
    """
    从 IDS 字符串中，去除 IDC 字符和 target_char 后，如果只剩下一个汉字，则返回该汉字。
    否则返回 None。
    """
    comps = get_ids_components_list(ids_str, target_char)
    if len(comps) == 1 and len(comps[0]) == 1:
        return comps[0]
    return None


def remove_existing_keys_from_mapping(mapping_data, reference_keys_set):
    """
    从 mapping_data 字典中删除在 reference_keys_set 中已有的键。
    """
    removed_count = 0
    # 遍历时创建键的列表副本，以便安全地修改字典
    for key in list(mapping_data.keys()):
        if key in reference_keys_set:
            del mapping_data[key]
            removed_count += 1

    return removed_count


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