"""Gửi kịch bản đã kiểm chứng vào Telegram để Du duyệt (~5 phút mỗi sáng).

Dùng thẳng Bot API qua HTTP cho nhẹ; chưa cần thư viện bot đầy đủ
vì Giai đoạn 1 chỉ gửi một chiều.
"""
import logging
import os

import requests

log = logging.getLogger(__name__)


def send_message(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.warning("Thiếu TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID — không gửi được")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True},
            timeout=15,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        log.error("Gửi Telegram lỗi: %s", exc)
        return False


def format_script_message(idea: dict, script: dict, factcheck: dict) -> str:
    hooks = "\n".join(f"  {i+1}. {h}" for i, h in enumerate(script.get("hooks", [])))
    scenes = "\n".join(
        f"  🎬 {s['voice']}\n     [{s['visual']}]" for s in script.get("scenes", [])
    )
    fc = "✅ Kiểm chứng ĐẠT" if factcheck.get("pass") else "⚠️ Có điểm chưa kiểm chứng được"
    fails = [v for v in factcheck.get("verdicts", []) if not v.get("ok")]
    fc_detail = "\n".join(f"  ⚠️ {v['claim']} — {v['note']}" for v in fails)
    return (
        f"📝 {idea['title']}\n"
        f"📐 Góc: {idea['angle']}\n"
        f"🔗 Nguồn: {idea['source_url']}\n\n"
        f"HOOK (chọn 1):\n{hooks}\n\n"
        f"KỊCH BẢN:\n{scenes}\n\n"
        f"{fc}\n{fc_detail}"
    )
