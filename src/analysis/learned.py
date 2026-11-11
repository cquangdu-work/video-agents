"""Những gì kênh TỰ HỌC được từ số liệu thật — file data/learned.yaml.

Agent Phân tích ghi file này mỗi tuần; các agent khác đọc:
  - Biên tập: trọng số chấm điểm (đè lên scoring_weights trong config/channel.yaml)
  - Biên kịch: các "bài học" rút từ video của chính kênh

Để riêng một file (không sửa thẳng channel.yaml / formula.yaml) vì: giữ nguyên được chú
thích trong file cấu hình, và trên VM không tạo thay đổi vào file git đang theo dõi
(nếu không, lần `git pull` sau sẽ xung đột). Xoá file này = quay về cấu hình gốc.
"""
from pathlib import Path

import yaml

LEARNED_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "learned.yaml"


def load_learned() -> dict:
    if LEARNED_PATH.exists():
        return yaml.safe_load(LEARNED_PATH.read_text(encoding="utf-8")) or {}
    return {}


def save_learned(data: dict) -> Path:
    LEARNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEARNED_PATH.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                            encoding="utf-8")
    return LEARNED_PATH


def apply_learned(cfg: dict) -> dict:
    """Đè trọng số đã học lên cấu hình (chỉ các khoá có sẵn — không cho thêm khoá lạ)."""
    learned = load_learned().get("scoring_weights") or {}
    for k, v in learned.items():
        if k in cfg.get("scoring_weights", {}) and isinstance(v, (int, float)):
            cfg["scoring_weights"][k] = v
    return cfg
