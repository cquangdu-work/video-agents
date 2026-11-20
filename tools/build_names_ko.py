"""Dựng assets/geo/names_ko.json — tên nước TIẾNG HÀN cho kênh Hàn (src/render/geo.country_names).

    curl -L -o ne_50m.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson
    python tools/build_names_ko.py ne_50m.geojson assets/geo/names_ko.json

Tên lấy từ cột NAME_KO của Natural Earth (phạm vi công cộng), khoá là mã của assets/geo/world.json.
NAME_KO là tên CHÍNH THỨC (대한민국, 중화인민공화국); video nói theo cách báo chí Hàn hay viết -> SHORT.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHORT = {"KOR": "한국", "PRK": "북한", "CHN": "중국", "TWN": "대만", "USA": "미국", "GBR": "영국",
         "RUS": "러시아", "COD": "콩고민주공화국", "COG": "콩고", "CZE": "체코", "DOM": "도미니카공화국",
         "CAF": "중앙아프리카공화국", "LAO": "라오스", "SYR": "시리아", "IRN": "이란", "VEN": "베네수엘라",
         "BOL": "볼리비아", "TZA": "탄자니아", "MDA": "몰도바", "MKD": "북마케도니아", "PSE": "팔레스타인"}


def build(ne_path: Path, out_path: Path) -> dict:
    ne = json.loads(Path(ne_path).read_text(encoding="utf-8"))
    world = {}
    for f in ("world.json", "world_ko.json"):           # bản đồ góc nhìn Hàn có thêm Kosovo (XKX)
        path = ROOT / "assets" / "geo" / f
        if path.exists():
            world.update(json.loads(path.read_text(encoding="utf-8"))["countries"])
    ko = {}
    for f in ne["features"]:
        p = f["properties"]
        for key in (p.get("ADM0_A3"), p.get("ISO_A3"), p.get("ISO_A3_EH")):
            if key and key != "-99" and p.get("NAME_KO") and key not in ko:
                ko[key] = p["NAME_KO"]
    if "KOS" in ko:
        ko.setdefault("XKX", ko["KOS"])
    names = {c: SHORT.get(c) or ko[c] for c in sorted(world) if c in ko or c in SHORT}
    missing = sorted(set(world) - set(names))
    if missing:
        raise SystemExit(f"Thiếu tên tiếng Hàn cho: {missing}")
    Path(out_path).write_text(json.dumps({"source": "Natural Earth 1:50m NAME_KO (public domain)"
                                                    " + tên thường dùng (tools/build_names_ko.py)",
                                          "names": names}, ensure_ascii=False, indent=1), encoding="utf-8")
    return names


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    got = build(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"Đã ghi {len(got)} tên nước tiếng Hàn")
