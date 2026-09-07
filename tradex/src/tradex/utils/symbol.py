"""
A-share stock symbol utilities.

Handles Chinese A-share stock code formatting:
- 6-digit codes: 000001, 600519, 300750, 688981, etc.
- Exchange prefix: sh/sz/bj
- Market identification: Main board, ChiNext, STAR, BSE

Exchange rules:
- 600xxx, 601xxx, 603xxx, 605xxx -> Shanghai (sh)
- 688xxx -> Shanghai STAR Market (sh)
- 000xxx, 001xxx, 002xxx, 003xxx -> Shenzhen (sz)
- 300xxx, 301xxx -> Shenzhen ChiNext (sz)
- 4xxxxx, 8xxxxx -> BSE (bj)

Index rules (指数代码白名单, v3.3.2 新增):
- sh000001 -> 上证指数
- sz399001 -> 深证成指
- sz399006 -> 创业板指
- sh000300 -> 沪深300
- sh000688 -> 科创50
- sh000905 -> 中证500
- sz399852 -> 中证1000
"""

# 指数代码白名单：带交易所前缀的指数代码 -> (exchange, 名称)
# 注意：000001 同时是平安银行(SZ)与上证指数(SH)，仅靠 bare code 无法区分，
# 因此白名单只用带前缀代码；bare code 仅收录"非股票专用"的指数代码。
_INDEX_CODES: dict[str, tuple[str, str]] = {
    "sh000001": ("sh", "上证指数"),
    "sz399001": ("sz", "深证成指"),
    "sz399006": ("sz", "创业板指"),
    "sh000300": ("sh", "沪深300"),
    "sh000688": ("sh", "科创50"),
    "sh000905": ("sh", "中证500"),
    "sz399852": ("sz", "中证1000"),
}

# 无前缀、且不会与任何 A 股股票代码冲突的指数代码 -> exchange
_INDEX_BARE: dict[str, str] = {
    "399001": "sz",
    "399006": "sz",
    "399852": "sz",
    "000300": "sh",
    "000688": "sh",
    "000905": "sh",
}

# 指数代码 -> 中文名称（同时收录带前缀与无前缀形式，便于按原始 code 直接查名）
_INDEX_NAME: dict[str, str] = {
    "sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指",
    "sh000300": "沪深300", "sh000688": "科创50", "sh000905": "中证500",
    "sz399852": "中证1000",
    "000300": "沪深300", "000688": "科创50", "000905": "中证500",
    "399001": "深证成指", "399006": "创业板指", "399852": "中证1000",
}


def is_index_code(code: str) -> bool:
    """判断代码是否为指数代码（带前缀或唯一性 bare code 均可）。

    Args:
        code: 股票/指数代码，支持 'sh000001' / '000001' / '399006' 等形式。

    Returns:
        True 若为已知指数代码。
    """
    raw = str(code).strip().lower()
    if raw in _INDEX_CODES:
        return True
    bare = normalize_symbol(code).lower()
    return bare in _INDEX_BARE


def _index_exchange(code: str) -> str | None:
    """返回指数代码的交易所前缀（'sh'/'sz'），非指数返回 None。"""
    raw = str(code).strip().lower()
    if raw in _INDEX_CODES:
        return _INDEX_CODES[raw][0]
    bare = normalize_symbol(code).lower()
    return _INDEX_BARE.get(bare)


def _index_name(code: str) -> str | None:
    """返回指数代码的中文名称，非已知指数返回 None。"""
    raw = str(code).strip().lower()
    return _INDEX_NAME.get(raw)


def normalize_symbol(code: str) -> str:
    """
    Normalize a stock code to 6-digit format.

    Strips any exchange prefix (sh/sz/bj) and ensures 6-digit zero-padded format.

    Args:
        code: Stock code, e.g., '000001', 'sh600519', 'sz.000001', '1'

    Returns:
        6-digit stock code string, e.g., '000001'
    """
    code = str(code).strip().upper()

    # Remove common prefixes
    for prefix in ["SH", "SZ", "BJ", "SH.", "SZ.", "BJ."]:
        if code.startswith(prefix):
            code = code[len(prefix):]
            break

    # Remove any dots or dashes
    code = code.replace(".", "").replace("-", "")

    # Zero-pad to 6 digits
    if code.isdigit():
        code = code.zfill(6)

    return code


def get_exchange(code: str) -> str:
    """
    Determine the exchange for a given A-share stock code.

    Exchange rules (v3.3.9+ 修正债券/可转债误判):
      - 6xxxxx (60/68/90)            -> sh (沪主板/科创/B股)
      - 5xxxxx (50/51/58)            -> sh (沪 ETF/基金/REITs)
      - 11xxxx (110/111/113)         -> sh (沪市可转债/可交换债)
      - 0/2/3xxxxx (00/20/30)        -> sz (深主板/深B/创业板)
      - 12xxxx (123/128)             -> sz (深市可转债)
      - 15xxxx (15/16/18)            -> sz (深 ETF/基金/REITs)
      - 4/8xxxxx (43/83/87/88/920)   -> bj (北交所)

    Args:
        code: 6-digit stock code.

    Returns:
        Exchange identifier: 'sh', 'sz', or 'bj'.
    """
    # 指数代码优先判定（白名单，必须用原始 code 保留 sh/sz 前缀以消歧）
    idx_ex = _index_exchange(code)
    if idx_ex:
        return idx_ex

    code = normalize_symbol(code)

    if code.startswith(("6", "5", "9")) and not code.startswith("920"):
        return "sh"
    elif code.startswith("920"):
        return "bj"
    elif code.startswith(("11", "12")):
        # 债券类：11x 沪市可转债/EB；12x 深市可转债
        return "sh" if code.startswith("11") else "sz"
    elif code.startswith(("0", "1", "2", "3", "15", "16", "18")):
        return "sz"
    elif code.startswith(("4", "8")):
        return "bj"
    else:
        return "sh"  # Default to Shanghai


def get_market_name(code: str) -> str:
    """
    Get the market name for a stock code.

    Args:
        code: 6-digit stock code.

    Returns:
        Human-readable market name in Chinese.
    """
    # 指数代码优先判定（用原始 code 保留前缀）
    idx_name = _index_name(code)
    if idx_name:
        return f"指数 · {idx_name}"

    code = normalize_symbol(code)

    if code.startswith("688"):
        return "上交所科创板"
    elif code.startswith("6"):
        return "上交所主板"
    elif code.startswith("300") or code.startswith("301"):
        return "深交所创业板"
    elif code.startswith(("0", "2", "3")):
        return "深交所主板"
    elif code.startswith("11"):
        return "上交所可转债/EB"
    elif code.startswith("12"):
        return "深交所可转债"
    elif code.startswith("1"):
        return "深交所基金"
    elif code.startswith(("4", "8", "920")):
        return "北交所"
    else:
        return "未知市场"


def format_with_exchange(code: str) -> str:
    """
    Format a stock code with exchange prefix for display.

    Args:
        code: 6-digit stock code.

    Returns:
        Code with exchange prefix, e.g., 'sh600519'.
    """
    # 指数代码优先判定（用原始 code 保留前缀）
    idx_ex = _index_exchange(code)
    if idx_ex:
        return f"{idx_ex}{normalize_symbol(code)}"

    code = normalize_symbol(code)
    exchange = get_exchange(code)
    return f"{exchange}{code}"


def format_em_symbol(code: str) -> str:
    """
    Format a stock code with uppercase exchange prefix for 东方财富 APIs.

    Many EM financial statement APIs require 'SH600519' / 'SZ000001' format.

    Args:
        code: 6-digit stock code.

    Returns:
        Code with uppercase exchange prefix, e.g., 'SH600519'.
    """
    # 指数代码优先判定（用原始 code 保留前缀）
    idx_ex = _index_exchange(code)
    if idx_ex:
        return f"{idx_ex.upper()}{normalize_symbol(code)}"

    code = normalize_symbol(code)
    exchange = get_exchange(code).upper()
    return f"{exchange}{code}"


def is_valid_a_share_code(code: str) -> bool:
    """
    Check if a code is a valid A-share stock code.

    Args:
        code: Stock code to validate.

    Returns:
        True if valid, False otherwise.
    """
    # 指数代码不是 A 股股票（用原始 code 含前缀消歧）
    if is_index_code(code):
        return False
    code = normalize_symbol(code)
    if len(code) != 6 or not code.isdigit():
        return False

    # Valid A-share prefixes
    valid_prefixes = (
        "600", "601", "603", "605",  # Shanghai main board
        "688",                        # Shanghai STAR
        "000", "001", "002", "003",  # Shenzhen main board
        "300", "301",                 # Shenzhen ChiNext
        "4", "8",                     # BSE
    )
    return code.startswith(valid_prefixes)
