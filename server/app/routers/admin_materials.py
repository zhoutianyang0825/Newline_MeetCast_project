"""管理端 · 素材 3 接口（Newline_MeetCast_API_Spec.md §四，JWT）

4.1 GET    /api/admin/materials        素材列表（F4.2）
4.2 POST   /api/admin/materials        公共素材上传（F4.1）
4.3 DELETE /api/admin/materials/{id}   删除（F4.2；专属素材同步下发 CLEAN_MATERIAL）
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.errors import (
    ApiError,
    CODE_MATERIAL_NOT_FOUND,
    CODE_PARAM_INVALID,
    CODE_QUOTA_EXCEEDED,
)
from app.files import ensure_format, remove_file, save_upload
from app.response import ok
from app.schemas import MaterialItem, MaterialUploadOut
from app.security import auth_admin, auth_user
from app.settings import MAX_MATERIALS, MAX_TOTAL_MB, PUBLIC_BASE
from app.store import Material, store, utc_now_iso

router = APIRouter(prefix="/api/admin/materials", tags=["admin-materials"])


# ============ 4.1 素材列表 ============

@router.get("")
def list_materials(
    scope: str | None = Query(None, description="public / meeting，不传=全部"),
    meeting_id: str | None = Query(None, description="只看某场会的专属素材"),
    tag: str | None = Query(None, description="按标签过滤，如 brand"),
    category: str | None = Query(None, description="按业务分类过滤：brand/culture/meeting/other"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _user_id: str = Depends(auth_user),
) -> dict:
    """素材列表（F4.2）。

    得到的数据：
        scope（可选过滤，"public"/"meeting"）；meeting_id（可选）；
        tag（可选标签）；category（可选业务分类）；page/page_size。

    要做的操作：
        scope 传了但不是 public/meeting → 1001；
        调 store.list_materials 取本页（支持 tag + category 双过滤），逐条转 MaterialItem。

    返回：
        {"items": [{"material_id": "mat_001", "name": "brand-default.png",
                    "category": "brand", "tags": ["brand"], ...}], "total": 3}

    为什么：素材库要按公共/专属两轨看，同时非技术用户更习惯"先按用途（品牌/文化墙/会议）缩范围"，
            标签则是运营自己的细粒度标记——两者并存，一个粗筛一个细筛。
    """
    if scope is not None and scope not in ("public", "meeting"):
        raise ApiError(CODE_PARAM_INVALID, "scope 只允许 public / meeting")
    rows, total = store.list_materials(
        scope=scope, meeting_id=meeting_id, page=page, page_size=page_size,
        tag=tag, category=category,
    )
    items = [
        MaterialItem(
            material_id=m.material_id,
            name=m.name,
            format=m.format,
            size_mb=m.size_mb,
            url=m.url,
            scope=m.scope,
            meeting_id=m.meeting_id,
            category=m.category,
            tags=m.tags,
            uploaded_by=m.uploaded_by,
            expire_at=m.expire_at,
            created_at=m.created_at,
        ).model_dump()
        for m in rows
    ]
    return ok({"items": items, "total": total})


# ============ 4.2 公共素材上传 ============

@router.post("")
async def upload_public_material(
    file: UploadFile = File(...),
    scope: str = Form("public"),
    category: str = Form("other"),
    tags: str | None = Form(None),
    expire_at: str | None = Form(None),
    actor_id: str = Depends(auth_user),
) -> dict:
    """公共素材上传（F4.1 / F4.2）。

    得到的数据：
        file（multipart 文件，≤500MB）；scope（固定 public，专属素材走 §5 免登录通道）；
        category（业务分类，默认 other）；tags（逗号分隔标签）；expire_at（可选有效期）；
        actor_id（登录用户，普通用户也可传）。

    要做的操作：
        scope 不是 public → 1001；格式白名单校验 → 2005；
        分块落盘（超 500MB → 2007）；条数/容量超配额 → 2011 并回滚文件；
        建 Material 行（category/tags 落库供筛选，last_used_at 供 15 天 LRU）。

    返回：
        {"material_id": "mat_032", "url": "http://localhost:8000/media/mat_032.png"}

    为什么：公共素材是行政/运营的常规入口，按 F8.1 普通用户就能传，不必管理员；
            category 在入库时就定下来，后面列表按用途筛选才不用猜。
    """
    if scope != "public":
        raise ApiError(CODE_PARAM_INVALID, "公共素材上传 scope 必须为 public，专属素材请走免登录上传链接")
    if store.material_quota()[0] >= MAX_MATERIALS:
        raise ApiError(CODE_QUOTA_EXCEEDED, f"素材数量已达上限 {MAX_MATERIALS}")
    ext = ensure_format(file.filename or "")

    material_id = f"mat_{uuid.uuid4().hex[:8]}"
    file_path, size_mb = await save_upload(file, material_id)
    # 容量配额：落盘后才知道真实大小，超了必须回滚文件再报错
    _count, used_mb = store.material_quota()
    if used_mb + size_mb > MAX_TOTAL_MB:
        remove_file(file_path)
        raise ApiError(CODE_QUOTA_EXCEEDED, f"素材库容量已达上限 {MAX_TOTAL_MB}MB")

    material = Material(
        material_id=material_id,
        name=file.filename or material_id,
        format=ext,
        size_mb=size_mb,
        url=f"{PUBLIC_BASE}/media/{material_id}.{ext}",
        scope="public",
        category=(category or "other").strip() or "other",
        tags=[t.strip() for t in (tags or "").split(",") if t.strip()],
        uploaded_by=f"user:{actor_id}",
        expire_at=expire_at,
        created_at=utc_now_iso(),
        last_used_at=utc_now_iso(),
        file_path=file_path,
    )
    store.add_material(material)
    print(f"[upload] public material {material_id} ({size_mb}MB) by user:{actor_id} category={category} tags={tags}")
    return ok(MaterialUploadOut(material_id=material_id, url=material.url).model_dump())


# ============ 4.3 删除素材 ============

@router.delete("/{material_id}")
def delete_material(material_id: str, admin_id: str = Depends(auth_admin)) -> dict:
    """删除素材（F4.2），专属素材同步清理设备本地副本（F4.8）。

    得到的数据：
        material_id（要删的素材）；admin_id（审计用）。

    要做的操作：
        查不到 → 2004；
        删记录 + 删本地文件；
        scope=meeting 时，找出会议所在会议室的所有设备，逐台入队 CLEAN_MATERIAL。

    返回：
        {"code": 0, "message": "ok", "data": null}

    为什么：专属素材只删服务端不够——设备本地留着副本，下一场会可能读到残留（PRD 场景 E 补丁）。
    """
    material = store.get_material(material_id)
    if material is None:
        raise ApiError(CODE_MATERIAL_NOT_FOUND, "素材不存在")
    remove_file(material.file_path)
    store.delete_material(material_id)

    cleaned_devices: list[str] = []
    if material.scope == "meeting" and material.meeting_id is not None:
        meeting = store.get_meeting(material.meeting_id)
        if meeting is not None:
            for device in store.devices_in_room(meeting.room_id):
                store.enqueue_command(
                    device_id=device.device_id,
                    type_="CLEAN_MATERIAL",
                    payload={"material_ids": [material_id], "scope": "meeting", "meeting_id": material.meeting_id},
                    initiated_by=f"admin:{admin_id}",
                )
                cleaned_devices.append(device.device_id)
    print(f"[delete] material {material_id} by admin:{admin_id} clean_on={cleaned_devices}")
    return ok(None)
