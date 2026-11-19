"""Bộ nhớ TỰ HỌC của đội agent (19/11/2026). Bốn vòng học — mọi thứ học được nằm ở DỮ LIỆU (bảng
learning_events + data/learned.yaml), không sửa code và KHÔNG BAO GIỜ nới các cổng kiểm chứng:

1. Học từ LỖI CỦA CHÍNH MÌNH — mỗi lỗi các cổng code bắt (đọc bảng, hook "Vì sao", điểm phần trăm,
   biểu đồ bịa số…) được ghi lại; trước khi làm, Biên kịch và Sản xuất đọc "lỗi hay mắc 14 ngày qua"
   của CHÍNH MÌNH kèm ví dụ thật.
2. Học từ DU — ✅/❌/ghi chú được ghi lại; Du dạy luật thẳng qua Telegram (/hoc …, /luat, /quen N);
   Biên kịch đọc mọi luật Du dạy và các nhận xét gần nhất.
3. Học từ NGƯỜI XEM — mỗi tuần agent Phân tích tính kiểu mở đầu / mảng chủ đề / dạng video nào giữ
   chân tốt (co về trung bình khi ít video; vẫn thưởng cái ít được thử — kiểu UCB) -> daily ưu tiên,
   máy chọn hook cộng điểm, Biên kịch được nhắc.
4. Học từ VIDEO TỐT — kịch bản Du đã duyệt mà vẫn qua MỌI cổng hiện tại làm ví dụ nhịp kể (không chép
   câu chữ: chống "nội dung theo mẫu").

Bộ nhớ hỏng (file lỗi, bảng thiếu) thì agent làm việc như chưa học gì — không bao giờ chặn dây chuyền.

    python -m src.learning              # in những gì hệ thống đang "nhớ" (lỗi hay mắc, luật Du, người xem)
    python -m src.learning --backfill   # một lần khi bật: nạp lỗi đã lưu trong hồ sơ kiểm chứng 14 ngày qua
"""
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone

import yaml

from .analysis import learned as store

log = logging.getLogger("learning")


def _safe(fn, default, what: str):
    """Chạy fn(); lỗi thì ghi cảnh báo và trả default — việc học không được làm hỏng việc chính."""
    try:
        return fn()
    except Exception as exc:
        log.warning("Tự học: %s lỗi (bỏ qua): %s", what, exc)
        return default

# ------------------------------------------------------------------ 1. lỗi của chính mình
# (khoá, mẫu nhận ra trong lời báo lỗi của các cổng, tên dễ đọc, cách sửa) — mẫu đầu tiên khớp là thắng.
# Mẫu so trên lời báo lỗi ĐÃ BỎ phần trích câu trong “…” (câu bị trích có thể chứa chữ bất kỳ).
KINDS = [
    # Kiểm chứng (main): "SAI: <khẳng định> -> <ghi chú>", "SAI (cảnh 3): …" — model nhận xét, không phân loại sâu
    ("kiem_chung", r"^SAI(:| \(cảnh)", "Kiểm chứng: câu trái nguồn", "đối chiếu từng câu với tóm tắt"),
    ("hook_vi_sao", r"không trả lời được nguyên nhân", "mở đầu bằng “Vì sao…?” với ý tưởng bảng số",
     "mở bằng đối lập con số, mốc thời gian hoặc thứ hạng bất ngờ"),
    ("xu_huong", r"(tăng|giảm) liên tục nhưng", "nói “liên tục tăng/giảm” trái dãy số",
     "chỉ nói xu hướng chung (\"nhìn chung tăng\") hoặc nêu đúng giai đoạn"),
    ("diem_phan_tram", r"hiệu hai tỷ lệ", "ghi hiệu hai tỷ lệ là “%”", "hiệu hai tỷ lệ là “điểm phần trăm”"),
    ("du_bao", r"nói như dự báo", "nói “dự kiến/sẽ” cho số đã ghi nhận", "số trong bảng là số ĐÃ GHI NHẬN"),
    ("lich_su", r"bảng chỉ có từ năm", "nói “nhất lịch sử/mọi thời đại”", "nói “từ năm <năm đầu bảng>”"),
    ("nam_vuot", r"đã vượt .* (giữa|trước) ", "nói sai năm nước này vượt nước kia",
     "dùng đúng dòng “Năm Y: A vượt B” trong điểm nhấn"),
    ("so_sanh", r"so sánh|ngược chiều|đảo chiều|không có căn cứ", "câu so sánh trái bảng số",
     "chỉ so những cặp số có sẵn trong tóm tắt"),
    ("nguyen_nhan", r"nguyên nhân/bối cảnh", "nêu nguyên nhân mà bảng số không nói",
     "thay bằng điểm nhấn hoặc cách nói dễ hình dung"),
    # Sản xuất (crew.design_scenes) — chỉ đưa cho agent Sản xuất, không đưa Biên kịch
    ("spec_bia_so", r"BỊA SỐ LIỆU", "biểu đồ có số không có trong kịch bản/nguồn",
     "cảnh mà lời đọc không có số thì dùng 'statement'"),
    ("spec_bo_cau", r"^spec chỉ mang", "bỏ sót câu lời đọc", "mọi câu kịch bản nằm nguyên văn trong 'voice'"),
    ("spec_chep_lap", r"^lời đọc bị chép lặp", "chép lặp lời đọc sang cảnh khác",
     "mỗi câu chỉ thuộc một cảnh hoặc các cảnh LIỀN NHAU"),
    ("spec_don_dieu", r"^đơn điệu", "một template chiếm quá nửa video",
     "hai số cùng đơn vị -> 'versus'; số qua các năm -> 'line_chart'; từ 3 mục -> 'bar_chart'"),
    ("spec_canh_ngan", r"^cảnh nhiều chi tiết quá ngắn", "bản đồ/cuộc đua quá ngắn",
     "cảnh map/bar_race gánh trọn 1-2 câu, ≥ 5 giây"),
    ("spec_json", r"^không đọc được danh sách cảnh", "trả lời sai khuôn JSON", "trả về đúng một JSON array"),
    ("bia_so", r"không có trong bài nguồn|BỊA SỐ", "con số không có trong nguồn (thường do tự tính)",
     "chỉ dùng số có sẵn — tóm tắt đã tính sẵn tỷ số, số năm"),
    ("dinh_nghia", r"định nghĩa chỉ số", "câu định nghĩa chỉ số ở 15 giây đầu",
     "định nghĩa để trên chữ của biểu đồ, lời đọc chứng minh hook"),
    ("hai_cau_khong_so", r"hai câu liền nhau không có con số", "15 giây đầu có hai câu không số liền nhau",
     "cảnh 2-5 xen kẽ: con số -> nó nghĩa là gì"),
    ("cau_dem", r"câu đệm", "câu đệm chung chung", "mỗi câu phải có thông tin mới hoặc diễn giải con số"),
    ("lui_qua_khu", r"lùi về quá khứ", "lùi về năm đầu bảng ngay đầu video", "chứng minh hook trước"),
    ("cau_ket", r"câu kết không quay lại", "câu kết không quay lại hook", "nhắc lại đúng con số của hook"),
    ("doc_bang", r"câu có số đứng liền nhau", "đọc bảng: nhiều câu nêu số MỚI liền nhau",
     "sau mỗi con số đắt là một câu nói nó nghĩa là gì, không thêm số mới"),
    ("moc_nam", r"mốc năm như đọc bảng", "nhắc quá nhiều mốc năm", "giữ 4-5 mốc năm đắt nhất"),
    ("so_viet_chu", r"viết bằng CHỮ", "viết số bằng chữ", "luôn viết chữ số: 73%, 2018, 8,9"),
    ("hook_lap", r"lặp cách mở", "mở đầu giống video gần đây", "đổi kiểu mở đầu"),
    ("hook_cam", r"^câu mở đầu:", "câu mở đầu phạm khuôn cấm", "xem LUẬT HOOK"),
    ("it_so", r"con số trong lời đọc \(cần", "quá ít con số", "đủ 5-7 con số đắt nhất"),
    ("so_tu", r"^\d+ từ \(cần", "sai ngân sách số từ", "đếm từ trước khi trả lời"),
    ("so_canh", r"^\d+ cảnh \(cần", "sai số cảnh", "mỗi câu một cảnh"),
    ("canh_dung_yen", r"đứng yên quá lâu", "một hình gánh quá nhiều lời",
     "câu dài thì chia nhiều cảnh LIỀN NHAU cùng 'voice'"),
]
LESSON_DAYS = 14
WRITER_STAGES = ("writer", "final")       # lỗi lúc viết + lỗi Kiểm chứng/chống bịa số -> Biên kịch học
PRODUCER_STAGES = ("spec",)               # lỗi spec cảnh -> agent Sản xuất học
QUOTED = re.compile(r"“[^”]*”")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def kind_of(problem: str) -> str:
    """Loại lỗi của một lời báo lỗi cổng code ('khac' nếu không nhận ra)."""
    text = QUOTED.sub("“…”", str(problem or ""))
    for key, pat, _, _ in KINDS:
        if re.search(pat, text):
            return key
    return "khac"


def record(con, source: str, kind: str, detail: str = "", stage: str = "", idea_id=None,
           script_id=None, at: str = None) -> None:
    """Ghi một sự kiện học. source: 'gate' (cổng code bắt lỗi), 'du' (approve/reject/note),
    'outcome' (kịch bản ra verified/draft)."""
    def write():
        con.execute("INSERT INTO learning_events (at, source, kind, stage, detail, idea_id, script_id)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (at or _now(), source, kind, stage, str(detail or "")[:400], idea_id, script_id))
        con.commit()
    _safe(write, None, f"ghi sự kiện {source}/{kind}")


def record_problems(con, problems, stage: str, idea_id=None, script_id=None, at: str = None) -> None:
    """Ghi từng lỗi cổng code bắt được (một lời báo lỗi -> một sự kiện có 'kind')."""
    for p in problems or []:
        record(con, "gate", kind_of(p), p, stage, idea_id, script_id, at)


def backfill(con, now: datetime = None) -> int:
    """Nạp MỘT LẦN các lỗi cổng cuối đã lưu sẵn trong hồ sơ kiểm chứng (scripts.factcheck
    ["standard_problems"]) của kịch bản viết trong LESSON_DAYS ngày qua, giữ đúng ngày viết — Biên kịch
    có bài học ngay khi bật tính năng thay vì chờ lỗi mới. Trả về số lỗi đã nạp (0 nếu đã nạp rồi)."""
    from . import db
    if db.get_state(con, "learning_backfilled"):
        return 0
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=LESSON_DAYS)).isoformat(timespec="seconds")
    n = 0
    for r in con.execute("SELECT id, idea_id, factcheck, created_at FROM scripts"
                         " WHERE created_at >= ? AND factcheck IS NOT NULL ORDER BY id", (since,)).fetchall():
        try:
            problems = json.loads(r["factcheck"]).get("standard_problems") or []
        except (ValueError, AttributeError):
            continue
        record_problems(con, problems, "final", r["idea_id"], r["id"], at=r["created_at"])
        n += len(problems)
    db.set_state(con, "learning_backfilled", _now())
    return n


def top_mistakes(con, days: int = LESSON_DAYS, n: int = 5, now: datetime = None,
                 stages=WRITER_STAGES) -> list:
    """[(khoá, số lần, ví dụ gần nhất)] các lỗi cổng code bắt nhiều nhất trong `days` ngày ở các
    khâu `stages` (None = mọi khâu)."""
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat(timespec="seconds")
    where, args = "source='gate' AND kind != 'khac' AND at >= ?", [since]
    if stages:
        where += f" AND stage IN ({','.join('?' * len(stages))})"
        args += list(stages)
    rows = con.execute(f"SELECT kind, COUNT(*) AS c, MAX(id) AS last FROM learning_events WHERE {where}"
                       " GROUP BY kind ORDER BY c DESC, last DESC LIMIT ?", args + [n]).fetchall()
    out = []
    for r in rows:
        ex = con.execute("SELECT detail FROM learning_events WHERE id=?", (r["last"],)).fetchone()["detail"]
        out.append((r["kind"], r["c"], ex))
    return out


def _label(kind: str) -> tuple:
    return next(((label, fix) for key, _, label, fix in KINDS if key == kind), (kind, ""))


def mistakes_block(con, now: datetime = None, stages=WRITER_STAGES, who: str = "BIÊN KỊCH") -> str:
    """Lỗi hay mắc nhất của một agent, kèm cách tránh và ví dụ thật gần nhất — đưa vào prompt."""
    rows = top_mistakes(con, now=now, stages=stages)
    if not rows:
        return ""
    lines = [f"\nLỖI {who} HAY MẮC {LESSON_DAYS} NGÀY QUA (máy đã bắt — đừng lặp lại):"]
    for kind, count, ex in rows:
        label, fix = _label(kind)
        lines.append(f"- {label} ({count} lần). Cách tránh: {fix}. Ví dụ gần nhất: {str(ex)[:140]}")
    return "\n".join(lines) + "\n"


def producer_lessons(con) -> str:
    """Bài học cho agent Sản xuất (dịch kịch bản thành cảnh): lỗi spec hay mắc."""
    return _safe(lambda: mistakes_block(con, stages=PRODUCER_STAGES, who="SẢN XUẤT"), "",
                 "bài học Sản xuất")


# ------------------------------------------------------------------------------ 2. học từ Du
MAX_RULES = 20


def _learned() -> dict:
    data = _safe(store.load_learned, {}, "đọc data/learned.yaml")
    return data if isinstance(data, dict) else {}


def rules() -> list:
    return [r for r in _learned().get("du_rules") or [] if isinstance(r, dict) and r.get("text")]


def add_rule(text: str) -> list:
    """Du dạy một luật (Telegram /hoc …). Trùng thì bỏ qua; giữ tối đa MAX_RULES luật mới nhất.
    (Đọc file KHÔNG qua _safe: file hỏng thì báo lỗi chứ không ghi đè mất những thứ đã học.)"""
    text = " ".join(str(text or "").split())[:300]
    data = store.load_learned()
    current = [r for r in data.get("du_rules") or [] if isinstance(r, dict) and r.get("text")]
    if text and all(r["text"].lower() != text.lower() for r in current):
        current.append({"text": text, "at": _now()[:10]})
    data["du_rules"] = current[-MAX_RULES:]
    store.save_learned(data)
    return data["du_rules"]


def remove_rule(index: int):
    """Bỏ luật số `index` (đánh số từ 1 như /luat in ra). Trả về luật đã bỏ, hoặc None."""
    data = store.load_learned()
    current = [r for r in data.get("du_rules") or [] if isinstance(r, dict) and r.get("text")]
    if not 1 <= index <= len(current):
        return None
    gone = current.pop(index - 1)
    data["du_rules"] = current
    store.save_learned(data)
    return gone


def du_block(con) -> str:
    """Luật Du dạy + nhận xét gần nhất của Du về video (ghi chú khi duyệt/loại)."""
    out = ""
    rs = rules()
    if rs:
        out += ("\nLUẬT DU ĐÃ DẠY (chủ kênh — làm theo, trừ khi trái luật kiểm chứng/chính sách):\n"
                + "\n".join(f"- {r['text']}" for r in rs) + "\n")
    notes = con.execute("SELECT detail, script_id FROM learning_events WHERE source='du' AND kind='note'"
                        " ORDER BY id DESC LIMIT 5").fetchall()
    if notes:
        out += ("\nNHẬN XÉT GẦN ĐÂY CỦA DU KHI DUYỆT VIDEO (tránh lặp lại điều Du chê):\n"
                + "\n".join(f"- {n['detail'][:200]}" for n in notes) + "\n")
    return out


# --------------------------------------------------------------------- 3. học từ người xem
def hook_type(text: str) -> str:
    """Kiểu câu mở đầu, khớp LUẬT HOOK của crew.HOOK_GUIDE: a) đối lập con số, b) mốc thời gian,
    c) thứ hạng, d) câu hỏi; còn lại (điều ngược trực giác...) là 'khac'."""
    t = " ".join(str(text or "").lower().split())
    if t.endswith("?"):
        return "cau-hoi"
    if re.search(r"mới (bằng|đạt)|tương đương|bằng .{0,30}năm \d{4}", t):
        return "moc-thoi-gian"
    if re.search(r"\b(thứ|hạng)\s+\d|đứng đầu|dẫn đầu|bét bảng|chót bảng|cuối bảng|chính giữa|top \d", t):
        return "thu-hang"
    if re.search(r"gấp|hơn|kém|vượt|chỉ (bằng|còn|có)|ngược lại|trong khi|nhưng|bỏ xa|tụt", t):
        return "doi-lap"
    return "khac"


def video_kind(title: str, source_name: str) -> str:
    """Dạng video theo tiêu đề ý tưởng mà các nguồn bảng số tự đặt: "Bản đồ thế giới: …" (World Bank,
    OWID), "Cuộc đua …" / "…: cuộc đua theo quốc tịch…" (KOSIS), còn lại là biểu đồ đường/cột."""
    from .sources.datatable import is_data_source
    title = str(title or "").lower()
    if not is_data_source(source_name):
        return "bai-bao"
    if title.startswith("bản đồ"):
        return "ban-do"
    if "cuộc đua" in title:
        return "cuoc-dua"
    return "bieu-do"


def features(hook: str, title: str, source_name: str) -> dict:
    from .sources.datatable import topic_family
    return {"hook": hook_type(hook), "family": topic_family(source_name), "kind": video_kind(title, source_name)}


def _hook_of(body: str) -> str:
    try:
        scenes = yaml.safe_load(body or "") or []
        return str(scenes[0].get("voice") or "") if scenes else ""
    except Exception:
        return ""


SHRINK = 3.0          # mỗi giá trị như thể có thêm 3 video "trung bình": ít video thì không kết luận mạnh
EXPLORE = 0.5         # thưởng cho cái ít được thử (đơn vị độ lệch chuẩn)


def update_preferences(con, rows: list, now: datetime = None) -> dict:
    """Agent Phân tích gọi mỗi tuần: kiểu mở đầu / mảng / dạng video nào giữ chân tốt.
    Thước đo: % lượt xem qua vài giây đầu (engaged) nếu đủ, không thì % xem trung bình, không nữa thì
    log lượt xem. Lưu vào learned.yaml["preferences"]. Trả về phần đã lưu."""
    metric = next((m for m in ("engaged_pct", "avg_view_pct")
                   if sum(1 for r in rows if r.get(m) is not None) >= max(3, len(rows) // 2)), "views")
    samples = []
    for r in rows:
        v = r.get(metric)
        if v is None:
            continue
        if metric == "views":
            v = math.log10(1 + float(v))
        row = con.execute("SELECT s.body, i.title, i.source_name FROM scripts s JOIN ideas i ON i.id = s.idea_id"
                          " WHERE s.id=?", (r.get("script_id"),)).fetchone()
        if row:
            samples.append((features(_hook_of(row["body"]), row["title"], row["source_name"]), float(v)))
    if len(samples) < 3:
        return {}
    vals = [v for _, v in samples]
    mean = sum(vals) / len(vals)
    sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
    prefs = {"metric": metric, "based_on": len(samples), "mean": round(mean, 3), "sd": round(sd, 3),
             "updated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
    for ftype in ("hook", "family", "kind"):
        groups = {}
        for f, v in samples:
            groups.setdefault(f[ftype], []).append(v)
        prefs[ftype] = {k: {"n": len(vs), "mean": round(sum(vs) / len(vs), 3),
                            "score": round((sum(vs) + SHRINK * mean) / (len(vs) + SHRINK), 3)}
                        for k, vs in groups.items()}
    data = store.load_learned()
    data["preferences"] = prefs
    store.save_learned(data)
    return prefs


def preferences() -> dict:
    """Sở thích người xem agent Phân tích đã học ({} nếu chưa có / file hỏng)."""
    prefs = _learned().get("preferences")
    return prefs if isinstance(prefs, dict) else {}


def preference_bonus(feats: dict, prefs: dict = None, cap: float = 3.0) -> float:
    """Điểm cộng (đơn vị độ lệch chuẩn, kẹp trong ±cap) cho một ứng viên theo những gì người xem đã cho
    thấy. Giá trị chưa thử lần nào được thưởng thăm dò (kiểu UCB) để hệ thống vẫn tiếp tục thử cái mới."""
    prefs = preferences() if prefs is None else prefs

    def compute():
        if not prefs.get("based_on"):
            return 0.0
        n_all, mean, sd = prefs["based_on"], prefs["mean"], prefs.get("sd") or 1.0
        bonus = 0.0
        for ftype, value in feats.items():
            st = (prefs.get(ftype) or {}).get(value) or {"n": 0, "score": mean}
            bonus += (st["score"] - mean) / sd + EXPLORE * math.sqrt(math.log(n_all + 1) / (st["n"] + 1))
        return round(max(-cap, min(cap, bonus)), 3)
    return _safe(compute, 0.0, "tính điểm sở thích người xem")


# story.hook_score chấm theo bậc 1 điểm (có số +2, có đối lập +1, độ dài +1): kẹp dưới 0,5 thì điểm
# người xem chỉ phân thắng thua giữa các phương án NGANG điểm luật, không bao giờ thắng được luật
HOOK_BONUS_CAP = 0.45


def hook_bonus(text: str, prefs: dict = None) -> float:
    """Điểm cộng cho MỘT câu mở đầu theo kiểu của nó (máy chọn hook trong 3 phương án)."""
    return preference_bonus({"hook": hook_type(text)}, prefs, cap=HOOK_BONUS_CAP)


def viewer_block(prefs: dict = None) -> str:
    """Nhắc Biên kịch những gì người xem kênh này đã cho thấy (chỉ khi đủ video để nói)."""
    prefs = preferences() if prefs is None else prefs
    hooks = {k: v for k, v in (prefs.get("hook") or {}).items() if v["n"] >= 2}
    if prefs.get("based_on", 0) < 4 or len(hooks) < 2:
        return ""
    unit = {"engaged_pct": "% lượt xem qua vài giây đầu", "avg_view_pct": "% thời lượng được xem"}.get(
        prefs["metric"], "lượt xem (thang log)")
    best = max(hooks, key=lambda k: hooks[k]["score"])
    worst = min(hooks, key=lambda k: hooks[k]["score"])
    return (f"\nNGƯỜI XEM KÊNH NÀY ({prefs['based_on']} video, đo bằng {unit}): mở đầu kiểu “{best}”"
            f" giữ chân tốt nhất ({hooks[best]['mean']}), kiểu “{worst}” kém nhất ({hooks[worst]['mean']})."
            " Ưu tiên kiểu tốt nhưng vẫn đổi cách viết mỗi video.\n")


# ------------------------------------------------------------------------ 4. học từ video tốt
def exemplar_block(con, idea: dict, cfg: dict) -> str:
    """Một kịch bản Du ĐÃ DUYỆT, cùng dạng (bảng số / bài báo) với ý tưởng đang viết, vẫn qua MỌI cổng
    hiện tại (kịch bản đời cũ có câu đệm, đọc bảng thì không được làm mẫu), giữ chân tốt nhất nếu đã
    có số liệu. Không có thì "" — kho mẫu tự đầy lên khi Du duyệt video khổ mới."""
    from . import crew
    from .sources.datatable import is_data_source
    want = is_data_source(idea.get("source_name"))
    rows = con.execute(
        "SELECT s.id, s.body, s.idea_id, i.summary, i.source_name,"
        " (SELECT engaged_views * 1.0 / NULLIF(views, 0) FROM video_stats st WHERE st.video_id = v.id"
        "  ORDER BY st.id DESC LIMIT 1) AS kept"
        " FROM videos v JOIN scripts s ON s.id = v.script_id JOIN ideas i ON i.id = s.idea_id"
        " WHERE v.status IN ('approved', 'published') ORDER BY v.id DESC LIMIT 40").fetchall()
    best = None
    for r in rows:
        if r["idea_id"] == idea.get("id") or is_data_source(r["source_name"]) != want:
            continue
        try:
            scenes = [s for s in yaml.safe_load(r["body"] or "") or [] if isinstance(s, dict)]
        except yaml.YAMLError:
            continue
        script = {"scenes": scenes}
        if crew.script_problems(script, cfg) or crew.content_problems(script, r["summary"]):
            continue
        key = (r["kept"] or 0.0, r["id"])
        if best is None or key > best[0]:
            best = (key, scenes)
    if not best:
        return ""
    lines = "\n".join(f"{k}. {s.get('voice', '')}" for k, s in enumerate(best[1], 1))
    return ("\nVÍ DỤ MỘT KỊCH BẢN DU ĐÃ DUYỆT (qua mọi cổng hiện tại) — học NHỊP và cách nói ý nghĩa của"
            " con số; KHÔNG chép câu chữ, KHÔNG lặp cách mở đầu (video theo mẫu bị YouTube cắt kiếm tiền):\n"
            + lines + "\n")


def writer_lessons(con, idea: dict, cfg: dict) -> str:
    """Toàn bộ "bài học" đưa cho Biên kịch trước khi viết một ý tưởng (phần nào lỗi thì bỏ phần đó)."""
    parts = [("lỗi hay mắc", lambda: mistakes_block(con)), ("luật Du", lambda: du_block(con)),
             ("sở thích người xem", viewer_block), ("kịch bản mẫu", lambda: exemplar_block(con, idea, cfg))]
    return "".join(_safe(fn, "", what) for what, fn in parts)


# ---------------------------------------------------------------------------- báo cáo tuần
def weekly_lines(con, now: datetime = None) -> list:
    """Vài dòng "hệ thống đã học gì" cho báo cáo tuần của agent Phân tích."""
    now = now or datetime.now(timezone.utc)
    week = (now - timedelta(days=7)).isoformat(timespec="seconds")
    prev = (now - timedelta(days=14)).isoformat(timespec="seconds")

    def rate(a, b):
        rows = dict(con.execute("SELECT status, COUNT(*) FROM scripts WHERE created_at >= ? AND created_at < ?"
                                " GROUP BY status", (a, b)).fetchall())
        total = sum(rows.values())
        return (rows.get("verified", 0), total)
    v1, t1 = rate(week, now.isoformat(timespec="seconds"))
    v0, t0 = rate(prev, week)
    lines = ["", "🧠 Tự học:"]
    if t1:
        lines.append(f"  Kịch bản đạt cổng tuần này: {v1}/{t1}" + (f" (tuần trước {v0}/{t0})" if t0 else ""))
    for stages, who in ((WRITER_STAGES, "Biên kịch"), (PRODUCER_STAGES, "Sản xuất")):
        for kind, count, _ in top_mistakes(con, days=7, n=3, now=now, stages=stages):
            lines.append(f"  Lỗi {who} hay gặp: {_label(kind)[0]} — {count} lần (đã đưa vào lời dặn)")
    du = dict(con.execute("SELECT kind, COUNT(*) FROM learning_events WHERE source='du' AND at >= ?"
                          " GROUP BY kind", (week,)).fetchall())
    if du:
        lines.append(f"  Du: duyệt {du.get('approve', 0)}, loại {du.get('reject', 0)},"
                     f" {du.get('note', 0)} nhận xét (Biên kịch đọc 5 nhận xét gần nhất)")
    rs = rules()
    if rs:
        lines.append(f"  Luật Du đã dạy: {len(rs)} (gửi /luat để xem, /quen N để bỏ)")
    prefs = preferences()
    if prefs.get("based_on"):
        hooks = sorted((prefs.get("hook") or {}).items(), key=lambda kv: -kv[1]["score"])
        lines.append(f"  Người xem ({prefs['based_on']} video): kiểu mở đầu "
                     + ", ".join(f"{k} {v['mean']} (n={v['n']})" for k, v in hooks))
    return lines if len(lines) > 2 else []


def main():
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from . import db
    from .main import load_config
    con = db.connect()
    if "--backfill" in sys.argv:
        print(f"Đã nạp {backfill(con)} lỗi cũ từ hồ sơ kiểm chứng (0 = đã nạp từ trước).")
    print(mistakes_block(con) or "(Biên kịch: chưa ghi nhận lỗi nào)")
    print(producer_lessons(con) or "(Sản xuất: chưa ghi nhận lỗi nào)")
    print(du_block(con) or "(Du chưa dạy luật nào)")
    print("Sở thích người xem:", json.dumps(preferences(), ensure_ascii=False, indent=1))
    print(exemplar_block(con, {"source_name": "World Bank Open Data"}, load_config()) or "(chưa có kịch bản mẫu)")


if __name__ == "__main__":
    main()
