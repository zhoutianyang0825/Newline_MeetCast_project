# Newline MeetCast 接口规范

**文档名称**：API 接口规范（前后端单一事实源）
**版本**：v1.0（生产级）
**日期**：2026-10-28
**负责人**：周天扬
**依据**：Newline_MeetCast_PRD.md v1.0（设备端协议复用 §4.5，业务接口按 F1~F8 展开）
**状态**：定稿；M0 交付物，M1 起照此实施
**变更记录**：
- v1.0（本次）：对齐 PRD v1.0 生产级重写。①**新增 6 个接口**：§4.4 素材语义检索（F4.5 升 P0）、§4.5~4.7 品牌知识库管理 3 个（F4.9 新增 P0）、§7.3/7.4 会议页内容预览与编辑（F5.6 升 P0），接口总数 **22 → 28**；②§九 技术栈定稿更新：RAG 向量库由 pgvector 改 **Milvus**、**CrewAI 转正**（文案 crew）、**LangGraph 升主编排**（调度 pipeline 状态图）、新增 Redis（长轮询唤醒/缓存）；③通用约定补持久化与多实例口径；④删除全部"4 天交付"表述，开发顺序对齐里程碑 M1~M7
- 历史（v0.1~v0.4）：统一返回壳/错误码表、设备端 6 接口、管理端 11 接口、免登录 2 接口、登录 2 接口、会议室二维码、素材 category、checksum 采样——契约继续有效

> **定位**：本文件是前后端唯一契约。**改接口先改本文件，再让 AI 同步改前后端代码**——不许代码先行、文档追认。

---

## 一、通用约定

| 约定项 | 规则 |
| --- | --- |
| Base URL | `https://<host>/api`（开发期 `http://localhost:8000/api`） |
| 风格 | REST；路径全小写、中划线；字段 `snake_case` |
| 时间 | 一律 UTC ISO 8601（如 `2026-10-28T02:00:00Z`）；随行字段 `timezone`（IANA 名）供前端本地化 |
| 认证 | 设备端：`X-Device-Key` 头；管理端：`Authorization: Bearer <JWT>`；免登录：URL 中 `{token}` |
| 内容类型 | `application/json`；文件上传 `multipart/form-data` |
| 幂等 | 设备指令靠 `command_id`；写接口可选传 `request_id` 防重 |
| 持久化 | 全部业务数据落 **PostgreSQL**（Alembic 迁移）；重启不丢；`command` 表为指令队列唯一事实源 |
| 多实例 | 写接口天然无状态可横向扩；调度图（LangGraph）由 Redis 分布式锁保证单实例执行 |

### 1.1 统一返回结构

```json
{ "code": 0, "message": "ok", "data": { } }
```

- `code=0` 成功；非 0 为错误，`message` 给人看，`data` 出错时为 null
- 列表类：`data = { "items": [...], "total": 12, "page": 1, "page_size": 20 }`

### 1.2 全局错误码

| code | 含义 | 触发场景 |
| --- | --- | --- |
| 0 | 成功 | — |
| 1001 | 参数校验失败 | 缺字段/类型错 |
| 1002 | 未认证 | 无密钥/JWT 过期 |
| 1003 | 无权限 | 普通用户调管理员接口 |
| 1004 | token 无效 | 免登录链接失效/过期/超额 |
| 2001 | 设备不存在 | device_id 未注册 |
| 2002 | 设备已绑定 | 换绑需先解绑（或传 `force=true`） |
| 2003 | 会议室不存在 | room_id 非法 |
| 2004 | 素材不存在 | material_id 非法 |
| 2005 | 格式不支持 | 冷门格式，明确拒绝不静默失败（F4.1） |
| 2006 | 上传已截止 | 超过会前 30 分钟（F2.4） |
| 2007 | 文件超限 | 单文件 > 500MB |
| 2008 | 会议室已绑定其他设备 | bind 时该 room 已有在绑设备 |
| 2009 | 设备离线 | 指令下发/手动干预时设备离线（入队 PENDING，上线后重试） |
| 2010 | 会议不存在或已取消 | 免登录 token 对应会议被取消/改期 |
| 2011 | 素材配额超限 | 素材库总容量或数量超上限 |
| 2012 | 知识库文档不存在 | doc_id 非法（v1.0 新增） |
| 2013 | 向量化失败 | embedding 服务不可用/超时（v1.0 新增；素材/文档本体已保存，仅向量缺失，可重试） |
| 3001 | 日历源凭证失效 | Graph token 过期（F2.6） |
| 3002 | 日历 API 超限 | 429 限流 |
| 4001 | 指令下发超时 | 重试超限仍无 ACK（F7.2，触发告警） |
| 5000 | 服务内部错误 | 兜底 |

---

## 二、设备端接口（6 个，X-Device-Key 认证）

> 与 PRD §4.5 一致。设备主动长轮询，不开放服务器端口。一期 macOS App 与二期 Android APK 使用完全相同的契约。

### 2.1 POST /api/device/poll — 长轮询取指令

hold 连接至有指令或超时（建议 25s）；有指令立即返回，超时返回空。服务端以 Redis pub/sub 唤醒 hold 中的连接（指令入队到设备取走 ≤5 秒）。

**入参**：

```json
{ "device_id": "SH-A3-01-01", "agent_version": "1.0.0" }
```

**返回**（有指令）：

```json
{
  "code": 0,
  "data": {
    "command_id": "cmd_9f3a…",
    "type": "PREPARE_MEETING",
    "payload": {
      "content_url": "https://meetcast.app/c/meeting_123",
      "meeting_id": "meeting_123",
      "prepare_at": "2026-10-28T01:50:00Z",
      "switch_at": "2026-10-28T01:59:00Z",
      "timezone": "Asia/Shanghai",
      "until": "2026-10-28T03:00:00Z"
    },
    "initiated_by": "system",
    "checksum": "sha256:…"
  }
}
```

**返回**（无指令）：`{ "code": 0, "data": { "command_id": null } }`

**错误**：1002 密钥错｜2001 设备不存在

### 2.2 POST /api/device/ack — 指令回执

**入参**：

```json
{ "command_id": "cmd_9f3a…", "status": "SUCCESS", "device_state": "MEETING" }
```

**返回**：`{ "code": 0, "data": null }`

**错误**：1001（status 只允许 `SUCCESS|FAILED`）｜2004 command_id 不存在

### 2.3 POST /api/device/heartbeat — 心跳上报

每 30s 一次；仅在线判定与状态采集，不承担指令下发。连续 3 次缺失 → 标记 offline（F1.2）。

**入参**：

```json
{ "device_id": "SH-A3-01-01", "device_state": "IDLE", "playing": "signage_default", "storage_used_mb": 34200 }
```

**返回**：`{ "code": 0, "data": { "server_time_utc": "2026-10-28T04:26:12Z" } }`

**错误**：1002 密钥错｜2001 设备不存在

### 2.4 GET /api/device/profile — 设备档案（F1.1 设备侧）

设备开机自检：我是谁、有没有绑定会议室、服务器几点。绑定动作在管理端（§3.2），设备侧只"问一句我现在什么状态"。

**入参**：无（设备身份由 `X-Device-Key` 推出，防止 A 设备密钥查 B 设备档案）

**返回**：

```json
{
  "code": 0,
  "data": {
    "device_id": "SH-A3-01-01",
    "device_name": "上海 A3 栋 01 会议室屏",
    "bound": true,
    "room_id": "room-a3-01",
    "room_name": "上海 A3-01",
    "timezone": "Asia/Shanghai",
    "server_time_utc": "2026-10-28T04:26:12Z",
    "agent_version": "1.0.0"
  }
}
```

未绑定时：`bound=false`，`room_id`/`room_name` 为 `null`。

**错误**：1002 密钥错

### 2.5 GET /api/device/schedule — 会议室日程（F2.4 / 标牌"下一场"）

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| hours | int | 否 | 往后看多少小时，默认 24，1~168（越界 → 1001） |

> 窗口往前留 60 分钟：刚开始的会仍出现（`is_current=true`）；cancelled 的不下发。

**返回**：

```json
{
  "code": 0,
  "data": {
    "device_id": "SH-A3-01-01",
    "bound": true,
    "room_id": "room-a3-01",
    "room_name": "上海 A3-01",
    "timezone": "Asia/Shanghai",
    "window_hours": 24,
    "server_time_utc": "2026-10-28T04:26:12Z",
    "items": [
      {
        "meeting_id": "meeting_a3_01_0",
        "subject": "产品评审会",
        "start_time_utc": "2026-10-28T02:08:00Z",
        "end_time_utc": "2026-10-28T03:08:00Z",
        "time_label": "10:08 – 11:08",
        "status": "scheduled",
        "is_current": false,
        "is_next": true,
        "content_url": "http://localhost:8000/ui/display/meeting.html?meeting_id=...",
        "is_sensitive": false
      }
    ]
  }
}
```

**约定**：`items` 按开始时间升序，`is_next` 至多一条；敏感会议 `subject` 已是"会议中"且 `is_sensitive=true`；`time_label` 为会议室本地时间（DST 由 tzdata 处理）；未绑定 `items=[]`。

**错误**：1001 hours 越界｜1002 密钥错

### 2.6 GET /api/device/materials — 应缓存素材清单（F4.1 / F4.4）

设备"预拉取"权威清单：公共素材 + 本会议室活跃会议的专属素材，已排除过期项。

**返回**：

```json
{
  "code": 0,
  "data": {
    "device_id": "SH-A3-01-01",
    "bound": true,
    "room_id": "room-a3-01",
    "total_mb": 2.4,
    "count": 1,
    "server_time_utc": "2026-10-28T04:26:12Z",
    "items": [
      {
        "material_id": "mat_001",
        "name": "brand-default.png",
        "format": "png",
        "size_mb": 2.4,
        "url": "http://localhost:8000/media/mat_001.png",
        "checksum": "sha256:9f3a…",
        "scope": "public",
        "meeting_id": null,
        "expire_at": null,
        "reason": "public"
      }
    ]
  }
}
```

**约定**：`reason` = `public` 或 `meeting:<meeting_id>`；`checksum`：≤32MB 全量 `sha256:`，更大 `sha256-partial:`（首尾各 1MB + 字节数），无实体文件为 `null`；未绑定设备仅下发公共素材；15 天 LRU 由设备端执行，服务端提供 `size_mb`/`expire_at` 依据。

**错误**：1002 密钥错

---

## 三、认证与账号（2 个）

### 3.1 POST /api/auth/login — 登录（免认证）

**入参**：

```json
{ "email": "admin@honghe.com", "password": "admin123" }
```

**返回**：

```json
{ "code": 0, "data": { "token": "eyJhbGciOiJIUzI1NiJ9...", "user_id": "admin_001",
  "name": "管理员", "role": "admin", "expires_in": 28800 } }
```

**错误**：1001 参数缺失｜1002 邮箱或密码错误（不区分两者，防账号枚举）

### 3.2 GET /api/auth/me — 回显当前身份

**返回**：`{ "code": 0, "data": { "user_id": "admin_001", "name": "管理员", "role": "admin" } }`

**错误**：1002 token 缺失/过期

---

## 四、管理端 · 素材与知识库（7 个，JWT）

### 4.1 GET /api/admin/materials — 素材列表（F4.2）

| Query | 说明 |
| --- | --- |
| `scope=public\|meeting`（可选） | 素材轨 |
| `meeting_id`（可选） | 按会议过滤专属素材 |
| `category`（可选：brand/culture/meeting/other） | 一级业务分类（粗筛） |
| `tag`（可选） | 自由标签（细筛）；与 category 为「与」关系 |
| `page`、`page_size` | 分页 |

**返回**：

```json
{
  "code": 0,
  "data": {
    "items": [{
      "material_id": "mat_001",
      "name": "Q3-review-cover.png",
      "format": "png",
      "size_mb": 2.4,
      "url": "https://cdn.meetcast.app/m/mat_001.png",
      "scope": "meeting",
      "meeting_id": "meeting_123",
      "uploaded_by": "organizer:zhangsan@honghe.com",
      "expire_at": "2026-10-28T03:30:00Z",
      "created_at": "2026-10-28T00:12:00Z"
    }],
    "total": 32
  }
}
```

### 4.2 POST /api/admin/materials — 公共素材上传（F4.1）

multipart/form-data：`file`（≤500MB）+ `scope=public` + 可选 `tags`、`expire_at`

**返回**：`{ "code": 0, "data": { "material_id": "mat_032", "url": "…" } }`
**错误**：2005｜2007｜2013（向量入库失败，素材本体已保存可补向量）
**备注**：上传成功后**异步向量化**入 Milvus `material_vectors`（F4.5）；15 天 LRU 依据 `last_used_at`；专属素材走 §五 免登录通道。

### 4.3 DELETE /api/admin/materials/{material_id} — 删除（F4.2）

**返回**：`{ "code": 0, "data": null }`；专属素材删除时同步下发 `CLEAN_MATERIAL`（F4.8）；同步删 Milvus 向量
**错误**：2004

### 4.4 GET /api/admin/materials/search — 素材语义检索（F4.5 · v1.0 新增 P0）

一句自然语言直接搜素材（"科技感强的背景图"）。**混合检索**：Milvus 向量 topK + 关键词/标签过滤融合排序。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| q | string | 是 | 自然语言描述，1~100 字 |
| scope | string | 否 | 默认 `public`（专属素材不经检索下发，过滤掉） |
| category | string | 否 | 一级分类过滤 |
| top_k | int | 否 | 默认 20，1~50 |

**返回**：

```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "material_id": "mat_017",
        "name": "tech-blue-bg.png",
        "score": 0.87,
        "matched_tags": ["科技", "背景"],
        "name": "tech-blue-bg.png",
        "format": "png",
        "size_mb": 3.1,
        "url": "https://cdn.meetcast.app/m/mat_017.png",
        "category": "brand",
        "tags": ["科技感", "蓝色", "背景"]
      }
    ],
    "total": 5,
    "q": "科技感强的背景图",
    "latency_ms": 120
  }
}
```

**约定**：`score` 为归一化相关度 0~1；检索范围一期仅 `scope=public`；未向量化素材不出现在结果中（可重试补向量）。

**错误**：1001 q 缺失｜2013 embedding 服务不可用

### 4.5 GET /api/admin/kb/documents — 知识库文档列表（F4.9 · v1.0 新增 P0）

**返回**：

```json
{
  "code": 0,
  "data": {
    "items": [{
      "doc_id": "doc_9f3a",
      "title": "品牌手册 2026",
      "source_uri": "/media/kb/doc_9f3a.pdf",
      "chunk_count": 42,
      "embedding_model": "text-embedding-v3",
      "status": "ready",
      "uploaded_by": "admin:admin_001",
      "created_at": "2026-10-28T02:00:00Z"
    }],
    "total": 3
  }
}
```

> `status`：`parsing`（MinerU 解析中）→ `embedding`（向量化中）→ `ready`（可被 RAG 检索）｜`failed`（可重试）。

### 4.6 POST /api/admin/kb/documents — 上传知识库文档（F4.9）

multipart/form-data：`file`（pdf/docx/md/txt，≤50MB）+ 可选 `title`

**链路**：MinerU 解析 → 分块 → embedding → Milvus `brand_kb`；Agent A 生成会议页文案前按会议主题检索 top3 垫 prompt。

**返回**：`{ "code": 0, "data": { "doc_id": "doc_9f3a", "status": "parsing" } }`
**错误**：2005（格式不支持）｜2007（超限）

### 4.7 DELETE /api/admin/kb/documents/{doc_id} — 删除知识库文档（F4.9）

**返回**：`{ "code": 0, "data": null }`；同步删 Milvus `brand_kb` 中该文档全部分块
**错误**：2012

---

## 五、免登录上传（2 个，URL token 认证）

> 对应 F4.7 / 场景 D。token 由 `upload_token` 表管理：绑定 meeting_id，会后失效，`max_uses` 防滥用。

### 5.1 GET /api/upload/{token} — 会议与上传信息

**返回**：

```json
{
  "code": 0,
  "data": {
    "meeting_id": "meeting_123",
    "subject": "产品评审会",
    "room_name": "Room-A3-01 · 上海总部 3F",
    "start_time_utc": "2026-10-28T02:00:00Z",
    "end_time_utc": "2026-10-28T03:00:00Z",
    "timezone": "Asia/Shanghai",
    "upload_deadline_utc": "2026-10-28T01:30:00Z",
    "max_size_mb": 500,
    "accepted_formats": ["png", "jpg", "mp4", "mp3"],
    "uploaded": [{ "name": "Q3-review-cover.png", "size_mb": 2.4, "status": "ready" }]
  }
}
```

**错误**：1004 token 无效/过期｜2006 上传已截止

### 5.2 POST /api/upload/{token} — 上传专属素材

multipart/form-data：`file` + `scope=meeting`（隐含）

**返回**：`{ "code": 0, "data": { "material_id": "mat_001", "name": "Q3-review-cover.png", "status": "ready" } }`
**错误**：1004｜2005｜2006｜2007｜2013
**备注**：`initiated_by = organizer:<email>`；`expire_at` = 会议结束；异步向量化（仅元信息，专属素材不进公共检索范围）

---

## 六、管理端 · 日历源（3 个，JWT）

### 6.1 GET /api/admin/calendar/config — 读取配置

**返回**：

```json
{
  "code": 0,
  "data": {
    "provider": "m365",
    "tenant": "honghe.onmicrosoft.com",
    "service_account": "meetcast-agent（app-only）",
    "scopes": ["Calendars.Read", "Mail.Send"],
    "connection_status": "connected",
    "credential_expire_at": "2027-01-04T00:00:00Z",
    "pull_policy": {
      "schedule": { "enabled": true, "interval_min": 5, "window_hours": 12 },
      "link_gen": { "enabled": true, "interval_min": 30, "window_days": 7 },
      "dst_enabled": true
    },
    "alert_email": "it-admin@honghe.com"
  }
}
```

### 6.2 PUT /api/admin/calendar/config — 保存配置

**入参**：6.1 的 `data` 去掉 `connection_status`/`credential_expire_at`（只读）
**返回**：`{ "code": 0, "data": null }`
**备注**：只允许开关/周期/告警邮箱；`scopes` 服务端固定不可改；凭据（tenant_id/client_id/secret）只存 `.env`，不经本接口传输

### 6.3 POST /api/admin/calendar/test — 连接测试（F2.7，P0）

真实调用 Graph：鉴权 → 拉会议室清单 → 抽一间房拉日程，返回延迟与同步数。

**返回**：

```json
{
  "code": 0,
  "data": {
    "auth_ok": true,
    "rooms_synced": 4,
    "api_latency_ms": 420,
    "checked_at": "2026-10-28T04:30:00Z"
  }
}
```

**错误**：3001 凭证失效｜3002 API 超限

---

## 七、管理端 · 运维与内容审核（4 个，JWT）

### 7.1 GET /api/admin/commands — 指令审计记录（F7.1 / F8.3）

**Query**：`device_id`（可选）、`initiated_by`（可选）、`page`、`page_size`

**返回**：

```json
{
  "code": 0,
  "data": {
    "items": [{
      "command_id": "cmd_9f3a…",
      "device_id": "SH-A3-01-01",
      "type": "PREPARE_MEETING",
      "status": "ACKED",
      "initiated_by": "system",
      "created_at": "2026-10-28T01:50:00Z",
      "acked_at": "2026-10-28T01:50:02Z",
      "retry_count": 0
    }],
    "total": 128
  }
}
```

### 7.2 POST /api/admin/commands/switch — 手动干预切换（F7.5）

唯一允许人工触发 `SWITCH_CONTENT` 的入口；自动路径一律走 `PREPARE_MEETING.switch_at`。

**入参**：

```json
{ "device_id": "SH-A3-01-01", "content_url": "https://meetcast.app/c/emergency", "until": "2026-10-28T05:00:00Z" }
```

**返回**：`{ "code": 0, "data": { "command_id": "cmd_a1b2…" } }`
**错误**：1003｜2001｜2009（入队 PENDING，上线后经 poll 下发）
**备注**：`initiated_by = admin:<user_id>`

### 7.3 GET /api/admin/contents/{meeting_id} — 会议页内容预览（F5.6 · v1.0 新增 P0）

查看某场会当前生成的会议页内容（CrewAI 产出 + 降级态），供管理员**下发前审核**。

**返回**：

```json
{
  "code": 0,
  "data": {
    "meeting_id": "meeting_123",
    "status": "generated",
    "layout": "standard",
    "generated_by": "crewai:agent_a",
    "title": "Q3 产品评审会",
    "tagline": "聚焦三大产品线季度复盘",
    "attendees": ["张三", "李四", "王五"],
    "time_label": "10:00 – 11:00",
    "is_sensitive": false,
    "content_url": "http://localhost:8000/ui/display/meeting.html?meeting_id=...",
    "kb_chunks_used": ["doc_9f3a#chunk12", "doc_9f3a#chunk07"],
    "generated_at": "2026-10-28T01:49:30Z"
  }
}
```

**约定**：`status` = `generated`（CrewAI 产出）｜`edited`（管理员编辑过）｜`template`（降级模板）；敏感会议 `title` 固定"会议中"且编辑接口不允许改回真实标题；`kb_chunks_used` 记录 RAG 命中的知识库分块（审计可溯源）。

**错误**：2010 会议不存在

### 7.4 PUT /api/admin/contents/{meeting_id} — 编辑会议页内容（F5.6）

**入参**：

```json
{ "title": "Q3 产品评审会（修正版）", "tagline": "聚焦三大产品线复盘与规划" }
```

**返回**：`{ "code": 0, "data": { "status": "edited", "content_url": "http://…（重新渲染）" } }`
**备注**：编辑后立即重新渲染会议页并刷新 `content_url`；设备端已预拉取的会在下一轮 PREPARE/预拉取窗口拿到新版；`initiated_by = admin:<user_id>`；`status` 置 `edited`

**错误**：1001｜2010｜敏感会议尝试改 title → 1003（不允许）

---

## 八、枚举附录（与 PRD 对齐）

**指令类型**（command.type）：`PREPARE_MEETING`｜`SWITCH_CONTENT`（仅手动干预）｜`REPLAY_DEFAULT`｜`SHOW_NOTICE`（二期）｜`CLEAN_MATERIAL`｜`REBOOT`（二期）

**指令状态**（command.status）：`PENDING` → `SENT` → `ACKED`｜`FAILED`｜`TIMEOUT`

**initiated_by 枚举**（F8.3）：`admin:<user_id>`｜`system`｜`meeting:<meeting_id>`｜`organizer:<email>`｜`device_user:<device_id>`｜`crewai:<agent_name>`（v1.0 新增：Agent 产出的内容被审核/下发时留痕）

**设备状态**（device_state）：`IDLE`｜`MEETING_PREP`｜`MEETING`｜`FALLBACK`

**素材 scope**：`public`（公共，行政/运营传）｜`meeting`（专属，定会者传）

**知识库文档 status**：`parsing`｜`embedding`｜`ready`｜`failed`

**免登录 token 规则**：绑定 `meeting_id`；`expire_at` = 会后失效（接口侧另校验上传截止=会前 30 分钟）；`max_uses` 默认 50，超限 1004

---

## 九、技术栈选型（v1.0 定稿，与 PRD §三 一致）

> **原则不变**（PRD §1.4）：90% 逻辑用代码实现，仅"内容生成"用 LLM；确定性链路不硬套 LLM。

| 层 | 技术栈 | 用在哪 | 对应接口/功能 |
| --- | --- | --- | --- |
| HTTP 接口层 | **FastAPI + Pydantic v2** | 28 个接口的路由/校验/鉴权 | 全部 |
| 数据层 | **PostgreSQL + SQLAlchemy + Alembic** | 全部业务表 + 迁移；command 表 = 指令队列事实源 | 全部 |
| 缓存/队列 | **Redis** | 长轮询唤醒 pub/sub（§2.1 ≤5 秒送达）、日程缓存、分布式锁（调度单实例）、在线状态 | §2 系列 |
| 向量库 | **Milvus** | `material_vectors`（素材语义）+ `brand_kb`（品牌知识库） | §4.4、§4.5~4.7 |
| 调度编排 | **LangGraph**（主编排） | 服务端调度 pipeline 状态图：sync_calendar → evaluate_device → expire_materials → ensure_upload_links；checkpointer 落 PG，可回放/断点续跑 | §2 背后的生成逻辑 |
| Agent 协作 | **CrewAI**（文案 crew） | Agent A 会议页文案 + Agent B 选版式/标牌协作；工具绑定 RAG 检索 | §7.3/7.4、F5 |
| LLM 调用 | **LangChain**（ChatModel + structured output） | 统一模型接入与结构化输出（文案 JSON 化） | Agent A/B |
| Embedding | 阿里百炼 / DeepSeek 侧模型 | 素材与知识库向量化 | §4.4~4.7 |
| 文档解析 | **MinerU** | 知识库文档（pdf/docx）解析分块 | §4.6 |
| LLM 网关 | DeepSeek（OpenAI 兼容） | 文案/版式；失败一律降级模板 | F5 |

**架构分层（谁调谁）**：

```
FastAPI 路由（28 接口）
   ├─ 确定性服务：设备绑定 / 素材 CRUD / 日历同步 / 指令队列  ← 纯代码，无 LLM
   ├─ 调度 pipeline：LangGraph 状态图（APScheduler 定时唤起 + Redis 锁）
   │     sync_calendar → evaluate_device → expire_materials → ensure_upload_links
   └─ Agent 服务：CrewAI crew（内容生成）
        ├─ agent_a 会议页文案（LangChain + Milvus brand_kb RAG）
        ├─ agent_b 选版式 + 标牌文案
        └─ 降级边：LLM 失败 → 规则模板 / 纯文字标题（图的分支，不是 try-catch）
```

**RAG 两条链路（P0）**：

```
链路① 素材语义检索（§4.4）：
  上传 → LLM 生成语义描述 → embedding → Milvus material_vectors
  查询 → query embedding → 向量 topK + 关键词/标签混合排序 → 返回
链路② 品牌知识库（§4.6 → §7.3）：
  文档上传 → MinerU 解析分块 → embedding → Milvus brand_kb
  Agent A 生成文案前 → 按会议主题检索 top3 → 垫进 prompt → kb_chunks_used 留痕
```

**工程注意**：

- Pydantic model 按本规范 JSON 示例写，`model_json_schema()` 即接口文档；前端 Mock 只准复制规范返回示例
- LangGraph 节点入参出参用 Pydantic，图状态含 meeting 上下文，便于复现与追溯
- 模型调用统一 `with_structured_output`，禁止自由文本直接进 payload
- Milvus 写入失败不阻塞素材/文档本体保存（2013 可重试补向量）——**向量是加速层，不是事实源**

---

## 十、角色与接口权限矩阵（F8.1 / F8.2）

| 接口 | 普通用户（user） | 管理员（admin） |
| --- | --- | --- |
| `GET /api/admin/devices`、`GET /api/admin/rooms`（查看） | ✅ | ✅ |
| `GET /api/admin/materials`、`GET /api/admin/materials/search` | ✅ | ✅ |
| `POST /api/admin/materials`（上传公共素材） | ✅ | ✅ |
| `POST /api/admin/devices/bind`、`/unbind` | ❌ 1003 | ✅ |
| `DELETE /api/admin/materials/{id}` | ❌ 1003 | ✅ |
| `GET/POST/DELETE /api/admin/kb/documents`（知识库管理） | ❌ 1003 | ✅ |
| `GET/PUT /api/admin/contents/{meeting_id}`（内容审核） | ❌ 1003 | ✅ |
| `GET/PUT /api/admin/calendar/config`、`POST /test` | ❌ 1003 | ✅ |
| `GET /api/admin/commands`、`POST /commands/switch` | ❌ 1003 | ✅ |

> 实现落在 `app/security.py` 两个依赖：`auth_user`（任意已登录角色）与 `auth_admin`（仅管理员）。

---

## 十一、接口总览（28 个）

| 分组 | 接口 | 认证 |
| --- | --- | --- |
| 设备端（6） | poll / ack / heartbeat / profile / schedule / materials | X-Device-Key |
| 认证（2） | login / me | 免认证 / JWT |
| 设备与会议室（4） | admin/devices 列表 / bind / unbind / admin/rooms | JWT |
| 素材与知识库（7） | materials 列表/上传/删除 / **materials/search** / **kb 列表/上传/删除** | JWT |
| 免登录上传（2） | upload/{token} GET / POST | URL token |
| 日历源（3） | config GET/PUT / test | JWT |
| 运维与审核（4） | commands / commands/switch / **contents 预览 / contents 编辑** | JWT |

---

**合规声明**：本规范为工程实施参考，具体实施请结合公司合规与法务要求确认。
