"""Dựng bản đồ thế giới từ Natural Earth (phạm vi công cộng) cho mẫu "map".

    # tải bản gốc (một lần): admin 0 countries 1:50m
    curl -L -o ne_50m.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson
    python tools/build_world_map.py ne_50m.geojson assets/geo/world.json
    python tools/build_world_map.py ne_50m.geojson assets/geo/world_ko.json --view ko   # kênh tiếng Hàn

GÓC NHÌN (--view, 20/11/2026): vn (mặc định, kênh Việt) dùng cột ADM0_A3_VN + tên tiếng Việt; ko (kênh Hàn) dùng
ADM0_A3_KO + tên tiếng Hàn (NAME_KO, sửa thành tên thường dùng theo tools/build_names_ko.SHORT). Đo 20/11 trên
Natural Earth 1:50m: hai cột chỉ khác ở Kosovo (Hàn Quốc công nhận Kosovo, Việt Nam thì không). Dokdo / 동해 do
src/render/geo.py tự vẽ (Natural Earth 1:50m không có đảo đó), như Hoàng Sa / Trường Sa của kênh Việt.

Việc script làm:
1. Theo GÓC NHÌN CỦA VIỆT NAM: Natural Earth có cột ADM0_A3_VN cho biết mỗi vùng thuộc nước
   nào theo lập trường Việt Nam — vùng không được công nhận (Kosovo, Somaliland, Bắc Síp,
   sông băng Siachen) được gộp vào nước chủ quyền.
2. Mã nước = mã ISO 3 chữ (ISO_A3_EH) — đúng mã World Bank trả về, để tô màu thẳng theo số liệu.
3. Tên = tên tiếng Việt của Natural Earth (NAME_VI), sửa theo geo.PREFERRED_NAMES; tên gốc và
   tên tiếng Anh giữ làm tên phụ để tra.
4. Bỏ châu Nam Cực, cắt vĩ độ theo BBOX, giảm điểm (Ramer–Douglas–Peucker) và bỏ đảo quá nhỏ:
   cả thế giới chỉ rộng 8,6 đơn vị trên khung dọc, 1 độ ≈ 3 điểm ảnh.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

from build_asia_map import polygons, simplify   # noqa: E402
from src.render.geo import PREFERRED_NAMES, clip_ring   # noqa: E402

BBOX = (-180.0, -58.0, 180.0, 84.0)     # bỏ châu Nam Cực (dưới -60) cho bản đồ đỡ trống
TOLERANCE = 0.15                         # độ (~0,5 điểm ảnh ở tỷ lệ này)
MIN_RING_POINTS = 4
MIN_ISLAND_DEG = 0.6                     # đảo nhỏ hơn chừng này (đường chéo, độ) thì bỏ...
DROP = {"ATA"}                           # châu Nam Cực
WB_CODES = {"KOS": "XKX"}               # Kosovo (chỉ có ở góc nhìn Hàn Quốc): World Bank ghi mã XKX


def iso_of(props: dict) -> str:
    iso = props.get("ISO_A3_EH") or props.get("ISO_A3")
    return iso if iso and iso != "-99" else props["ADM0_A3"]


def ring_size(ring: list) -> float:
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5


def rings_of(geometry: dict, tol: float, digits: int) -> list:
    rings = []
    for ring in polygons(geometry):
        clipped = clip_ring([list(p[:2]) for p in ring], BBOX)
        if len(clipped) < MIN_RING_POINTS:
            continue
        small = simplify(clipped + [clipped[0]], tol)
        small = [[round(x, digits), round(y, digits)] for x, y in small]
        small = [p for i, p in enumerate(small) if i == 0 or p != small[i - 1]]
        if len(small) >= MIN_RING_POINTS:
            rings.append(small)
    return rings


def _name(props: dict, code: str, view: str) -> str:
    if view == "ko":
        from build_names_ko import SHORT
        return SHORT.get(code) or props.get("NAME_KO") or props.get("NAME")
    return PREFERRED_NAMES.get(code) or props.get("NAME_VI") or props.get("NAME")


def build(data: dict, view: str = "vn") -> dict:
    feats = data["features"]
    col = f"ADM0_A3_{view.upper()}"
    # mã ADM0_A3 của nước chủ quyền -> mã ISO, để vùng gộp vào đúng mã của nước đó
    adm_to_iso = {f["properties"]["ADM0_A3"]: iso_of(f["properties"]) for f in feats}
    countries = {}
    for feat in feats:
        props = feat["properties"]
        owner_adm = props.get(col) or props["ADM0_A3"]
        code = adm_to_iso.get(owner_adm, owner_adm)
        code = WB_CODES.get(code, code)
        if code in DROP or props["ADM0_A3"] in DROP:
            continue
        # Nước nhỏ (Singapore, Bahrain, Malta...) bị giảm điểm mất hết -> dựng lại mịn hơn:
        # chúng hay đứng đầu bảng số liệu, không được biến mất khỏi bản đồ
        rings = rings_of(feat["geometry"], TOLERANCE, 1) or rings_of(feat["geometry"], 0.005, 3)
        if not rings:
            continue
        entry = countries.setdefault(code, {"name": None, "aliases": [], "rings": []})
        entry["rings"] += rings
        # Tên lấy từ chính nước đó (không phải vùng được gộp vào). Vài vùng phụ thuộc mang CÙNG mã
        # ISO với nước chủ (quần đảo Ashmore và Cartier: ADM0_A3=ATC nhưng ISO=AUS) -> chúng chỉ
        # đặt tên khi chưa có, còn đối tượng có ADM0_A3 trùng mã thì luôn thắng. Ca thật 18/11:
        # Úc bị ghi tên "Quần đảo Ashmore và Cartier" trên mọi bản đồ và cuộc đua.
        if owner_adm == props["ADM0_A3"] and (entry["name"] is None or props["ADM0_A3"] == code):
            entry["name"] = _name(props, code, view)
            entry["aliases"] = sorted({a for a in (props.get("NAME_VI"), props.get("NAME_KO"), props.get("NAME"),
                                                   props.get("NAME_LONG")) if a} - {entry["name"]})
    for code, c in countries.items():
        # đảo nhỏ li ti: bỏ, trừ khi đó là toàn bộ nước (đảo quốc nhỏ vẫn phải có trên bản đồ)
        big = [r for r in c["rings"] if ring_size(r) >= MIN_ISLAND_DEG]
        c["rings"] = big or sorted(c["rings"], key=ring_size)[-1:]
        c["name"] = c["name"] or code
    view_name = {"vn": "Việt Nam", "ko": "Hàn Quốc"}.get(view, view)
    return {"source": "Made with Natural Earth — 1:50m admin 0 countries (public domain),"
                      f" ranh giới theo góc nhìn {view_name} ({col})",
            "projection": "equal_earth", "bbox": list(BBOX), "countries": countries}


def main(src: str, dst: str, view: str = "vn"):
    out = build(json.load(open(src, encoding="utf-8")), view)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    points = sum(len(r) for c in out["countries"].values() for r in c["rings"])
    print(f"{len(out['countries'])} nước/vùng, {points} điểm -> {dst}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):      # console Windows (cp949) không in được tiếng Việt
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    view = "vn"
    if "--view" in args:
        i = args.index("--view")
        view = args[i + 1]
        del args[i:i + 2]
    main(args[0], args[1], view)
