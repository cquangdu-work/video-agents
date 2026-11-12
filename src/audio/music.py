"""Nhạc nền: tự chọn bài theo tâm trạng kịch bản, xoay vòng không lặp, tự hạ nhạc khi có giọng.

Kho nhạc là thư mục assets/music/ (KHÔNG vào git — mỗi máy tự chép nhạc vào). Tên file bắt
đầu bằng nhóm tâm trạng: "calm - Ten bai.mp3", "bright - ...", "serious - ...". File không có
tiền tố được coi là "calm". Thư mục trống hoặc tắt trong config thì video không có nhạc như cũ.

Luồng (gọi từ src/assemble.py):
1. scan_library()   đọc thư mục -> danh sách bài kèm nhóm tâm trạng
2. register()       ghi từng bài vào kho chất liệu kèm giấy phép (agent Kiểm định soát)
3. pick_mood()      đoán tâm trạng từ lời đọc (luật từ khoá — đoán sai thì chỉ hơi lệch nhạc)
4. choose_track()   chọn bài cùng nhóm ít dùng nhất 7 ngày qua (luật chống lặp của kho chất liệu)
5. mix_filter()     đồ thị lọc ffmpeg: lặp/cắt nhạc cho vừa video, lên-xuống nhạc ở hai đầu,
                    nén theo giọng (sidechaincompress: có giọng thì nhạc tự nhỏ), trộn, chuẩn -16 LUFS
"""
import hashlib
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
MUSIC_DIR = ROOT / "assets" / "music"
MOODS = ("calm", "bright", "serious")
EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
DEFAULT_LICENSE = "YouTube Audio Library — không yêu cầu ghi công"

# Từ khoá nhận tâm trạng (đã bỏ dấu cách thừa, so chữ thường). Kênh nói chuyện số liệu nên
# phần lớn video là "calm"; chỉ đổi khi lời đọc nghiêng rõ về một phía.
SERIOUS_WORDS = ("tử vong", "chết", "thiệt mạng", "nạn nhân", "thiên tai", "động đất", "lũ lụt",
                 "bão", "khủng hoảng", "chiến tranh", "ung thư", "tự tử", "ô nhiễm", "dịch bệnh",
                 "báo động", "thảm hoạ", "thảm họa", "nắng nóng", "đói", "nghèo đói", "tai nạn")
BRIGHT_WORDS = ("tăng trưởng", "vượt", "kỷ lục", "dẫn đầu", "bứt phá", "tăng gấp", "cuộc đua",
                "lần đầu", "thành công", "vươn lên", "hạng 1", "đứng đầu", "tăng mạnh", "nhanh nhất")


def mood_of_file(path: Path) -> str:
    """'bright - Sunny Day.mp3' -> 'bright'; không có tiền tố hợp lệ -> 'calm'."""
    m = re.match(r"\s*([a-zA-Z]+)\s*[-_ ]", path.stem)
    mood = m.group(1).lower() if m else ""
    return mood if mood in MOODS else "calm"


def scan_library(folder: Path = MUSIC_DIR) -> list:
    """-> [{"name": tên file, "path": Path, "mood": nhóm}] — tên file dùng làm tên chất liệu."""
    if not folder.is_dir():
        return []
    return [{"name": p.name, "path": p, "mood": mood_of_file(p)}
            for p in sorted(folder.iterdir()) if p.is_file() and p.suffix.lower() in EXTENSIONS]


def register(con, tracks: list, license_text: str = DEFAULT_LICENSE) -> None:
    """Ghi bài nhạc vào bảng assets (kind 'music') — có giấy phép thì Kiểm định mới cho qua."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for t in tracks:
        con.execute("INSERT OR IGNORE INTO assets (kind, name, tags, license, note, created_at)"
                    " VALUES ('music', ?, ?, ?, ?, ?)",
                    (t["name"], t["mood"], license_text, f"assets/music/{t['name']}", now))
    con.commit()


def pick_mood(text: str) -> str:
    """Đoán tâm trạng từ lời đọc: đếm từ khoá. Nghiêm trọng thắng khi có từ 2 dấu hiệu
    (một chữ "chết" lẻ loi trong câu so sánh không đủ đổi nhạc)."""
    t = " ".join(str(text or "").lower().split())
    serious = sum(t.count(w) for w in SERIOUS_WORDS)
    bright = sum(t.count(w) for w in BRIGHT_WORDS)
    if serious >= 2 and serious >= bright:
        return "serious"
    if bright >= 2:
        return "bright"
    return "calm"


def choose_track(tracks: list, mood: str, uses: dict, salt: str = ""):
    """Chọn bài: cùng nhóm tâm trạng (thiếu thì lùi về 'calm', rồi bất kỳ), ít dùng nhất trong 7
    ngày (uses: {tên: số lần}); hoà thì dựa vào `salt` (mã video) để mỗi video ra bài khác nhau
    nhưng chạy lại cùng video thì vẫn đúng bài cũ."""
    pool = ([t for t in tracks if t["mood"] == mood] or [t for t in tracks if t["mood"] == "calm"]
            or list(tracks))
    if not pool:
        return None
    tie = lambda t: hashlib.sha1(f"{salt}|{t['name']}".encode("utf-8")).hexdigest()
    return min(pool, key=lambda t: (uses.get(t["name"], 0), tie(t)))


def select(con, narration: str, salt: str, cfg: dict, folder: Path = MUSIC_DIR):
    """Chọn bài cho một video, hoặc None (kho trống / tắt nhạc trong config).
    -> {"name", "path", "mood", "mood_wanted"}."""
    mcfg = (cfg or {}).get("music") or {}
    if not mcfg.get("enabled", True):
        return None
    tracks = scan_library(folder)
    if not tracks:
        return None
    register(con, tracks, mcfg.get("license", DEFAULT_LICENSE))
    from ..assets_db import uses_last_week
    uses = {t["name"]: uses_last_week(con, t["name"]) for t in tracks}
    wanted = pick_mood(narration)
    track = choose_track(tracks, wanted, uses, salt)
    limit = int(mcfg.get("max_uses_per_week", 3))
    if uses.get(track["name"], 0) >= limit:
        log.warning("Nhạc '%s' đã dùng %d lần trong 7 ngày (trần %d) — kho nhạc nhóm '%s' cần thêm bài",
                    track["name"], uses[track["name"]], limit, track["mood"])
    return dict(track, mood_wanted=wanted)


def mix_filter(duration: float, gain_db: float = -20.0, fade_in: float = 1.0,
               fade_out: float = 1.5) -> str:
    """Đồ thị lọc cho ffmpeg với 3 đầu vào: [0] video câm, [1] giọng đọc, [2] nhạc (-stream_loop -1).
    Kết quả: [aout] = giọng + nhạc đã hạ thấp và tự nhỏ khi có giọng, chuẩn -16 LUFS."""
    d = f"{duration:.3f}"
    out_start = max(duration - fade_out, 0.0)
    # Ép giọng (mono 24 kHz) và nhạc (thường stereo 44,1 kHz) về cùng một định dạng: ffmpeg 4.4
    # trên VM không tự thống nhất được cho sidechaincompress ("could not choose their formats").
    same = "aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
    return (
        f"[2:a]atrim=0:{d},asetpts=N/SR/TB,{same},volume={gain_db}dB,"
        f"afade=t=in:st=0:d={fade_in},afade=t=out:st={out_start:.3f}:d={fade_out}[m];"
        f"[1:a]{same},asplit=2[v][key];"
        # có giọng -> nhạc bị nén mạnh (tự nhỏ đi); hết giọng -> nhạc nhích lên trong 0,4 giây
        f"[m][key]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400[duck];"
        f"[v][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
        f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]"   # loudnorm tự nâng lên 192 kHz
    )
