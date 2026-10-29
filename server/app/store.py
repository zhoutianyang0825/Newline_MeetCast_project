"""持久化存储层（M1：SQLAlchemy 10 张表，ADR D1——对外 API 与 demo 版完全一致）

 得到的数据：路由/调度层只认本模块的 dataclass 行对象（Room/Device/Command/...），
          不直接暴露 ORM——换内脏不换骨架，28 个路由零改动
 关键设计：每个方法 = 一次短会话；读：ORM → dataclass；写：dataclass → ORM → commit
 时间口径：对外一律 UTC ISO 串，库里 naive UTC datetime（SQLite/PG 双兼容）

对应 PRD §4.6 与 05_数据模型评审 的 10 张表：
  room / device / command / meeting / upload_token / material /
  material_vector / kb_document / app_user / calendar_config
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.calendar_source import fixture_events
from app.content import is_sensitive
from app.db.session import get_session_factory
from app.models import (
    AppUser as AppUserORM,
    CalendarConfig as CalendarConfigORM,
    Command as CommandORM,
    Device as DeviceORM,
    Material as MaterialORM,
    Meeting as MeetingORM,
    Room as RoomORM,
    UploadToken as UploadTokenORM,
)
from app.settings import PUBLIC_BASE
from app.users import User, make_user


def utc_now_iso() -> str:
    """当前 UTC 时间字符串。

    得到的数据：
        无。

    要做的操作：
        取当前时刻，格式化成 ISO 8601 带秒。

    返回：
        "2026-10-28T08:00:00Z"。

    为什么：规范约定时间一律 UTC ISO 8601，全项目统一这一个出口。
    """
    return datetime.now(UTC).strftime(_ISO_FMT)


def shift_minutes(iso_text: str, minutes: int) -> str:
    """ISO 时间串平移若干分钟。

    得到的数据：
        iso_text（形如 "2026-10-28T02:00:00Z"）；minutes（正数往后、负数往前，如 -30）。

    要做的操作：
        解析成 UTC datetime，加 timedelta，再格式化回同一格式。

    返回：
        "2026-10-28T01:30:00Z"（-30 分钟的例子）。

    为什么：上传截止 = 会前 30 分钟、预拉取 = 会前 10 分钟，都要按会议时间推。
    """
    parsed = datetime.strptime(iso_text, _ISO_FMT).replace(tzinfo=UTC)
    return (parsed + timedelta(minutes=minutes)).strftime(_ISO_FMT)


# ---------- 时间换算（ISO 串 ↔ 库内 naive UTC datetime） ----------

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _iso_to_db(iso_text: str | None) -> datetime | None:
    """ISO 串 → naive UTC datetime（入库用）。

    得到的数据：
        iso_text（形如 "2026-10-28T02:00:00Z"）；None 原样通过。

    要做的操作：
        strptime 解析 → 挂 UTC → 去掉 tzinfo（SQLite 的 DATETIME 不存时区，
        统一按"裸值即 UTC"的口径落库）。

    返回：
        naive UTC datetime；入参 None 返回 None。

    为什么：SQLite/PG 双兼容的前提是"库里永远是 UTC 裸值"，读出侧统一补时区。
    """
    if iso_text is None:
        return None
    return datetime.strptime(iso_text, _ISO_FMT).replace(tzinfo=UTC).replace(tzinfo=None)


def _db_to_iso(dt: datetime | None) -> str | None:
    """库内 datetime（naive UTC）→ ISO 串（出库用）。

    得到的数据：
        dt（从库里读出的 datetime，naive，含义是 UTC）；None 原样通过。

    要做的操作：
        补挂 UTC tzinfo → 格式化成项目统一的 ISO 带秒串。

    返回：
        "2026-10-28T02:00:00Z"；入参 None 返回 None。

    为什么：与 _iso_to_db 成对，保证"存进去什么格式、读出来还是什么格式"。
    """
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC).strftime(_ISO_FMT)


# ---------- 行对象（dataclass，路由/调度层操作的数据形态） ----------

@dataclass
class Room:
    """会议室行对象。

    字段：room_id（身份主键）；room_name（后台展示名）；room_email（M365 资源邮箱）；timezone（IANA 时区名，DST 换算必备）。
    """

    room_id: str
    room_name: str
    room_email: str | None = None
    timezone: str = "Asia/Shanghai"


@dataclass
class Device:
    """设备行对象。

    字段：
        device_id（身份主键）；
        device_key（X-Device-Key 认证凭据）；
        device_name（后台展示名）；
        room_id（绑定会议室，None=未绑定）；
        status（online/offline）；
        device_state（IDLE/MEETING_PREP/MEETING/FALLBACK）；
        playing（当前播放内容标识）；agent_version（上报的 Agent 版本）；
        storage_used_mb（素材占用 MB）；last_heartbeat（最近心跳 UTC ISO）；
        heartbeat_miss（进程内遗留字段，不入库、无判定方）。
    """

    device_id: str
    device_key: str
    device_name: str = ""
    room_id: str | None = None
    status: str = "offline"
    device_state: str = "IDLE"
    playing: str = ""
    agent_version: str = ""
    storage_used_mb: float = 0
    last_heartbeat: str | None = None
    heartbeat_miss: int = 0


@dataclass
class Command:
    """指令行对象（指令队列核心）。

    字段：
        command_id（幂等键主键）；
        device_id（目标设备）；
        type（指令类型枚举）；
        payload（指令参数 dict）；
        status（PENDING→SENT→ACKED/FAILED/TIMEOUT）；
        retry_count（重试计数）；
        initiated_by（触发方，审计必埋）；
        created_at/sent_at/acked_at（入队/下发/回执三个时间点）；
        checksum（防篡改校验串）。
    """

    command_id: str
    device_id: str
    type: str
    payload: dict = field(default_factory=dict)
    status: str = "PENDING"
    retry_count: int = 0
    initiated_by: str = "system"
    created_at: str = ""
    sent_at: str | None = None
    acked_at: str | None = None
    checksum: str = ""


@dataclass
class Meeting:
    """会议行对象。

    字段：
        meeting_id（业务主键，日历事件 id）；
        room_id（所属会议室）；subject（标题）；
        organizer_email（定会者邮箱，免登录上传审计用）；
        attendees（参会人，会议页展示）；
        start_time_utc/end_time_utc（起止 UTC）；
        timezone（渲染时区）；
        status（scheduled/cancelled/ended）；
        is_sensitive（命中敏感词）。
    """

    meeting_id: str
    room_id: str
    subject: str
    organizer_email: str
    start_time_utc: str
    end_time_utc: str
    attendees: list[str] = field(default_factory=list)
    timezone: str = "Asia/Shanghai"
    status: str = "scheduled"
    is_sensitive: bool = False


@dataclass
class UploadToken:
    """免登录上传凭据行对象（F4.7）。

    字段：
    token（URL 随机串，主键）；
    meeting_id（绑定本场会）；
    organizer_email（定会者）；
    expire_at（失效时刻，会后失效）；
    used_count/max_uses（防滥用计数）；
    revoked_at（撤销时刻）。
    """

    token: str
    meeting_id: str
    organizer_email: str
    expire_at: str
    used_count: int = 0
    max_uses: int = 50
    revoked_at: str | None = None


@dataclass
class Material:
    """素材行对象（公共/专属双轨，F4）。

    字段：
        material_id（主键）；
        name/format/size_mb/url（文件本体）；
        scope（public 公共 / meeting 专属）；
        meeting_id（专属素材必填）；
        category（一级业务分类）；
        tags（自由标签）；uploaded_by（上传者，审计枚举）；
        expire_at（专属素材会后过期）；
        created_at/last_used_at（LRU 依据）；
        file_path（本地落盘路径，换 OSS 后由 url 取代）。
    """

    material_id: str
    name: str
    format: str
    size_mb: float
    url: str
    scope: str = "public"
    meeting_id: str | None = None
    category: str = "other"
    tags: list[str] = field(default_factory=list)
    uploaded_by: str = ""
    expire_at: str | None = None
    created_at: str = ""
    last_used_at: str | None = None
    file_path: str = ""


@dataclass
class CalendarConfig:
    """日历源配置行对象（单例，规范 §6）。

    字段：
        provider/tenant/service_account（接入身份）；
        scopes（服务端固定权限）；
        connection_status/credential_expire_at（只读状态，M3 真接入前为 mock 值）；
        pull_policy（拉取策略 dict）；
        alert_email（告警收件人）。
    """

    provider: str = "m365"
    tenant: str = "honghe.onmicrosoft.com"
    service_account: str = "svc-meetcast@honghe.com"
    scopes: list[str] = field(default_factory=lambda: ["Calendars.Read", "Mail.Send"])
    connection_status: str = "connected"
    credential_expire_at: str = "2027-01-04T00:00:00Z"
    pull_policy: dict = field(default_factory=lambda: {
        "schedule": {"enabled": True, "interval_min": 5, "window_hours": 12},
        "link_gen": {"enabled": True, "interval_min": 30, "window_days": 7},
        "dst_enabled": True,
    })
    alert_email: str = "it-admin@honghe.com"


# ---------- ORM ↔ dataclass 转换（模块级私有，每个方法内部调用） ----------

def _room_dc(row: RoomORM) -> Room:
    """Room ORM 行 → Room dataclass。

    得到的数据：
        row（RoomORM 行）。

    要做的操作：
        同名字段逐个搬进 dataclass。

    返回：
        Room dataclass。

    为什么：路由/调度层只认 dataclass，不碰 ORM。
    """
    return Room(room_id=row.room_id, room_name=row.room_name,
                room_email=row.room_email, timezone=row.timezone)


def _device_dc(row: DeviceORM) -> Device:
    """Device ORM 行 → Device dataclass。

    得到的数据：
        row（DeviceORM 行）。

    要做的操作：
        同名字段搬移；None 值回落 dataclass 默认（device_state→IDLE 等）；
        last_heartbeat 转 ISO 串；heartbeat_miss 不入库恒为 0。

    返回：
        Device dataclass。

    为什么：与 _device_apply 成对，保证读写形态一致。
    """
    return Device(device_id=row.device_id, device_key=row.device_key,
                  device_name=row.device_name or "", room_id=row.room_id,
                  status=row.status, device_state=row.device_state or "IDLE",
                  playing=row.playing or "", agent_version=row.agent_version or "",
                  storage_used_mb=row.storage_used_mb or 0,
                  last_heartbeat=_db_to_iso(row.last_heartbeat))


def _device_apply(row: DeviceORM, dc: Device) -> None:
    """Device dataclass 字段刷到 ORM 行（upsert_device 专用）。

    得到的数据：
        row（已取出的 DeviceORM 行，原地修改）；dc（设备 dataclass）。

    要做的操作：
        逐字段覆盖；last_heartbeat 转 naive UTC。

    返回：
        无（commit 由调用方负责）。

    为什么：新建与更新共用一套搬移逻辑，避免两处字段清单漂移。
    """
    row.device_key = dc.device_key
    row.device_name = dc.device_name
    row.room_id = dc.room_id
    row.status = dc.status
    row.device_state = dc.device_state
    row.playing = dc.playing
    row.agent_version = dc.agent_version
    row.storage_used_mb = dc.storage_used_mb
    row.last_heartbeat = _iso_to_db(dc.last_heartbeat)


def _command_dc(row: CommandORM) -> Command:
    """Command ORM 行 → Command dataclass。

    得到的数据：
        row（CommandORM 行）。

    要做的操作：
        同名字段搬移；payload 空值回落 {}；三个时间点转 ISO 串。

    返回：
        Command dataclass。

    为什么：poll/ack/审计接口都消费 dataclass。
    """
    return Command(command_id=row.command_id, device_id=row.device_id,
                   type=row.type, payload=row.payload or {}, status=row.status,
                   retry_count=row.retry_count, initiated_by=row.initiated_by,
                   created_at=_db_to_iso(row.created_at) or "",
                   sent_at=_db_to_iso(row.sent_at),
                   acked_at=_db_to_iso(row.acked_at), checksum=row.checksum)


def _meeting_dc(row: MeetingORM) -> Meeting:
    """Meeting ORM 行 → Meeting dataclass。

    得到的数据：
        row（MeetingORM 行）。

    要做的操作：
        同名字段搬移；attendees 空值回落 []；起止时间转 ISO 串。

    返回：
        Meeting dataclass。

    为什么：状态机/上传页/会议页都消费 dataclass。
    """
    return Meeting(meeting_id=row.meeting_id, room_id=row.room_id,
                   subject=row.subject, organizer_email=row.organizer_email,
                   attendees=row.attendees or [],
                   start_time_utc=_db_to_iso(row.start_time_utc) or "",
                   end_time_utc=_db_to_iso(row.end_time_utc) or "",
                   timezone=row.timezone, status=row.status,
                   is_sensitive=row.is_sensitive)


def _token_dc(row: UploadTokenORM) -> UploadToken:
    """UploadToken ORM 行 → UploadToken dataclass。

    得到的数据：
        row（UploadTokenORM 行）。

    要做的操作：
        同名字段搬移；expire_at/revoked_at 转 ISO 串。

    返回：
        UploadToken dataclass。

    为什么：上传接口与链接生成都消费 dataclass。
    """
    return UploadToken(token=row.token, meeting_id=row.meeting_id,
                       organizer_email=row.organizer_email,
                       expire_at=_db_to_iso(row.expire_at) or "",
                       used_count=row.used_count, max_uses=row.max_uses,
                       revoked_at=_db_to_iso(row.revoked_at))


def _material_dc(row: MaterialORM) -> Material:
    """Material ORM 行 → Material dataclass。

    得到的数据：
        row（MaterialORM 行）。

    要做的操作：
        同名字段搬移；tags 空值回落 []；expire_at/created_at/last_used_at 转 ISO 串。

    返回：
        Material dataclass。

    为什么：素材接口与设备预拉取清单都消费 dataclass。
    """
    return Material(material_id=row.material_id, name=row.name,
                    format=row.format, size_mb=row.size_mb, url=row.url,
                    scope=row.scope, meeting_id=row.meeting_id,
                    category=row.category, tags=row.tags or [],
                    uploaded_by=row.uploaded_by,
                    expire_at=_db_to_iso(row.expire_at),
                    created_at=_db_to_iso(row.created_at) or "",
                    last_used_at=_db_to_iso(row.last_used_at),
                    file_path=row.file_path or "")


def _user_dc(row: AppUserORM) -> User:
    """AppUser ORM 行 → User dataclass（users.py 定义）。

    得到的数据：
        row（AppUserORM 行）。

    要做的操作：
        同名字段搬移。

    返回：
        User dataclass（登录校验 verify_password 直接消费）。

    为什么：认证域的行对象定义在 users.py，这里只做形态转换。
    """
    return User(user_id=row.user_id, email=row.email, name=row.name,
                role=row.role, password_hash=row.password_hash, salt=row.salt)


def _config_dc(row: CalendarConfigORM) -> CalendarConfig:
    """CalendarConfig ORM 行 → CalendarConfig dataclass（补齐只读字段）。

    得到的数据：
        row（CalendarConfigORM 单行）。

    要做的操作：
        库列反拼 pull_policy dict；scopes/connection_status/credential_expire_at
        填服务端固定值（M3 真接入前为 mock 口径）。

    返回：
        CalendarConfig dataclass（字段全集，供 config 接口直接返回）。

    为什么：库只存可变部分，只读部分集中在这里补，保证返回结构稳定。
    """
    return CalendarConfig(
        provider=row.provider,
        tenant=row.tenant or "honghe.onmicrosoft.com",
        service_account=row.service_account or "svc-meetcast@honghe.com",
        connection_status="connected",   # M3 真接入后由连接测试结果驱动
        credential_expire_at="2027-01-04T00:00:00Z",
        pull_policy={
            "schedule": {"enabled": True, "interval_min": row.pull_schedule_min, "window_hours": 12},
            "link_gen": {"enabled": True, "interval_min": row.pull_link_gen_min, "window_days": row.link_window_days},
            "dst_enabled": row.dst_enabled,
        },
        alert_email=row.alert_email or "it-admin@honghe.com",
    )


class Store:
    """持久化存储门面：方法签名与 demo 版一致，内部 = 短会话 + 10 张表。"""

    def __init__(self) -> None:
        # MAIL_MOCK 的调试日志（mock 专用，不入库——真模式走 Graph，无需本地留痕）
        self.mail_log: list[dict] = []

    # ---------- 会议室 ----------

    def get_room(self, room_id: str | None) -> Room | None:
        """按主键取会议室行。

        得到的数据：
            room_id（会议室身份，如 "room-a3-01"）；None 直接返回 None。

        要做的操作：
            按主键查询 room 表。

        返回：
            Room dataclass；不存在返回 None。

        为什么：设备档案/会议室列表/上传页都要"room_id → 展示名与时区"。
        """
        if room_id is None:
            return None
        with get_session_factory()() as s:
            row = s.get(RoomORM, room_id)
            return _room_dc(row) if row else None

    def list_rooms(self) -> list[Room]:
        """全部会议室。

        得到的数据：
            无。

        要做的操作：
            全表查询，按 room_id 排序（输出稳定）。

        返回：
            [Room dataclass, ...]。

        为什么：Graph Mock 拉日程与会议室列表接口都要遍历全表。
        """
        with get_session_factory()() as s:
            rows = s.scalars(select(RoomORM).order_by(RoomORM.room_id)).all()
            return [_room_dc(r) for r in rows]

    def count_rooms(self) -> int:
        """会议室数量。

        得到的数据：
            无。

        要做的操作：
            全表计数。

        返回：
            int，如 4。

        为什么：日历连接测试要展示 rooms_synced（F2.7）。
        """
        with get_session_factory()() as s:
            return len(s.scalars(select(RoomORM)).all())

    def upsert_room(self, room: Room) -> None:
        """会议室覆盖写。

        得到的数据：
            room（Room dataclass，含 room_id）。

        要做的操作：
            主键查行：不存在则插入，存在则覆盖 name/email/timezone。

        返回：
            无。

        为什么：seed 灡数据用；M3 真 M365 时由 places 同步调用。
        """
        with get_session_factory()() as s:
            row = s.get(RoomORM, room.room_id)
            if row is None:
                row = RoomORM(room_id=room.room_id)
                s.add(row)
            row.room_name = room.room_name
            row.room_email = room.room_email
            row.timezone = room.timezone
            s.commit()

    # ---------- 设备 ----------

    def get_device(self, device_id: str) -> Device | None:
        """按主键取设备行。

        得到的数据：
            device_id（设备身份，如 "SH-A3-01-01"）。

        要做的操作：
            按主键查询 device 表。

        返回：
            Device dataclass；不存在返回 None。

        为什么：认证依赖、绑定/解绑、手动干预都以"主键取行"为第一步。
        """
        with get_session_factory()() as s:
            row = s.get(DeviceORM, device_id)
            return _device_dc(row) if row else None

    def device_exists(self, device_id: str) -> bool:
        """设备是否存在。

        得到的数据：
            device_id（设备身份）。

        要做的操作：
            按主键探查，不取全行。

        返回：
            True / False。

        为什么：认证与 2001（设备不存在）判定只需要存在性，不需要整行。
        """
        with get_session_factory()() as s:
            return s.get(DeviceORM, device_id) is not None

    def get_device_by_key(self, device_key: str) -> Device | None:
        """X-Device-Key → 设备行。

        得到的数据：
            device_key（请求头里的密钥，如 "dev-key-sh-a3-01-01"）。

        要做的操作：
            按密钥唯一索引查询（device_key UNIQUE）。

        返回：
            Device dataclass；查不到返回 None（调用方转 1002）。

        为什么：设备端认证是"一个密钥一台设备"，用密钥反查而不是传 device_id 查。
        """
        with get_session_factory()() as s:
            row = s.scalars(
                select(DeviceORM).where(DeviceORM.device_key == device_key)
            ).first()
            return _device_dc(row) if row else None

    def list_all_devices(self) -> list[Device]:
        """全部设备。

        得到的数据：
            无。

        要做的操作：
            全表查询，按 device_id 排序。

        返回：
            [Device dataclass, ...]。

        为什么：调度器每 tick 要逐台跑状态机判定。
        """
        with get_session_factory()() as s:
            rows = s.scalars(select(DeviceORM).order_by(DeviceORM.device_id)).all()
            return [_device_dc(r) for r in rows]

    def list_devices(self, status: str | None, page: int, page_size: int) -> tuple[list[Device], int]:
        """设备列表分页查询（F1.3）。

        得到的数据：
            status（过滤条件，"online"/"offline"，None=不过滤）；page/page_size（页码从 1 起）。

        要做的操作：
            按 device_id 排序 → status 过滤 → 切片。

        返回：
            (本页 Device dataclass 列表, 过滤后的总数)。

        为什么：后台列表要先给 total 才能渲染分页，切片后的行直接喂 DeviceListItem。
        """
        with get_session_factory()() as s:
            query = select(DeviceORM).order_by(DeviceORM.device_id)
            if status is not None:
                query = query.where(DeviceORM.status == status)
            rows = s.scalars(query).all()
            devices = [_device_dc(r) for r in rows]
        total = len(devices)
        start = (page - 1) * page_size
        return devices[start:start + page_size], total

    def upsert_device(self, device: Device) -> None:
        """设备覆盖写。

        得到的数据：
            device（Device dataclass，含 device_id）。

        要做的操作：
            主键查行：不存在则插入，存在则经 _device_apply 逐字段覆盖。

        返回：
            无。

        为什么：seed 灡设备用；统一走 _device_apply 避免两份字段清单漂移。
        """
        with get_session_factory()() as s:
            row = s.get(DeviceORM, device.device_id)
            if row is None:
                row = DeviceORM(device_id=device.device_id)
                s.add(row)
            _device_apply(row, device)
            s.commit()

    def touch_device(self, device_id: str, agent_version: str | None = None) -> None:
        """poll 存活信号：刷 last_heartbeat，顺带记 agent_version。

        得到的数据：
            device_id（设备身份）；agent_version（可选，None=不覆盖）。

        要做的操作：
            status 置 online、last_heartbeat 刷成当前 UTC；agent_version 不为 None 才覆盖。

        返回：
            无。

        为什么：poll 与心跳都是存活信号（F1.2）；demo 版靠路由直接改内存行，
                落库后必须收口成方法才能持久化。
        """
        with get_session_factory()() as s:
            row = s.get(DeviceORM, device_id)
            if row is None:
                return
            row.status = "online"
            row.last_heartbeat = _iso_to_db(utc_now_iso())
            if agent_version is not None:
                row.agent_version = agent_version
            s.commit()

    def mark_heartbeat(self, device_id: str, device_state: str, playing: str | None, storage_used_mb: float | None) -> None:
        """心跳落库：刷新在线状态与采集字段。

        得到的数据：
            device_id（设备身份）；device_state（状态枚举，如 "IDLE"）；playing / storage_used_mb（可选，None=本次没带）。

        要做的操作：
            status 置 online、last_heartbeat 刷成当前 UTC；可选字段不为 None 才覆盖。

        返回：
            无。

        为什么：心跳是唯一在线判定信号（F1.2）；可选字段没带就保留旧值，避免误清。
        """
        with get_session_factory()() as s:
            row = s.get(DeviceORM, device_id)
            if row is None:
                return
            row.status = "online"
            row.device_state = device_state
            row.last_heartbeat = _iso_to_db(utc_now_iso())
            if playing is not None:
                row.playing = playing
            if storage_used_mb is not None:
                row.storage_used_mb = storage_used_mb
            s.commit()

    def sweep_offline(self, timeout_sec: int = 90) -> list[str]:
        """离线扫描：超时没心跳的设备标 offline。

        得到的数据：
            timeout_sec（判定阈值，默认 90 ≈ 3 次×30s 心跳间隔）。

        要做的操作：
            遍历 online 设备，算 last_heartbeat 距今的静默秒数；超过阈值 → offline。

        返回：
            本次被标记 offline 的 device_id 列表；没有则 []。

        为什么：F1.2 验收口径——连续 3 次心跳缺失（90 秒）内要反映到后台。
        """
        now = datetime.now(UTC)
        went_offline: list[str] = []
        with get_session_factory()() as s:
            rows = s.scalars(select(DeviceORM).where(DeviceORM.status == "online")).all()
            for row in rows:
                if row.last_heartbeat is None:
                    continue
                last = row.last_heartbeat.replace(tzinfo=UTC)
                if (now - last).total_seconds() > timeout_sec:
                    row.status = "offline"
                    went_offline.append(row.device_id)
            s.commit()
        return went_offline

    def room_occupant(self, room_id: str) -> str | None:
        """查询会议室当前占用的设备。

        得到的数据：
            room_id（会议室身份，如 "room-a3-01"）。

        要做的操作：
            按 room_id 查设备表第一行。

        返回：
            占用的 device_id；无人绑定返回 None。

        为什么：bind 要判定 2008（会议室已绑定其他设备）。
        """
        with get_session_factory()() as s:
            row = s.scalars(
                select(DeviceORM).where(DeviceORM.room_id == room_id)
            ).first()
            return row.device_id if row else None

    def bind_device(self, device_id: str, room_id: str) -> None:
        """写入绑定关系（前置校验由路由层做完才进来）。

        得到的数据：
            device_id（设备身份）；room_id（目标会议室）。

        要做的操作：
            device.room_id 写成 room_id。

        返回：
            无。

        为什么：绑定关系只落在 device 行一个字段上（PRD §4.6 device.room_id）。
        """
        with get_session_factory()() as s:
            row = s.get(DeviceORM, device_id)
            if row is not None:
                row.room_id = room_id
                s.commit()

    def unbind_device(self, device_id: str) -> None:
        """解除绑定关系（F1.4）。

        得到的数据：
            device_id（设备身份）。

        要做的操作：
            device.room_id 置 None。

        返回：
            无。

        为什么：解绑后设备退出该会议室的调度范围，重复解绑按幂等处理。
        """
        with get_session_factory()() as s:
            row = s.get(DeviceORM, device_id)
            if row is not None:
                row.room_id = None
                s.commit()

    def devices_in_room(self, room_id: str) -> list[Device]:
        """该会议室下的所有设备。

        得到的数据：
            room_id（会议室身份）。

        要做的操作：
            按 room_id 过滤设备表。

        返回：
            [Device dataclass, ...]；没有则 []。

        为什么：会后清理专属素材要往"这个房间的所有设备"下发 CLEAN_MATERIAL。
        """
        with get_session_factory()() as s:
            rows = s.scalars(
                select(DeviceORM).where(DeviceORM.room_id == room_id)
            ).all()
            return [_device_dc(r) for r in rows]

    # ---------- 会议 / 免登录 token ----------

    def get_meeting(self, meeting_id: str) -> Meeting | None:
        """会议行查询。

        得到的数据：
            meeting_id（业务主键，如 "meeting_123"）。

        要做的操作：
            按主键查询 meeting 表。

        返回：
            Meeting dataclass；不存在返回 None。

        为什么：上传接口要拿会议信息判断截止时间与状态（取消/结束）。
        """
        with get_session_factory()() as s:
            row = s.get(MeetingORM, meeting_id)
            return _meeting_dc(row) if row else None

    def all_meetings(self) -> list[Meeting]:
        """全部会议。

        得到的数据：
            无。

        要做的操作：
            全表查询。

        返回：
            [Meeting dataclass, ...]。

        为什么：链接生成拉取要遍历未来窗口内的所有会议。
        """
        with get_session_factory()() as s:
            rows = s.scalars(select(MeetingORM)).all()
            return [_meeting_dc(r) for r in rows]

    def upsert_meeting(self, meeting: Meeting) -> None:
        """会议同步写库（日历拉取后调用）。

        得到的数据：
            meeting（Meeting dataclass，由 calendar_source/调度测试构造）。

        要做的操作：
            按 meeting_id merge：存在则覆盖，不存在则插入。

        返回：
            无。

        为什么：日历是唯一事实源，每次拉取以它为准覆盖本地缓存，取消/改期自然同步。
        """
        with get_session_factory()() as s:
            s.merge(MeetingORM(
                meeting_id=meeting.meeting_id,
                room_id=meeting.room_id,
                subject=meeting.subject,
                organizer_email=meeting.organizer_email,
                attendees=meeting.attendees,
                start_time_utc=_iso_to_db(meeting.start_time_utc),
                end_time_utc=_iso_to_db(meeting.end_time_utc),
                timezone=meeting.timezone,
                status=meeting.status,
                is_sensitive=meeting.is_sensitive,
            ))
            s.commit()

    def meetings_of_room(self, room_id: str) -> list[Meeting]:
        """某会议室的全部会议。

        得到的数据：
            room_id（会议室身份）。

        要做的操作：
            按 room_id 过滤，按 start_time_utc 升序。

        返回：
            [Meeting dataclass, ...]；没有则 []。

        为什么：状态机要按时间顺序挑"下一场/当前这场/刚结束这场"。
        """
        with get_session_factory()() as s:
            rows = s.scalars(
                select(MeetingORM)
                .where(MeetingORM.room_id == room_id)
                .order_by(MeetingORM.start_time_utc)
            ).all()
            return [_meeting_dc(r) for r in rows]

    def get_upload_token(self, token: str) -> UploadToken | None:
        """免登录上传 token 查询。

        得到的数据：
            token（URL 里的随机串，如 "tok_demo_123"）。

        要做的操作：
            按主键查询 upload_token 表。

        返回：
            UploadToken dataclass；不存在返回 None（调用方转 1004）。

        为什么：token 是免登录通道唯一凭据，所有校验都从这一行开始。
        """
        with get_session_factory()() as s:
            row = s.get(UploadTokenORM, token)
            return _token_dc(row) if row else None

    def add_upload_token(self, token: UploadToken) -> None:
        """写入免登录 token。

        得到的数据：
            token（UploadToken dataclass，含 token 主键）。

        要做的操作：
            按 token 主键 merge（存在则覆盖，不存在则插入）。

        返回：
            无。

        为什么：调度层生成新 token 与 seed 预置都走这一个入口。
        """
        with get_session_factory()() as s:
            s.merge(UploadTokenORM(
                token=token.token,
                meeting_id=token.meeting_id,
                organizer_email=token.organizer_email,
                expire_at=_iso_to_db(token.expire_at),
                used_count=token.used_count,
                max_uses=token.max_uses,
                revoked_at=_iso_to_db(token.revoked_at),
            ))
            s.commit()

    def save_upload_token_usage(self, token: str, used_count: int) -> None:
        """回写 token 使用计数。

        得到的数据：
            token（凭据主键）；used_count（自增后的计数）。

        要做的操作：
            更新该行的 used_count。

        返回：
            无。

        为什么：上传成功后 used_count+1 必须立刻持久化，否则重启后防滥用计数清零。
        """
        with get_session_factory()() as s:
            row = s.get(UploadTokenORM, token)
            if row is not None:
                row.used_count = used_count
                s.commit()

    def token_for_meeting(self, meeting_id: str) -> UploadToken | None:
        """该会议是否已有免登录上传 token。

        得到的数据：
            meeting_id（会议业务主键）。

        要做的操作：
            按 meeting_id 查未撤销（revoked_at IS NULL）的第一条。

        返回：
            UploadToken dataclass；没有返回 None。

        为什么：链接生成拉取每 30 分钟跑一次，同一场会不能重复建 token、重复发信。
        """
        with get_session_factory()() as s:
            rows = s.scalars(
                select(UploadTokenORM)
                .where(UploadTokenORM.meeting_id == meeting_id,
                       UploadTokenORM.revoked_at.is_(None))
            ).all()
            return _token_dc(rows[0]) if rows else None

    # ---------- 账号 ----------

    def get_user_by_email(self, email: str) -> User | None:
        """按登录邮箱取用户。

        得到的数据：
            email（登录名，如 "admin@honghe.com"）。

        要做的操作：
            按邮箱唯一索引查询（统一 lower）。

        返回：
            User dataclass；不存在返回 None（登录层转 1002）。

        为什么：登录失败信息必须模糊，避免被用来枚举账号。
        """
        with get_session_factory()() as s:
            row = s.scalars(
                select(AppUserORM).where(AppUserORM.email == (email or "").lower())
            ).first()
            return _user_dc(row) if row else None

    def get_user_by_id(self, user_id: str) -> User | None:
        """按 user_id 取用户。

        得到的数据：
            user_id（用户主键，JWT sub 解出）。

        要做的操作：
            按主键查询。

        返回：
            User dataclass；不存在返回 None。

        为什么：GET /api/auth/me 身份回显按 user_id 找人。
        """
        with get_session_factory()() as s:
            row = s.get(AppUserORM, user_id)
            return _user_dc(row) if row else None

    def add_user(self, user: User) -> None:
        """写入账号。

        得到的数据：
            user（User dataclass，password_hash/salt 已派生）。

        要做的操作：
            主键已存在则静默跳过（seed 幂等），否则插入（email 统一 lower）。

        返回：
            无。

        为什么：seed 可重复执行，重复灌账号必须无害。
        """
        with get_session_factory()() as s:
            if s.get(AppUserORM, user.user_id) is not None:
                return
            s.add(AppUserORM(
                user_id=user.user_id, email=user.email.lower(), name=user.name,
                role=user.role, password_hash=user.password_hash, salt=user.salt,
            ))
            s.commit()

    # ---------- 调度层：指令去重 ----------

    def has_command(self, device_id: str, type_: str, meeting_id: str) -> bool:
        """该设备是否已为某场会下发过某类指令（调度去重）。

        得到的数据：
            device_id（目标设备）；type_（指令类型，如 "PREPARE_MEETING"）；
            meeting_id（payload 里的会议 id）。

        要做的操作：
            按设备+类型查指令，再比对 payload.meeting_id（payload 是 JSON，小规模 Python 过滤最清晰）。

        返回：
            True（已下发过）/ False（没发过）。

        为什么：调度器每 60/300 秒跑一次，同一条指令不能重复入队（幂等的要求）。
        """
        with get_session_factory()() as s:
            rows = s.scalars(
                select(CommandORM)
                .where(CommandORM.device_id == device_id, CommandORM.type == type_)
            ).all()
            return any((r.payload or {}).get("meeting_id") == meeting_id for r in rows)

    # ---------- 素材 ----------

    def add_material(self, material: Material) -> Material:
        """素材落库。

        得到的数据：
            material（已填好 id/name/format/size/url/scope 的 Material dataclass）。

        要做的操作：
            按主键 merge 覆盖写。

        返回：
            同一个 Material dataclass。

        为什么：上传成功必须立刻可按 id 查到，删除/列表都依赖这份索引。
        """
        with get_session_factory()() as s:
            s.merge(MaterialORM(
                material_id=material.material_id,
                name=material.name,
                format=material.format,
                url=material.url,
                file_path=material.file_path or None,
                size_mb=material.size_mb,
                scope=material.scope,
                meeting_id=material.meeting_id,
                category=material.category,
                tags=material.tags,
                uploaded_by=material.uploaded_by,
                expire_at=_iso_to_db(material.expire_at),
                created_at=_iso_to_db(material.created_at),
                last_used_at=_iso_to_db(material.last_used_at),
            ))
            s.commit()
        return material

    def get_material(self, material_id: str) -> Material | None:
        """按 id 取素材。

        得到的数据：
            material_id（如 "mat_001"）。

        要做的操作：
            按主键查询 material 表。

        返回：
            Material dataclass；不存在返回 None（调用方转 2004）。

        为什么：删除与后续 CLEAN_MATERIAL 都要先拿到素材本体。
        """
        with get_session_factory()() as s:
            row = s.get(MaterialORM, material_id)
            return _material_dc(row) if row else None

    def all_materials(self) -> list[Material]:
        """全部素材。

        得到的数据：
            无。

        要做的操作：
            全表查询。

        返回：
            [Material dataclass, ...]。

        为什么：设备预拉取清单要从全量素材里按规则挑选。
        """
        with get_session_factory()() as s:
            rows = s.scalars(select(MaterialORM)).all()
            return [_material_dc(r) for r in rows]

    def meeting_materials(self, meeting_id: str) -> list[Material]:
        """某场会的专属素材。

        得到的数据：
            meeting_id（会议业务主键）。

        要做的操作：
            按 scope=meeting + meeting_id 过滤。

        返回：
            [Material dataclass, ...]；没有则 []。

        为什么：上传页"已传列表"要只显示本场会的文件，避免重复上传。
        """
        with get_session_factory()() as s:
            rows = s.scalars(
                select(MaterialORM)
                .where(MaterialORM.scope == "meeting",
                       MaterialORM.meeting_id == meeting_id)
            ).all()
            return [_material_dc(r) for r in rows]

    def list_materials(self, scope: str | None, meeting_id: str | None, page: int, page_size: int, tag: str | None = None, category: str | None = None) -> tuple[list[Material], int]:
        """素材列表分页（F4.2）。

        得到的数据：
            scope（public/meeting，None=不过滤）；meeting_id（指定会议）；tag（自由标签）；
            category（业务分类）；page/page_size。

        要做的操作：
            created_at 倒序 → scope/meeting_id/category 库内过滤 → tag 内存过滤 → 切片。

        返回：
            (本页 Material dataclass 列表, 过滤后总数)。

        为什么：素材库页面按"最近上传"排序最符合运营心智，tag/category 是两级筛选。
        """
        with get_session_factory()() as s:
            query = select(MaterialORM)
            if scope is not None:
                query = query.where(MaterialORM.scope == scope)
            if meeting_id is not None:
                query = query.where(MaterialORM.meeting_id == meeting_id)
            if category is not None:
                query = query.where(MaterialORM.category == category)
            rows = s.scalars(query.order_by(MaterialORM.created_at.desc())).all()
        materials = [_material_dc(r) for r in rows if tag is None or tag in (r.tags or [])]
        total = len(materials)
        start = (page - 1) * page_size
        return materials[start:start + page_size], total

    def expired_meeting_materials(self, now_iso: str) -> list[Material]:
        """已过期的会议专属素材（F4.8 会后清理的依据）。

        得到的数据：
            now_iso（当前 UTC 时间串）。

        要做的操作：
            筛 scope=meeting 且 expire_at 非空且 ≤ now 的素材。

        返回：
            [Material dataclass, ...]（为空表示没有待清理的）。

        为什么：专属素材只靠设备 LRU 会残留，服务端必须按到期时间主动清理。
        """
        cutoff = _iso_to_db(now_iso)
        with get_session_factory()() as s:
            rows = s.scalars(
                select(MaterialORM)
                .where(MaterialORM.scope == "meeting",
                       MaterialORM.expire_at.is_not(None),
                       MaterialORM.expire_at <= cutoff)
            ).all()
            return [_material_dc(r) for r in rows]

    def delete_material(self, material_id: str) -> Material | None:
        """删除素材记录（物理删，评审决策 #5）。

        得到的数据：
            material_id（如 "mat_001"）。

        要做的操作：
            主键取行 → 记下 dataclass → 物理删除该行。

        返回：
            被删的 Material dataclass；不存在返回 None（调用方转 2004）。

        为什么：删完还要用返回的 scope/meeting_id 决定是否下发 CLEAN_MATERIAL。
        """
        removed: Material | None = None
        with get_session_factory()() as s:
            row = s.get(MaterialORM, material_id)
            if row is not None:
                removed = _material_dc(row)
                s.delete(row)
                s.commit()
        return removed

    def material_quota(self) -> tuple[int, float]:
        """素材库当前占用。

        得到的数据：
            无。

        要做的操作：
            统计素材条数与总大小。

        返回：
            (条数, 总 MB)，如 (32, 128.6)。

        为什么：2011 配额校验要数量与容量两个口径（规范 §1.2）。
        """
        with get_session_factory()() as s:
            rows = s.scalars(select(MaterialORM)).all()
            total_mb = sum(r.size_mb for r in rows)
            return len(rows), round(total_mb, 2)

    # ---------- 指令审计 ----------

    def list_commands(self, device_id: str | None, initiated_by: str | None, page: int, page_size: int) -> tuple[list[Command], int]:
        """指令审计记录分页（F7.1 / F8.3）。

        得到的数据：
            device_id（只看某台设备，None=不过滤）；initiated_by（只看某触发方）；page/page_size。

        要做的操作：
            created_at 倒序 → 两条件过滤 → 切片。

        返回：
            (本页 Command dataclass 列表, 过滤后总数)。

        为什么：运维排查"这条指令是谁、什么时候发的"全靠这份可过滤的审计流。
        """
        with get_session_factory()() as s:
            query = select(CommandORM)
            if device_id is not None:
                query = query.where(CommandORM.device_id == device_id)
            if initiated_by is not None:
                query = query.where(CommandORM.initiated_by == initiated_by)
            rows = s.scalars(query.order_by(CommandORM.created_at.desc())).all()
            commands = [_command_dc(r) for r in rows]
        total = len(commands)
        start = (page - 1) * page_size
        return commands[start:start + page_size], total

    def all_commands(self) -> list[Command]:
        """全部指令。

        得到的数据：
            无。

        要做的操作：
            全表查询。

        返回：
            [Command dataclass, ...]。

        为什么：冒烟脚本要全量断言指令状态；生产审计请走 list_commands 分页。
        """
        with get_session_factory()() as s:
            rows = s.scalars(select(CommandORM)).all()
            return [_command_dc(r) for r in rows]

    # ---------- 指令队列 ----------

    def enqueue_command(self, device_id: str, type_: str, payload: dict, initiated_by: str = "system") -> Command:
        """指令入队。

        得到的数据：
            device_id（目标设备）；type_（指令类型）；payload（指令参数 dict）；
            initiated_by（触发方，审计必埋，默认 "system"）。

        要做的操作：
            生成 command_id（cmd_ + uuid 前 12 位）和 checksum；
            组 Command 行，status 置 PENDING、记 created_at，落库。

        返回：
            Command dataclass（status=PENDING）。

        为什么：command_id 是幂等键，checksum 供设备端校验指令未被篡改；
                "pending 队列"不再是内存 list——PENDING 状态本身就是队列。
        """
        command_id = f"cmd_{uuid.uuid4().hex[:12]}"
        raw = command_id + json.dumps(payload, sort_keys=True, ensure_ascii=False)
        checksum = "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
        command = Command(
            command_id=command_id,
            device_id=device_id,
            type=type_,
            payload=payload,
            initiated_by=initiated_by,
            created_at=utc_now_iso(),
            checksum=checksum,
        )
        with get_session_factory()() as s:
            s.add(CommandORM(
                command_id=command.command_id,
                device_id=command.device_id,
                type=command.type,
                payload=command.payload,
                status="PENDING",
                initiated_by=command.initiated_by,
                checksum=command.checksum,
                created_at=_iso_to_db(command.created_at),
            ))
            s.commit()
        return command

    def pop_pending_command(self, device_id: str) -> Command | None:
        """取出该设备最早一条待执行指令并标 SENT。

        得到的数据：
            device_id（设备身份）。

        要做的操作：
            查该设备最早的 PENDING 指令（created_at 升序 = FIFO 语义）；
            取到 → status 置 SENT、记 sent_at。

        返回：
            Command dataclass（已标 SENT）；队列空返回 None（poll 层继续 hold）。

        为什么：FIFO 保证先入队先执行；PENDING 状态即队列，重启后未取走的指令照样在。
        """
        with get_session_factory()() as s:
            row = s.scalars(
                select(CommandORM)
                .where(CommandORM.device_id == device_id,
                       CommandORM.status == "PENDING")
                .order_by(CommandORM.created_at.asc())
                .limit(1)
            ).first()
            if row is None:
                return None
            row.status = "SENT"
            row.sent_at = _iso_to_db(utc_now_iso())
            s.commit()
            return _command_dc(row)

    def ack_command(self, command_id: str, status: str, device_state: str | None) -> Command | None:
        """设备回执落库：SENT → ACKED / FAILED。

        得到的数据：
            command_id（要回执的指令）；status（"SUCCESS"/"FAILED"）；
            device_state（可选，设备执行后回传的状态）。

        要做的操作：
            command.status 改成 ACKED/FAILED 并记 acked_at；
            device_state 不为 None 时同步到设备行。

        返回：
            Command dataclass（已更新）；command_id 不存在返回 None（路由层转 2004）。

        为什么：指令审计要求每条指令有终态和回执时间（F7.1），重试判定也靠它。
        """
        with get_session_factory()() as s:
            row = s.get(CommandORM, command_id)
            if row is None:
                return None
            row.status = "ACKED" if status == "SUCCESS" else "FAILED"
            row.acked_at = _iso_to_db(utc_now_iso())
            command = _command_dc(row)
            if device_state is not None:
                device = s.get(DeviceORM, row.device_id)
                if device is not None:
                    device.device_state = device_state
            s.commit()
            return command

    # ---------- 日历源配置 ----------

    @property
    def calendar_config(self) -> CalendarConfig:
        """日历源配置快照。

        得到的数据：
            无（读 calendar_config 单行，id=1，不存在自动建默认行）。

        要做的操作：
            主键读行 → _config_dc 补齐只读字段。

        返回：
            CalendarConfig dataclass（字段全集快照）。

        为什么：路由读 cfg.xxx 的写法不用改；但对快照赋值不会持久化，
                保存必须走 save_calendar_config。
        """
        with get_session_factory()() as s:
            row = s.get(CalendarConfigORM, 1)
            if row is None:
                row = CalendarConfigORM(id=1)
                s.add(row)
                s.commit()
                s.refresh(row)
            return _config_dc(row)

    def save_calendar_config(self, provider: str, tenant: str | None, service_account: str | None,
                             pull_policy: dict, alert_email: str | None) -> None:
        """保存日历源配置（PUT /api/admin/calendar/config）。

        得到的数据：
            provider/tenant/service_account（接入身份）；pull_policy（前端策略 dict）；
            alert_email（告警收件人）。

        要做的操作：
            白名单字段覆盖写；scopes/connection_status 服务端固定不碰。

        返回：
            无。

        为什么：只允许开关/周期/告警邮箱可改，权限范围一旦放开就有越权风险（规范 §6.2）。
        """
        schedule = pull_policy.get("schedule", {})
        link_gen = pull_policy.get("link_gen", {})
        with get_session_factory()() as s:
            row = s.get(CalendarConfigORM, 1)
            if row is None:
                row = CalendarConfigORM(id=1)
                s.add(row)
            row.provider = provider
            row.tenant = tenant
            row.service_account = service_account
            row.pull_schedule_min = int(schedule.get("interval_min", 5))
            row.pull_link_gen_min = int(link_gen.get("interval_min", 30))
            row.link_window_days = int(link_gen.get("window_days", 7))
            row.dst_enabled = bool(pull_policy.get("dst_enabled", True))
            row.alert_email = alert_email
            s.commit()


# ---- 种子数据（开发/联调：幂等——已灌过就跳过，重启不重灌） ----

def seed(store: Store) -> None:
    """灌演示种子数据（开发/联调用，幂等）。

    得到的数据：
        store（持久化存储门面单例）。

    要做的操作：
        幂等闸门：room-a3-01 已存在 → 直接返回；
        建 4 间会议室（上海两间 + 巴塞罗那 + 纽约）、设备 3 台（已绑/未绑/常驻离线）；
        从 calendar_source fixture 生成会议（唯一数据源）并建 3 个上传 token；
        建 1 条公共素材、2 个账号；
        不预置指令——PREPARE_MEETING 交给 scheduler 按日历生成。

    返回：
        无。

    为什么：服务一启动就有真实数据可联调；幂等化后 fixture 锚点稳定，
            上传 token 的 95 分钟余量不会因重启无限续期。
    """
    if store.get_room("room-a3-01") is not None:
        return

    rooms = [
        Room(room_id="room-a3-01", room_name="Room-A3-01 · 上海总部 3F", room_email="room-a3-01@honghe.com"),
        Room(room_id="room-b2-05", room_name="Room-B2-05 · 上海总部 2F", room_email="room-b2-05@honghe.com"),
        Room(room_id="room-bcn-01", room_name="Room-BCN-01 · 巴塞罗那", room_email="room-bcn-01@honghe.com", timezone="Europe/Madrid"),
        Room(room_id="room-ny-01", room_name="Room-NY-01 · 纽约", room_email="room-ny-01@honghe.com", timezone="America/New_York"),
    ]
    for room in rooms:
        store.upsert_room(room)

    demo_device = Device(
        device_id="SH-A3-01-01",
        device_key="dev-key-sh-a3-01-01",   # 演示密钥（见 DEVICE_APP.md），生产版改为绑定时服务端签发+落库
        device_name="device_sh_003",
        room_id="room-a3-01",
    )
    store.upsert_device(demo_device)

    spare_device = Device(
        device_id="SH-A3-01-02",
        device_key="dev-key-sh-a3-01-02",   # 第二台：未绑定，供 bind/unbind 联调
        device_name="device_sh_004",
    )
    store.upsert_device(spare_device)

    # 第三台：从未心跳，永远 offline —— 给 2009（设备离线，指令入队）留稳定用例
    offline_device = Device(
        device_id="SH-A3-01-03",
        device_key="dev-key-sh-a3-01-03",
        device_name="device_sh_005",
    )
    store.upsert_device(offline_device)

    # 会议只从日历源来（唯一事实源）：fixture 生成 → 写成 Meeting 行
    # 这样"上传页看到的会"和"调度器下指令的会"永远是同一批，不会出现两套数据对不上
    events = fixture_events()
    for event in events:
        store.upsert_meeting(Meeting(
            meeting_id=event["meeting_id"],
            room_id=event["room_id"],
            subject=event["subject"],
            organizer_email=event["organizer_email"],
            attendees=event.get("attendees", []),
            start_time_utc=event["start_time_utc"],
            end_time_utc=event["end_time_utc"],
            timezone=event["timezone"],
            status=event["status"],
            is_sensitive=is_sensitive(event["subject"]),
        ))

    # 上传 token 绑到 fixture 的会议：
    #   ① A3 第二场（95 分钟后开）→ 上传截止还有余量，用于验证"能正常上传"
    #   ② B2 那场（已开始）→ 上传截止已过，用于验证 2006
    a3_events = [e for e in events if e["room_id"] == "room-a3-01"]
    a3_uploadable = a3_events[-1]
    b2_started = next(e for e in events if e["room_id"] == "room-b2-05")
    now = utc_now_iso()
    store.add_upload_token(UploadToken(
        token="tok_demo_123",
        meeting_id=a3_uploadable["meeting_id"],
        organizer_email=a3_uploadable["organizer_email"],
        expire_at=a3_uploadable["end_time_utc"],
    ))
    store.add_upload_token(UploadToken(
        token="tok_demo_started",
        meeting_id=b2_started["meeting_id"],
        organizer_email=b2_started["organizer_email"],
        expire_at=b2_started["end_time_utc"],
    ))
    store.add_upload_token(UploadToken(
        token="tok_demo_revoked",
        meeting_id=a3_uploadable["meeting_id"],
        organizer_email=a3_uploadable["organizer_email"],
        expire_at=a3_uploadable["end_time_utc"],
        revoked_at=now,
    ))

    # 一条公共素材（列表页不至于空，删除接口有对象可测）
    store.add_material(Material(
        material_id="mat_001",
        name="brand-default.png",
        format="png",
        size_mb=2.4,
        url=f"{PUBLIC_BASE}/media/mat_001.png",
        scope="public",
        category="brand",
        tags=["brand"],
        uploaded_by="admin:admin_001",
        created_at=now,
        last_used_at=now,
    ))

    # 账号种子（F8.1/F8.2：管理员 + 普通用户）
    admin = make_user("admin_001", "admin@honghe.com", "管理员", "admin", "admin123")
    ops = make_user("user_001", "ops@honghe.com", "运营小王", "user", "ops123")
    store.add_user(admin)
    store.add_user(ops)

    # 触发日历配置默认行（id=1）落库
    _ = store.calendar_config


store = Store()
