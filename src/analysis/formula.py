"""Từ danh sách video đột biến -> file "công thức" config/formula.yaml.

File này được các agent đọc mỗi lần chạy (Biên kịch dùng nhiều nhất).
Agent Phân tích (giai đoạn 4) sẽ cập nhật nó hằng tuần theo số liệu thật của kênh.
"""
import logging
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

FORMULA_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "formula.yaml"


def synthesize_formula(scan_result: dict, cfg: dict) -> Path:
    from ..crew import _run_single_task
    from ..utils import extract_json

    listing = "\n".join(
        f"- [{o['lang']}] \"{o['title']}\" — {o['views']:,} view (gấp {o['ratio']}x trung vị kênh"
        f" {o['channel']}, {o['channel_subs']:,} subs), dài {o['seconds']}s"
        for o in scan_result["outliers"][:60]
    )
    out = _run_single_task(
        role="Nhà phân tích chiến lược nội dung video ngắn",
        goal="Rút ra công thức lặp lại được từ các video ăn khách vượt mức",
        description=f"""Dưới đây là {min(len(scan_result['outliers']), 60)} video NGẮN có lượt xem
gấp nhiều lần mức bình thường của chính kênh đăng nó (tức đề tài/cách làm thắng,
không phải do kênh to sẵn). Kênh của tôi: "{cfg['channel']['name']}" —
{cfg['channel']['description']}

{listing}

Phân tích theo nhóm ngôn ngữ (vi/ko/en) và rút ra công thức CỤ THỂ, dùng lại được:
1. title_patterns: 3-5 khuôn tiêu đề hay thắng (viết dạng khuôn có chỗ trống, tiếng Việt)
2. hook_rules: 3-4 luật viết câu mở đầu rút từ các tiêu đề thắng
3. length_seconds: khoảng độ dài hay thắng nhất
4. topic_clusters: 3-5 cụm đề tài đang ăn khách, cụm nào hợp kênh tôi thì ghi chú
5. notes: 2-3 nhận xét khác đáng chú ý
Chỉ rút từ dữ liệu trên, không bịa.""",
        expected_output="""JSON object:
{"title_patterns": [...], "hook_rules": [...],
 "length_seconds": {"min": n, "max": n},
 "topic_clusters": [{"cluster": "...", "fit": "..."}], "notes": [...]}""",
    )
    formula = extract_json(out)
    formula["_meta"] = {
        "generated_from": f"{scan_result['channels_scanned']} kênh, "
                          f"{len(scan_result['outliers'])} video đột biến",
        "scanned_at": scan_result["scanned_at"],
    }
    FORMULA_PATH.write_text(
        yaml.safe_dump(formula, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return FORMULA_PATH


def load_formula() -> dict | None:
    """Các agent gọi hàm này; chưa có file thì trả None và pipeline vẫn chạy."""
    if FORMULA_PATH.exists():
        return yaml.safe_load(FORMULA_PATH.read_text(encoding="utf-8"))
    return None
