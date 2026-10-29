"""P0 补齐项冒烟（F1.1 二维码 / F3.4 标牌时段 / F4.2 素材分类与预览）

用法：cd server && uv run python scripts/mock_p0_gap.py
前置：服务已启动

序列：
  ① GET /api/admin/rooms              → 4 间房，每间带 bind_url + qr_svg
  ② 二维码内容正确                     → bind_url 含 room_id 且指向后台设备页
  ③ 二维码 SVG 合法                    → 以 <svg 开头、含 path
  ④ 素材分类字段                       → 种子素材 category=brand
  ⑤ 分类过滤 category=brand           → 命中；category=culture → 不命中
  ⑥ 上传带 category=culture           → 落库后按该分类可查回
  ⑦ 标牌页按 slot 渲染                 → /ui/display/signage.html?slot=morning 返回 200
  ⑧ 会议页按 layout 渲染               → /ui/display/meeting.html?layout=minimal 返回 200
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.jwtauth import create_token  # noqa: E402

BASE_URL = "http://localhost:8000"
ADMIN = {"Authorization": f"Bearer {create_token('admin_001')}"}


def check(step: str, got: int, want: int, extra: str = "") -> None:
    """断言业务码并打印结果。"""
    mark = "PASS" if got == want else "FAIL"
    suffix = f"  {extra}" if extra else ""
    print(f"[{mark}] {step}  → code={got}（期望 {want}）{suffix}")
    if got != want:
        sys.exit(1)


def expect(step: str, ok: bool, extra: str = "") -> None:
    """断言布尔条件。"""
    mark = "PASS" if ok else "FAIL"
    suffix = f"  {extra}" if extra else ""
    print(f"[{mark}] {step}{suffix}")
    if not ok:
        sys.exit(1)


def main() -> None:
    with httpx.Client(timeout=30) as client:
        # ① 会议室列表 + 二维码
        r = client.get(f"{BASE_URL}/api/admin/rooms", headers=ADMIN).json()
        check("① rooms 列表", r["code"], 0)
        rooms = r["data"]["items"]
        expect("① 4 间会议室", len(rooms) == 4, f"{len(rooms)} 间")
        expect("① 每间都有二维码", all(x.get("qr_svg") for x in rooms), "全部内联 SVG")

        # ② 二维码内容 = 后台绑定页 + room_id
        sample = rooms[0]
        expect("② bind_url 带 room_id",
               sample["room_id"] in sample["bind_url"] and "/ui/index.html" in sample["bind_url"],
               sample["bind_url"])

        # ③ SVG 合法性
        svg = sample["qr_svg"]
        expect("③ SVG 结构合法", svg.lstrip().startswith("<?xml") or svg.lstrip().startswith("<svg"),
               f"{len(svg)}B")
        expect("③ SVG 含路径数据", "<path" in svg or "<rect" in svg)

        # ④ 种子素材分类
        r = client.get(f"{BASE_URL}/api/admin/materials", headers=ADMIN,
                       params={"scope": "public", "page_size": 50}).json()
        check("④ 素材列表", r["code"], 0)
        cats = {m["material_id"]: m.get("category") for m in r["data"]["items"]}
        expect("④ 种子素材 category=brand", cats.get("mat_001") == "brand", f"mat_001 → {cats.get('mat_001')}")

        # ⑤ 分类过滤
        rb = client.get(f"{BASE_URL}/api/admin/materials", headers=ADMIN,
                        params={"scope": "public", "category": "brand"}).json()
        rc = client.get(f"{BASE_URL}/api/admin/materials", headers=ADMIN,
                        params={"scope": "public", "category": "culture"}).json()
        expect("⑤ category=brand 命中", rb["data"]["total"] >= 1, f"total={rb['data']['total']}")
        expect("⑤ category=culture 不命中", rc["data"]["total"] == 0, f"total={rc['data']['total']}")

        # ⑥ 上传时指定分类
        with open(Path(__file__).resolve().parent.parent.parent / "brand" / "logo_icon.png", "rb") as fp:
            up = client.post(f"{BASE_URL}/api/admin/materials", headers=ADMIN,
                             files={"file": ("culture-wall.png", fp, "image/png")},
                             data={"scope": "public", "category": "culture", "tags": "文化墙,测试"}).json()
        check("⑥ 上传 category=culture", up["code"], 0)
        new_id = up["data"]["material_id"]
        rc2 = client.get(f"{BASE_URL}/api/admin/materials", headers=ADMIN,
                         params={"scope": "public", "category": "culture"}).json()
        expect("⑥ 新素材可按分类查回",
               any(m["material_id"] == new_id for m in rc2["data"]["items"]),
               f"{new_id} in culture total={rc2['data']['total']}")

        # 清理本次上传，避免污染后续断言
        client.delete(f"{BASE_URL}/api/admin/materials/{new_id}", headers=ADMIN)

        # ⑦⑧ 大屏页支持 slot / layout 参数
        for path, label in [
            ("/ui/display/signage.html?slot=morning&room=Room-A3-01&next=10:00%20%E4%BA%A7%E5%93%81%E8%AF%84%E5%AE%A1%E4%BC%9A", "⑦ 标牌 slot=morning"),
            ("/ui/display/signage.html?slot=evening", "⑦ 标牌 slot=evening"),
            ("/ui/display/meeting.html?layout=focus", "⑧ 会议页 layout=focus"),
            ("/ui/display/meeting.html?layout=minimal", "⑧ 会议页 layout=minimal"),
        ]:
            resp = client.get(f"{BASE_URL}{path}")
            expect(label, resp.status_code == 200, f"HTTP {resp.status_code}")

    print("\nP0 补齐项冒烟全过：二维码 / 素材分类 / 大屏参数 均可用")


if __name__ == "__main__":
    main()
