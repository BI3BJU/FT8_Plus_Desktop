# ft8_callsign.py - 呼号校验与提取（纯函数，不依赖 Core）
import re


def is_valid_callsign(call: str) -> bool:
    """3~7 位；1~2 前缀 + 1 数字 + 0~4 字母；前缀至少含一个字母。"""
    call = call.strip().upper()
    if not (3 <= len(call) <= 7):
        return False
    if not re.fullmatch(r'^[A-Z0-9]{1,2}[0-9][A-Z]{0,4}$', call):
        return False
    prefix = re.match(r'^[A-Z0-9]{1,2}', call).group()
    return bool(re.search(r'[A-Z]', prefix))


def extract_source_callsign(raw_text):
    """Extract the source callsign: the token before the first space.

    Falls back to prefix scanning when no space is present.
    """
    if not raw_text:
        return None
    raw_upper = raw_text.strip().upper()
    space_idx = raw_upper.find(' ')
    if space_idx != -1:
        src_part = raw_upper[:space_idx].strip()
        if is_valid_callsign(src_part):
            return src_part
    # Fallback: try prefixes of decreasing length
    for length in range(7, 2, -1):
        if len(raw_upper) >= length:
            cand = raw_upper[:length]
            if is_valid_callsign(cand):
                return cand
    return None


def extract_target_callsign(raw_text):
    """Extract the target callsign: the token between the first and second space."""
    if not raw_text:
        return None
    raw_upper = raw_text.strip().upper()
    first_space = raw_upper.find(' ')
    if first_space == -1:
        return None
    second_space = raw_upper.find(' ', first_space + 1)
    if second_space == -1:
        cand = raw_upper[first_space + 1:].strip()
    else:
        cand = raw_upper[first_space + 1:second_space].strip()
    return cand if is_valid_callsign(cand) else None


def parse_message_callsigns(raw_text):
    return (extract_source_callsign(raw_text),
            extract_target_callsign(raw_text))
