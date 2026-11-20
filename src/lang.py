"""NGÔN NGỮ + KÊNH (20/11/2026, Du chốt mở kênh tiếng Hàn).

Cùng một bộ code chạy được nhiều kênh: mỗi kênh là một file cấu hình (config/channel.yaml = kênh Việt,
config/channel_ko.yaml = kênh Hàn) và một thư mục chạy riêng trên VM (dữ liệu, token, video, .env riêng —
đều nằm ngoài git). Chọn kênh bằng biến môi trường CHANNEL_CONFIG (trong .env của thư mục đó); không đặt
thì là kênh Việt, nên kênh Việt chạy y như trước.

Ngôn ngữ của kênh (`channel.language`: vi | ko) quyết định:
- CÁCH VIẾT SỐ: Việt 1.234,5 · Hàn 1,234.5. Bảng số đưa cho Biên kịch phải đúng kiểu người xem đọc — người
  Hàn đọc "2.462" (kiểu Việt = hai nghìn bốn trăm) thành 2,462 (hai phẩy bốn), sai 1.000 lần, mà cổng chống bịa
  số so chữ số nên không bắt được.
- CÁCH NÓI SỐ LỚN: Việt nghìn/triệu/tỷ (bội 1.000) · Hàn 만/억/조 (bội 10.000) — cổng đối chiếu số phải thử
  cả các bội đó ("5,170만 명" = 51.700.000).
- Nhận dạng giọng (Whisper), chữ trong bảng số / lời nhắc model (giai đoạn sau).
"""
import functools
import os
from contextlib import contextmanager
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = "config/channel.yaml"
SUPPORTED = ("vi", "ko")

LOCALES = {
    "vi": {"dec": ",", "thou": ".", "whisper": "vi", "name": "tiếng Việt",
           "scales": ((1e12, "nghìn tỷ"), (1e9, "tỷ"), (1e6, "triệu")), "about": "khoảng"},
    "ko": {"dec": ".", "thou": ",", "whisper": "ko", "name": "tiếng Hàn",
           "scales": ((1e12, "조"), (1e8, "억"), (1e4, "만")), "about": "약"},
}
# bội số khi đối chiếu "số viết gọn" với số trong bảng: 5 triệu = 5000000; 5,170만 = 51700000
SCALE_DIVISORS = {"vi": (1e3, 1e6, 1e9), "ko": (1e3, 1e4, 1e6, 1e8, 1e9, 1e12)}

_override = None


def config_path() -> Path:
    """File cấu hình của kênh đang chạy: CHANNEL_CONFIG (biến môi trường, hoặc trong .env), mặc định kênh Việt.
    Đọc .env trực tiếp vì nhiều module tính đường dẫn lúc import, trước khi main() gọi load_dotenv."""
    name = os.getenv("CHANNEL_CONFIG")
    if not name:
        try:
            from dotenv import dotenv_values
            name = dotenv_values(ROOT / ".env").get("CHANNEL_CONFIG")
        except Exception:
            name = None
    p = Path(name or DEFAULT_CONFIG)
    return p if p.is_absolute() else ROOT / p


@functools.lru_cache(maxsize=8)
def _language_of(path: str) -> str:
    try:
        cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        code = str((cfg.get("channel") or {}).get("language") or "vi").lower()
    except (OSError, yaml.YAMLError):
        code = "vi"
    if code not in SUPPORTED:
        raise ValueError(f"Ngôn ngữ kênh chưa hỗ trợ: {code} (có: {', '.join(SUPPORTED)})")
    return code


def code() -> str:
    """Mã ngôn ngữ của kênh đang chạy ("vi" | "ko")."""
    return _override or _language_of(str(config_path()))


@contextmanager
def using(language: str):
    """Tạm chạy như kênh ngôn ngữ khác (test, công cụ)."""
    global _override
    if language not in SUPPORTED:
        raise ValueError(language)
    old, _override = _override, language
    try:
        yield
    finally:
        _override = old


def locale() -> dict:
    return LOCALES[code()]


# ------------------------------------------------------------------ viết số
def fixed(x: float, decimals: int = 0) -> str:
    """Số với ĐÚNG `decimals` chữ số lẻ theo kiểu của kênh: 1234567.8 -> '1.234.567,8' (vi) | '1,234,567.8' (ko)."""
    s = f"{x:,.{decimals}f}"
    loc = locale()
    return s.replace(",", "\0").replace(".", loc["dec"]).replace("\0", loc["thou"])


def readable(x: float) -> str:
    """Làm tròn vừa đủ để ĐỌC rồi viết theo kiểu của kênh: 36226.97 -> '36.227' | '36,227';
    83.74 -> '83,7' | '83.7'; 0.721 -> '0,72' | '0.72'. Bỏ số 0 thừa (8,90 -> 8,9)."""
    a = abs(x)
    decimals = 0 if a >= 100 else 1 if a >= 10 else 2
    s = f"{x:,.{decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    loc = locale()
    return s.replace(",", "\0").replace(".", loc["dec"]).replace("\0", loc["thou"])


def spoken_scale(x: float) -> str:
    """Cách nói gọn của số rất lớn: 100987686 -> ' (khoảng 101 triệu)' | ' (약 1.01억)'; 51700000 (ko) ->
    ' (약 5,170만)'. Số nhỏ -> ''."""
    loc = locale()
    for size, word in loc["scales"]:
        if abs(x) >= size:
            scaled = x / size
            if code() == "ko":
                if size == 1e4:                            # 만: số nguyên, có dấu phẩy ngăn nghìn
                    return f" ({loc['about']} {fixed(round(scaled))}{word})"
                return f" ({loc['about']} {readable(scaled)}{word})"
            return f" ({loc['about']} {readable(scaled)} {word})"
    return ""


def parse(s: str) -> float:
    """Ngược lại readable/fixed theo kiểu của kênh: '36.227' (vi) | '36,227' (ko) -> 36227."""
    loc = locale()
    return float(str(s).strip().replace(loc["thou"], "").replace(loc["dec"], "."))


def scale_divisors() -> tuple:
    return SCALE_DIVISORS[code()]


def whisper_code() -> str:
    return locale()["whisper"]
