# 05 · 数据模型 SQL 化评审 — Newline MeetCast（M0 交付物）

> **定位**：PRD §4.6 的字段草图 → 正式 SQL 模型的**评审稿**。你逐条拍板后，M1 动工照稿落进 `server/app/models/` + Alembic。
> **评审方式**：第四节"决策点清单"是要你拍板的 9 个问题；其余为建议默认值，不同意单独说。
> **状态**：待评审（2026-10-28 起草）

---

## 一、表清单（10 张，与 API Spec v1.0 对齐）

| 表 | 职责 | 关键约束 |
| --- | --- | --- |
| `room` | 会议室（含房间邮箱与时区） | room_email UNIQUE |
| `device` | 设备 + 最后已知状态 | device_key UNIQUE |
| `command` | 指令队列（**唯一事实源**） | PK=command_id 幂等键 |
| `meeting` | 日历会议缓存 | (room_id, start_time_utc) 复合索引 |
| `upload_token` | 免登录上传凭据 | PK=token |
| `material` | 素材（公共/专属双轨） | (scope, meeting_id) 过滤索引 |
| `material_vector` | 素材向量元数据（向量本体在 Milvus） | 1:1 material |
| `kb_document` | 品牌知识库文档 | status 状态机 |
| `app_user` | 后台账号 | email UNIQUE |
| `calendar_config` | 日历源配置（单行表） | 全局一行 |

> 相比 PRD 草图新增 `calendar_config`：原草图没落位，但 API Spec §6.1/6.2 有 config 读写接口——配置必须持久化（否则重启丢 alert_email/pull_policy），单行表最简。

---

## 二、全量 SQLAlchemy 2.0 模型（评审稿正文）

```python
# server/app/models/base.py
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """唯一登记处：所有模型必须 import 此 Base（幽灵表防线）。"""

# server/app/models/__init__.py —— 全部串起来，漏 import = Alembic 看不见
from app.models.base import Base
from app.models import (room, device, command, meeting,
                        upload_token, material, material_vector,
                        kb_document, app_user, calendar_config)
```

```python
# server/app/models/room.py
from datetime import datetime
from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class Room(Base):
    __tablename__ = "room"

    room_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    room_name: Mapped[str] = mapped_column(String(128))
    room_email: Mapped[str] = mapped_column(String(255), unique=True)   # 房间邮箱，M365 轮询的锚点
    building: Mapped[str | None] = mapped_column(String(128))
    floor: Mapped[str | None] = mapped_column(String(32))
    capacity: Mapped[int | None] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64))                    # IANA 名，DST 全靠它
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

```python
# server/app/models/device.py
class Device(Base):
    __tablename__ = "device"

    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_name: Mapped[str | None] = mapped_column(String(128))
    device_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)  # 认证锚点，唯一
    room_id: Mapped[str | None] = mapped_column(ForeignKey("room.room_id"))        # NULL=未绑定
    status: Mapped[str] = mapped_column(String(16), default="offline")             # online/offline，应用层校验
    device_state: Mapped[str | None] = mapped_column(String(16))                   # 四态：最后已知状态
    playing: Mapped[str | None] = mapped_column(String(255))                       # 最后上报的播放内容
    agent_version: Mapped[str | None] = mapped_column(String(32))
    storage_used_mb: Mapped[int | None] = mapped_column(Integer)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

```python
# server/app/models/command.py
class Command(Base):
    __tablename__ = "command"

    command_id: Mapped[str] = mapped_column(String(32), primary_key=True)   # cmd_<uuid12>，幂等键
    device_id: Mapped[str] = mapped_column(
        ForeignKey("device.device_id"), index=True)
    type: Mapped[str] = mapped_column(String(32))        # PREPARE_MEETING/SWITCH_CONTENT/REPLAY_DEFAULT/...
    payload: Mapped[dict] = mapped_column(JSON)          # PG 上是 JSONB，SQLite 上退化 TEXT（单测兼容）
    status: Mapped[str] = mapped_column(
        String(16), default="PENDING")                   # PENDING→SENT→ACKED/FAILED/TIMEOUT
    initiated_by: Mapped[str] = mapped_column(String(64))  # 审计必埋（F8.3）
    checksum: Mapped[str] = mapped_column(String(80))      # sha256(cmd_id+payload)，防篡改
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), index=True)                             # 审计流按时间倒序查
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_command_device_status", "device_id", "status"),   # poll 取 PENDING 的主查询路径
    )
```

```python
# server/app/models/meeting.py
class Meeting(Base):
    __tablename__ = "meeting"

    meeting_id: Mapped[str] = mapped_column(String(128), primary_key=True)  # 日历事件 id，覆盖写主键
    room_id: Mapped[str] = mapped_column(ForeignKey("room.room_id"))
    subject: Mapped[str] = mapped_column(String(255))
    organizer_email: Mapped[str] = mapped_column(String(255))
    start_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="scheduled")    # scheduled/cancelled/ended
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)      # 同步时就判定落库（不重复判）
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now())                     # 每次同步覆盖写都有痕

    __table_args__ = (
        Index("ix_meeting_room_start", "room_id", "start_time_utc"),  # 状态机每 tick 按 room 扫会议
    )
```

```python
# server/app/models/upload_token.py
class UploadToken(Base):
    __tablename__ = "upload_token"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)   # tok_<urlsafe>
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meeting.meeting_id"), index=True)
    organizer_email: Mapped[str] = mapped_column(String(255))          # 审计归属
    expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    max_uses: Mapped[int] = mapped_column(Integer, default=50)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

```python
# server/app/models/material.py
class Material(Base):
    __tablename__ = "material"

    material_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # mat_<uuid8>
    name: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(8))
    url: Mapped[str] = mapped_column(String(512))
    file_path: Mapped[str | None] = mapped_column(String(512))       # 本地落盘路径；OSS 托管时 NULL
    size_mb: Mapped[float] = mapped_column(Float)
    scope: Mapped[str] = mapped_column(String(8))                    # public/meeting（应用层校验）
    meeting_id: Mapped[str | None] = mapped_column(ForeignKey("meeting.meeting_id"))
    category: Mapped[str] = mapped_column(String(16), default="other")
    tags: Mapped[list] = mapped_column(JSON, default=list)           # 自由标签数组
    uploaded_by: Mapped[str] = mapped_column(String(64))             # initiated_by 同款枚举
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)  # 到期清理扫描
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)      # 15 天 LRU 依据
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_material_scope_meeting", "scope", "meeting_id"),   # 设备拉素材清单的主查询
    )
```

```python
# server/app/models/material_vector.py
class MaterialVector(Base):
    __tablename__ = "material_vector"

    material_id: Mapped[str] = mapped_column(
        ForeignKey("material.material_id", ondelete="CASCADE"), primary_key=True)
    milvus_pk: Mapped[str] = mapped_column(String(64))     # Milvus 主键，删向量时定位
    embedding_model: Mapped[str] = mapped_column(String(64))   # 维度/模型变更时可定位需重嵌的行
    embedded_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # 状态语义：本表有行=已向量化；无行=待补向量（2013 可重试的落点）
```

```python
# server/app/models/kb_document.py
class KbDocument(Base):
    __tablename__ = "kb_document"

    doc_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    source_uri: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="parsing")  # parsing/embedding/ready/failed
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    embedding_model: Mapped[str | None] = mapped_column(String(64))
    uploaded_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

```python
# server/app/models/app_user.py
class AppUser(Base):
    __tablename__ = "app_user"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))              # admin/user，应用层 VALID_ROLES 校验
    password_hash: Mapped[str] = mapped_column(String(128))
    salt: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

```python
# server/app/models/calendar_config.py —— 单行表（id=1 恒定）
class CalendarConfig(Base):
    __tablename__ = "calendar_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    provider: Mapped[str] = mapped_column(String(16), default="m365")
    tenant: Mapped[str | None] = mapped_column(String(255))
    service_account: Mapped[str | None] = mapped_column(String(255))
    pull_schedule_min: Mapped[int] = mapped_column(Integer, default=5)     # 编排拉取周期
    pull_link_gen_min: Mapped[int] = mapped_column(Integer, default=30)    # 链接生成周期
    link_window_days: Mapped[int] = mapped_column(Integer, default=7)
    dst_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_email: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now())
    # 凭据（tenant_id/client_id/secret）永不入库——只存 .env，防"一个 SQL 注入拖走租户凭据"
```

---

## 三、Alembic 0001 策略

- **0001_initial 用 `Base.metadata.create_all` + 空库校验**（PrismEdu D8 同款）：不手写 10 张表 DDL，模型即迁移零漂移；执行前检查库里已存在业务表则报错拒绝
- **0002 起改 autogenerate diff**，手写只做微调
- engine 惰性单例：import 零副作用（PrismEdu D9 同款，避免"跑个单测也要连 PG"）

---

## 四、决策点清单（要你拍板的 9 个）

| # | 决策点 | 建议方案 | 理由 / 备选 |
| --- | --- | --- | --- |
| 1 | 枚举策略（role/status/scope） | **String + 应用层 VALID 常量校验** | PG ENUM 加值要 ALTER TYPE 且 SQLite 不一致；应用层校验跨库可移植（PrismEdu D3 同款）。备选：PG CHECK 约束兜底一层 |
| 2 | `command.payload` 类型 | **SQLAlchemy JSON**（PG=JSONB，SQLite=TEXT） | 单测用 SQLite 内存库不依赖 Docker；payload 是"设备读的文档"非查询键，不需要 JSONB 索引 |
| 3 | 设备删除语义 | **物理不删**：解绑置 room_id=NULL，下线置 status=offline | 指令审计引用 device_id，物理删会断审计链；无"注销设备"的 P0 需求 |
| 4 | meeting 覆盖写 vs 事件追加 | **覆盖写**（PK=日历事件 id，updated_at 留痕） | sync_calendar 每轮全量对齐，追加会产生僵尸行；完整变更史二期再加 event_log |
| 5 | material 删除 | **物理删 + 双侧清理**（文件/Milvus 向量/CLEAN_MATERIAL 同步） | 素材有实体文件，软删会白占盘；LRU/expire 反正要物理清 |
| 6 | material_vector 用 1:1 附属表 | **有行=已向量化，无行=待补** | 把"2013 可重试"变成一次 JOIN 判断，不需要额外 status 列 |
| 7 | calendar_config 单行表 vs 存 .env | **单行表**（凭据仍留 .env） | API §6.2 要求运行时可改告警邮箱/拉取周期，改 .env 要重启；凭据永不入库是安全红线 |
| 8 | tags 用 JSON 数组还是标签关联表 | **JSON 数组** | 标签是运营自由打的，无聚合统计需求；真要"按标签多维分析"时再迁移（JSON→关联表迁移成本低） |
| 9 | 密码列长度与算法 | **本期维持 PBKDF2 12 万次，hash 列开 128 长度** | 换 argon2/bcrypt 时列不用动（hash 串自描述）；迭代次数提升列入 M1 债务账本 |

---

## 五、与 PRD §4.6 草图的差异说明

| 变化 | 原因 |
| --- | --- |
| +`calendar_config` 表 | config 接口需要持久化落位（草图漏了） |
| +`material_vector` 表 | 向量元数据落位，2013 重试的判定载体（草图漏了） |
| device +`device_state/playing/agent_version/storage_used_mb` | 心跳上报的落库字段（草图只有心跳时间） |
| command +`checksum/retry_count` | API Spec 已定义，草图漏了 |
| meeting +`updated_at` | 覆盖写策略的可观测性要求 |

---

## 六、评审通过后的动作（M1 第一步）

1. 按拍板结果落 `server/app/models/` + `alembic init` + `0001_initial`
2. store.py 改造为 SQLAlchemy 会话读写（收口不变，路由层零改动）
3. seed() 幂等化（存在即跳过）——债务账本 #3 一并销账
4. 全部接口回归冒烟（12 套脚本平移）
