"""免登录上传 2 接口（Newline_MeetCast_API_Spec.md §五，URL token 认证 · F4.7 / 场景 E）

5.1 GET  /api/upload/{token}   会议与上传信息
5.2 POST /api/upload/{token}   上传会议专属素材

token 规则（规范 §八）：绑定 meeting_id；会后失效；max_uses 默认 50；超额 → 1004。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, UploadFile

from app.errors import (
    ApiError,
    CODE_MEETING_UNAVAILABLE,
    CODE_TOKEN_INVALID,
    CODE_UPLOAD_CLOSED,
)
from app.files import ensure_format, save_upload
from app.response import ok
from app.schemas import UploadedFileItem, UploadInfoOut, UploadResultOut
from app.settings import ACCEPTED_FORMATS, MAX_FILE_MB, PUBLIC_BASE, UPLOAD_LEAD_MIN
from app.store import (
    Material,
    shift_minutes,
    store,
    utc_now_iso,
)

router = APIRouter(prefix="/api/upload", tags=["upload"])


def _load_context(token: str) -> tuple:
    """token → (token 行, 会议行)，顺带做三件事校验。

    得到的数据：
        token（URL 里那段随机串，如 "tok_demo_123"）。

    要做的操作：
        token 不存在/已撤销/用满 max_uses → 1004；
        会议不存在或已取消 → 2010；
        已过上传截止（会前 30 分钟）→ 2006。

    返回：
        (UploadToken, Meeting)，供 GET/POST 两个接口共用。

    为什么：两个接口的准入条件完全一样，校验收口一处，避免两边判据漂移。
    """
    upload_token = store.get_upload_token(token)
    if upload_token is None or upload_token.revoked_at is not None:
        raise ApiError(CODE_TOKEN_INVALID)
    if upload_token.used_count >= upload_token.max_uses:
        raise ApiError(CODE_TOKEN_INVALID, "token 使用次数已用尽")
    meeting = store.get_meeting(upload_token.meeting_id)
    if meeting is None or meeting.status == "cancelled":
        raise ApiError(CODE_MEETING_UNAVAILABLE)
    if utc_now_iso() > shift_minutes(meeting.start_time_utc, -UPLOAD_LEAD_MIN):
        raise ApiError(CODE_UPLOAD_CLOSED)
    return upload_token, meeting


def _uploaded_of(meeting_id: str) -> list[UploadedFileItem]:
    """该会议已上传的专属素材列表。

    得到的数据：
        meeting_id（会议业务主键）。

    要做的操作：
        取该会的 meeting 级素材，转成上传页要的 {name, size_mb, status}。

    返回：
        [UploadedFileItem(name="Q3-review-cover.png", size_mb=2.4, status="ready")]

    为什么：定会者上传页要能看见"我刚传了哪几个文件"，避免重复上传。
    """
    rows = store.meeting_materials(meeting_id)
    return [UploadedFileItem(name=m.name, size_mb=m.size_mb) for m in rows]


# ============ 5.1 会议与上传信息 ============

@router.get("/{token}")
def upload_info(token: str) -> dict:
    """免登录上传页的会议信息。

    得到的数据：
        token（URL 里那段随机串）。

    要做的操作：
        走 _load_context 做 1004 / 2010 / 2006 三道校验；
        拼会议信息 + 上传约束（500MB、白名单格式）+ 已传列表。

    返回：
        {"meeting_id": "meeting_123", "subject": "产品评审会",
         "room_name": "Room-A3-01 · 上海总部 3F", "upload_deadline_utc": "...",
         "max_size_mb": 500, "accepted_formats": ["jpg", "jpeg", "mp3", "mp4", "png"], "uploaded": []}

    为什么：定会者点邮件链接进来，第一眼要知道"传什么会、什么时候截止、能传多大"。
    """
    _token_row, meeting = _load_context(token)
    room = store.get_room(meeting.room_id)
    return ok(UploadInfoOut(
        meeting_id=meeting.meeting_id,
        subject=meeting.subject,
        room_name=room.room_name if room else meeting.room_id,
        start_time_utc=meeting.start_time_utc,
        end_time_utc=meeting.end_time_utc,
        timezone=meeting.timezone,
        upload_deadline_utc=shift_minutes(meeting.start_time_utc, -UPLOAD_LEAD_MIN),
        max_size_mb=MAX_FILE_MB,
        accepted_formats=sorted(ACCEPTED_FORMATS),
        uploaded=_uploaded_of(meeting.meeting_id),
    ).model_dump())


# ============ 5.2 上传会议专属素材 ============

@router.post("/{token}")
async def upload_meeting_material(token: str, file: UploadFile = File(...)) -> dict:
    """上传本场会专属素材（F4.7）。

    得到的数据：
        token（免登录凭据）；file（multipart 文件，≤500MB）。

    要做的操作：
        走 _load_context 校验（1004 / 2010 / 2006）；
        格式白名单 → 2005；分块落盘（超限 → 2007）；
        建 Material 行：scope=meeting、绑定 meeting_id、expire_at=会议结束；
        token.used_count += 1。

    返回：
        {"material_id": "mat_001", "name": "Q3-review-cover.png", "status": "ready"}

    为什么：专属素材只本场会可见、会后自动清理，所以必须绑 meeting_id 并带过期时刻。
    """
    upload_token, meeting = _load_context(token)
    ext = ensure_format(file.filename or "")
    material_id = f"mat_{uuid.uuid4().hex[:8]}"
    file_path, size_mb = await save_upload(file, material_id)

    material = Material(
        material_id=material_id,
        name=file.filename or material_id,
        format=ext,
        size_mb=size_mb,
        url=f"{PUBLIC_BASE}/media/{material_id}.{ext}",
        scope="meeting",
        meeting_id=meeting.meeting_id,
        category="meeting",
        uploaded_by=f"organizer:{upload_token.organizer_email}",
        expire_at=meeting.end_time_utc,
        created_at=utc_now_iso(),
        last_used_at=utc_now_iso(),
        file_path=file_path,
    )
    store.add_material(material)
    upload_token.used_count += 1
    store.save_upload_token_usage(upload_token.token, upload_token.used_count)
    print(f"[upload] meeting material {material_id} ({size_mb}MB) by organizer:{upload_token.organizer_email}")
    return ok(UploadResultOut(material_id=material_id, name=material.name).model_dump())
