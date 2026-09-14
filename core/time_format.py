from typing import Optional


def parse_time_str(time_str: str) -> Optional[float]:
    """
    灵活解析时间字符串为浮点秒数。
    支持格式：
    - "01:23:45.678" -> 5025.678
    - "14:23.5" -> 863.5
    - "23.5" 或 "23.5s" -> 23.5
    - "863" -> 863.0
    """
    if not time_str:
        return None
    s = time_str.strip().lower().rstrip("s").strip()
    if not s:
        return None

    try:
        val = float(s)
        return val if val >= 0 else None
    except ValueError:
        pass

    parts = s.split(":")
    if len(parts) == 2:
        try:
            m = float(parts[0])
            sec = float(parts[1])
            if m < 0 or sec < 0 or sec >= 60:
                return None
            return m * 60.0 + sec
        except ValueError:
            return None
    elif len(parts) == 3:
        try:
            h = float(parts[0])
            m = float(parts[1])
            sec = float(parts[2])
            if h < 0 or m < 0 or m >= 60 or sec < 0 or sec >= 60:
                return None
            return h * 3600.0 + m * 60.0 + sec
        except ValueError:
            return None

    return None


def format_time_str(seconds: float) -> str:
    """将秒数格式化为清晰的时间字符串 (HH:MM:SS.mmm 或 MM:SS.mmm)"""
    if seconds is None or seconds < 0:
        return "00:00.000"
    total_sec = max(0.0, float(seconds))
    h = int(total_sec // 3600)
    m = int((total_sec % 3600) // 60)
    s = total_sec % 60

    if h > 0:
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    return f"{m:02d}:{s:06.3f}"
