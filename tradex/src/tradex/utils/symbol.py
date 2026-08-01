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
"""


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

    Args:
        code: 6-digit stock code.

    Returns:
        Exchange identifier: 'sh', 'sz', or 'bj'.
    """
    code = normalize_symbol(code)

    if code.startswith(("6",)):
        return "sh"
    elif code.startswith(("0", "1", "2", "3")):
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
    code = normalize_symbol(code)

    if code.startswith("688"):
        return "上交所科创板"
    elif code.startswith("6"):
        return "上交所主板"
    elif code.startswith("300") or code.startswith("301"):
        return "深交所创业板"
    elif code.startswith(("0", "1")):
        return "深交所主板"
    elif code.startswith(("4", "8")):
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
