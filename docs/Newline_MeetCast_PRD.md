# Newline MeetCast PRD

**产品名称**：Newline MeetCast（Calendar-Driven Meeting Room Display）  
**版本**：v1.0（生产级重写版）  
**日期**：2026-10-28  
**负责人**：周天扬  
**状态**：定稿 · 一期按 P0 开发  
**变更记录**：

- v1.0（本次）：**全面转生产级**，删除"4 天快速交付"全部叙事；技术栈定稿为 Python + Agent 生态（FastAPI / Pydantic / Alembic / LangChain / LangGraph / CrewAI / RAG / PostgreSQL / Milvus / Redis）；**设备端一期 = macOS**（"四、核心设计"按 macOS 重写），安卓 APK 移二期；素材语义检索（F4.5）与品牌知识库 RAG 升 P0；内容审核（F5.6）升 P0；里程碑按生产级重排；新增「Azure AD 凭据申请指南」补充章节；P1/P2 条目集中挪至「二期规划」
- 历史版本（v0.2~v0.8）的关键定稿结论继续有效，收敛进「十、确认结论」：素材双轨制 / 扫码绑定路径 / prepare_at + switch_at 双时刻 / 自动切换唯一路径 = 设备本地定时 / 免登录链接邮件单通道 / CLEAN_MATERIAL 双侧清理 / 敏感判定前置 / 长轮询 hold + 心跳 POST / initiated_by 枚举 / 试点 4 城 4 时区带

---

## 一、背景与目标

### 1.1 业务背景

Newline 品牌在美国 IFPD 市场市占率 23.2% 稳居第一，2026H1 商用场景收入 3.71 亿元（同比 +46.46%），海外收入占比 59.80%。当前海外商用产品停留在"人工配置、人工编排"阶段，智能化落后于国内同行（MAXHUB 领效智会大模型、海信接入 DeepSeek）。

本产品基于 Newline Signage Pro 裁剪重构：**只保留"素材上传 + 设备注册 + 播放"核心能力，代码全新生成**，叠加日历驱动的智能场景编排。

### 1.2 产品目标

| 维度     | 现状              | 目标                                       |
| ------ | --------------- | ---------------------------------------- |
| 场景切换   | 人工在后台改排期        | 按会议日程自动切换，会议结束自动恢复                       |
| 配置成本   | 运营手工选模版、填素材、配周期 | 仅需上传素材 + 扫码绑设备，其余全自动                     |
| 素材查找   | 人工翻素材库          | **语义检索**：一句"找科技感强的背景图"直接命中               |
| 会议室利用率 | 屏幕闲置时与企业形象无关    | 空档期展示品牌内容，会议期展示会议信息                      |
| 差异化    | 与国内厂商同质化        | **出海多时区自适应 + 会议/标牌双场景统一编排 + RAG 素材/知识库** |

### 1.3 非目标（本产品明确不做）

- ❌ 会议纪要生成 / 语音转写 / 同声传译
- ❌ 点餐交易闭环（二期仅"提醒 + 推荐 + 跳转"）
- ❌ 视频会议能力 / 裸眼 3D 等硬件线
- ❌ 对接现有 Signage Pro 素材库（全新独立系统）
- ❌ 复杂子账户权限体系

### 1.4 核心设计原则

1. **确定性优先**：90% 逻辑用代码实现（调度、状态判定、指令下发），仅"内容生成"用 LLM
2. **LLM 可降级**：文案生成失败降级为纯文字会议标题，不阻塞主链路
3. **模版策略**：人工不选模版，Agent 自动选配；拿不准时用 2~3 个兜底固定版式
4. **审计必埋**：所有操作记录 `initiated_by`（谁触发的）
5. **最小权限**：普通用户 + 管理员两级；日历读取走独立 app-only 服务账号
6. **生产级底线**：异常兜底（断网自愈 / 绝不黑屏）是一期 P0，不是"以后再说"

---

## 二、用户角色与使用场景

### 2.1 角色定义

| 角色             | 说明            | 权限范围                            |
| -------------- | ------------- | ------------------------------- |
| 定会者（会议组织者）     | 发起会议的普通员工     | 上传/管理**本场会议专属素材**（免登录链接，无需后台账号） |
| 普通用户（运营/行政）    | 上传素材、管理会议室    | 公共素材上传、会议室查看、设备查看               |
| 管理员            | 系统管理员、实施/运维   | 全部功能 + 设备管理 + 日历源配置 + 知识库管理     |
| 系统身份（app-only） | Azure AD 服务账号 | 读所有会议室日历 + 发通知邮件（不参与人工登录）       |

> **设备永不登录个人账号**。**素材双轨制**：公共素材由运营/行政上传共享；会议专属素材由定会者经免登录链接直传、不过行政、仅本场可见、会后自动清理。

### 2.2 核心场景

**场景 A：会议自动切换（主场景）**

```
09:45  服务端拉取 Room-A3-01 日历，发现 10:00-11:00 "产品评审会"
09:50  下发 PREPARE_MEETING（prepare_at=09:50，switch_at=09:59）+ 会议页预拉取地址
09:50  设备进 MEETING_PREP：预拉取会议页到本地（仍显示标牌，不切黑）
09:59  设备本地按 switch_at 定时切到会议页
11:00  会议结束，服务端下发 REPLAY_DEFAULT → 恢复标牌
```

**场景 B：绑定设备（手机扫门口码 + 后台确认）**

```
门口二维码只含 room_id（贴门口不动）；device_id 由设备开机画面大字展示
管理员手机扫门口码 → 后台显示会议室名称与日历状态
   → 待绑定设备列表选中该 device_id（对照设备屏）→ 确认绑定
写入 device.room_id，纳入调度；换绑走 F1.4
```

**场景 C：跨国跨时区同步（差异化场景）**

```
试点 4 城 4 时区带：上海 / 新加坡（UTC+8 无 DST）、巴塞罗那（欧盟 DST）、美国（美式 DST）
总部纽约 09:00 全球招商会 → 全程 UTC 存储，按各会议室 IANA 时区本地化渲染
美欧 DST 切换日不同，两段"错位窗口"内时差 6h→5/7h，换算必须自动正确
```

**场景 D：定会者免登录直传专属素材**

```
张三 Outlook 约"明天 10:00 产品评审会"（Room-A3-01）
   → 服务端拉到日程，organizer=张三 → 生成免登录上传链接（token 绑 meeting_id，会后失效）
   → Graph Mail.Send 以应用身份发邮件给张三
张三点链接 → 直接上传（无账号、无行政审核、上传即生效）
会前预拉取：公共素材 + 本场专属素材一起拉到设备本地
会后：服务端下发 CLEAN_MATERIAL 删设备本地副本 + 服务端记录按 expire_at 过期（双侧清理）
```

> 二期场景（点餐提醒、推荐、跳转订餐）见「九、二期规划」。

---

## 三、技术栈与总体架构

### 3.1 技术栈定稿

| 层         | 技术                                                     | 用途                                                |
| --------- | ------------------------------------------------------ | ------------------------------------------------- |
| Web 框架    | **FastAPI + Pydantic v2**                              | 22+ REST 接口；Pydantic model 即文档                    |
| 数据持久化     | **PostgreSQL + SQLAlchemy + Alembic**                  | 全部业务表；Alembic 管迁移；指令队列以 PG 表为准（command_id 幂等）     |
| 缓存/队列     | **Redis**                                              | 长轮询唤醒（pub/sub）、日程缓存、设备在线状态、热点素材 URL               |
| 向量库       | **Milvus**                                             | 素材语义向量（F4.5）+ 品牌知识库向量（F4.9）                       |
| 编排        | **LangGraph**                                          | 服务端调度 pipeline（日历→状态机→指令生成）状态图化：可观测、可回放、可断点       |
| Agent 团队  | **CrewAI**                                             | 文案生成 crew：Agent A 会议页文案 + Agent B 选版式/标牌内容协作（含降级） |
| LLM       | DeepSeek（OpenAI 兼容协议）                                  | 文案/版式推荐；失败一律降级模板                                  |
| Embedding | 阿里百炼 / DeepSeek 侧 embedding 模型                         | 素材与知识库向量化                                         |
| 文档解析      | MinerU                                                 | 知识库文档（品牌手册/文化墙文案）入库前解析                            |
| 设备端（一期）   | **macOS 原生 Swift**（WKWebView / AVPlayer / LaunchAgent） | 见 §四                                              |
| 设备端（二期）   | Android 原生（Kotlin）                                     | 见「九、二期规划」                                         |

### 3.2 总体架构

```
┌────────────────────────────────────────────┐
│ 接入层  FastAPI（uvicorn worker × N）       │
│  管理端 11+ 接口（JWT）· 设备端 6 接口       │
│  （X-Device-Key）· 免登录上传 2 接口         │
└──────────────┬─────────────────────────────┘
               ↓
┌────────────────────────────────────────────┐
│ 编排层  LangGraph 状态图（确定性，不用 LLM） │
│  sync_calendar → evaluate_device →         │
│  expire_materials → ensure_upload_links    │
│  节点级 checkpointer（PG）→ 可回放/断点续跑 │
└──────────────┬─────────────────────────────┘
               ↓
┌────────────────────────────────────────────┐
│ Agent 层  CrewAI crew（仅内容生成）         │
│  Agent A 会议页文案 · Agent B 选版式/标牌   │
│  RAG 检索品牌知识库 → 垫进 prompt           │
│  失败一律降级固定模板（不阻塞主链路）       │
└──────────────┬─────────────────────────────┘
               ↓
┌────────────────────────────────────────────┐
│ 数据层                                     │
│  PostgreSQL：room/device/command/meeting/  │
│    material/upload_token/user/kb_document  │
│  Redis：长轮询唤醒 pub/sub · 日程缓存 ·    │
│    在线状态                                │
│  Milvus：material_vectors · brand_kb       │
│  本地磁盘：素材文件（/media 静态托管）      │
└──────────────┬─────────────────────────────┘
               ↓
┌────────────────────────────────────────────┐
│ 设备端（一期 macOS · 二期 Android）         │
│  长轮询取指令 → ACK → WKWebView/AVPlayer   │
│  本地素材缓存 + 15 天 LRU + 断网自愈       │
└────────────────────────────────────────────┘
```

**与 demo 版的本质区别**：持久化落 PG（重启不丢）、指令队列可回放、多实例可横向扩展（Redis 协调）、Agent 层状态图化可观测。

---

## 四、核心设计（一期 = macOS 设备端）

### 4.1 设备端状态机（macOS 侧）

```
┌────────────┐   日历无会/恢复成功   ┌─────────────┐
│   IDLE     │◄──────────────────────┤   FALLBACK  │
│  显示标牌  │                        │ 保持旧内容  │
└─────┬──────┘                        │  +离线角标  │
      │ PREPARE_MEETING（prepare_at） └──────▲──────┘
      ▼                             服务端不可达│/下载失败
┌─────────────┐   拉取失败重试 1 次  │
│MEETING_PREP │──────────────────────┘
│ 预拉取内容  │   仍失败 → 转 FALLBACK（保持旧内容，绝不黑屏）
│（仍显示标牌）│
└─────┬───────┘
      │ 预拉取成功 + 到达 switch_at（会前 1min）
      ▼
┌─────────────┐
│   MEETING   │──── until（会议结束）───► REPLAY_DEFAULT ────► IDLE
│  显示会议页 │
└─────────────┘
```

- **四态齐全是一期 P0**（生产级口径，不再砍 FALLBACK）
- 设计要点：MEETING_PREP 故意不切屏——先预拉取、拉完再切，避免黑屏
- 预拉取失败：重试 1 次 → 仍失败转 FALLBACK 并记 error 日志（meeting_id），绝不卡死

### 4.2 服务端分层

- **调度层（LangGraph 图，不用 LLM）**
  - 节点：① sync_calendar（批量拉 20 间/次）→ ② evaluate_device（状态机判定生成指令）→ ③ expire_materials（到期清理 + CLEAN_MATERIAL）→ ④ ensure_upload_links（新会→token→邮件）
  - 触发：APScheduler 定时唤起图执行（编排 5 分钟 / 链接生成 30 分钟两档）
  - checkpointer 落 PG：每次图执行可回放、可从失败节点续跑
- **Agent 层（CrewAI crew，仅内容生成）**
  - Agent A 会议页文案：输入主题/参会人/时间 → RAG 检索品牌知识库垫 prompt → 生成文案
  - Agent B 选版式 + 标牌内容：standard/focus/minimal 三选一（minimal 仅敏感会议硬规则）+ 时段标牌文案
  - 降级链固定：敏感判定前置 → LLM 生成 → 失败降纯文字模板
- **下发层（确定性）**
  - 指令队列：PG command 表为准（command_id 幂等）+ Redis pub/sub 唤醒长轮询（有指令 ≤5 秒送达）
  - 设备长轮询 POST /api/device/poll（hold 25s）

### 4.3 设备端（macOS 一期）功能范围

| 编号 | 功能      | 说明                                                                           |
| -- | ------- | ---------------------------------------------------------------------------- |
| A1 | 绑定配合    | 开机展示本机 device_id（大字）+ 绑定页输入设备密钥自检注册；实际绑定由管理员扫门口码在后台完成                        |
| A2 | 长轮询拉指令  | POST /api/device/poll（hold 25s）；心跳 POST /api/device/heartbeat 每 30s          |
| A3 | 素材下载与缓存 | 下载到本地（~/Library/Application Support/MeetCastDevice/cache），sha256 校验，15 天 LRU |
| A4 | 内容播放    | WKWebView 渲染会议页/标牌页（服务端生成 URL，设备只负责打开）；AVPlayer 播 mp4/mp3                    |
| A5 | 场景切换    | 本地按 switch_at 定时切屏；until 到点恢复标牌（自动切换唯一路径）                                    |
| A6 | 预拉取     | 会议页 + 页面资源 + 素材提前落本地，拉完再切                                                    |
| A7 | 状态上报    | ACK + 当前播放内容 + 存储占用上报                                                        |
| A8 | 断网自愈    | 服务不可达不退出：显示缓存页/兜底页 + 离线角标，周期重试，恢复当秒重连                                        |
| A9 | 开机自启    | LaunchAgent 常驻；崩溃自动拉起                                                        |

**macOS 技术栈**：

```swift
Swift 6 + SwiftUI/AppKit     → 壳与状态机（Swift Concurrency 定时器）
WKWebView                    → 渲染会议页/标牌页（Agent 生成 URL，设备只负责打开）
AVPlayer                     → 播放 mp4/mp3（本地缓存优先）
URLSession                   → 长轮询/心跳/ACK/素材下载
FileManager + 文件时间戳      → 15 天 LRU 清理
LaunchAgent                  → 开机自启 + 崩溃拉起
```

### 4.4 设备端（Android 二期）适配说明

> 一期只交付 macOS 端；协议与状态机与平台无关，二期换壳即可。

| 项     | 二期方案                                                                |
| ----- | ------------------------------------------------------------------- |
| 渲染/播放 | WKWebView → Android WebView；AVPlayer → Media3（CacheDataSource 边播边下） |
| 后台任务  | LaunchAgent → WorkManager（长轮询/清理定时）                                 |
| 本地存储  | FileManager → Room/SQLite（素材元数据 + 15 天清理依据）                         |
| 自启    | LaunchAgent → BOOT_COMPLETED                                        |
| 交付形态  | 定制固件 APK + OTA 灰度（固件已确认支持）                                          |

### 4.5 设备通信协议

**设备主动长轮询**（会议室网络只出不进，不开放服务器端口）

```
POST /api/device/poll          ← 长轮询：hold 至有指令或超时（25s），有指令立即返回
POST /api/device/ack           ← { command_id, status: SUCCESS|FAILED, device_state }
POST /api/device/heartbeat     ← 每 30s 上报 { device_state, playing, storage_used_mb }
```

**指令类型枚举**

| type              | 含义               | payload 关键字段                                                        |
| ----------------- | ---------------- | ------------------------------------------------------------------- |
| `PREPARE_MEETING` | 预拉取会议页（含切屏时刻）    | content_url, meeting_id, **prepare_at, switch_at**, timezone, until |
| `SWITCH_CONTENT`  | 手动切换（**仅人工干预用**） | content_url, until, checksum                                        |
| `REPLAY_DEFAULT`  | 恢复标牌             | playlist[], slot, signage_url, timezone, meeting_id                 |
| `SHOW_NOTICE`     | 弹通知（二期点餐）        | title, body, action_url                                             |
| `CLEAN_MATERIAL`  | 清设备本地素材（会后清专属）   | material_ids[] 或 scope=meeting, meeting_id                          |
| `REBOOT`          | 重启设备（二期）         | —                                                                   |

**关键约定**：

- `command_id` 幂等键，重复收到只执行一次
- 全部指令携带 `initiated_by` 审计字段
- 时间一律 UTC ISO 8601；payload 必带 `timezone`（会议室 IANA 时区）
- **自动切换唯一路径**：设备本地按 switch_at 定时；SWITCH_CONTENT 仅人工干预

### 4.6 核心数据模型（PostgreSQL · Alembic 管理）

```sql
-- 会议室
room ( room_id PK, room_email UNIQUE, building, floor, capacity,
       timezone )                          -- IANA 时区，跨时区+DST 必备

-- 设备
device ( device_id PK, device_key UNIQUE, room_id FK NULL, status,
         last_heartbeat, agent_version, storage_used_mb )

-- 指令队列（核心）
command ( command_id PK, device_id FK, type, payload JSONB,
          status, retry_count, initiated_by, created_at, acked_at )

-- 会议
meeting ( meeting_id PK, room_id FK, subject, organizer_email,
          start_time_utc, end_time_utc, timezone, status, is_sensitive,
          created_at, updated_at )

-- 免登录上传 token
upload_token ( token PK, meeting_id FK, organizer_email,
               expire_at, used_count, max_uses, created_at, revoked_at )

-- 素材
material ( material_id PK, name, format, url, file_path, size_mb,
           scope,                            -- public / meeting
           meeting_id FK NULL,               -- scope=meeting 必填
           category, tags TEXT[], uploaded_by,
           expire_at, last_used_at, created_at )

-- 素材向量元数据（向量本体在 Milvus · collection: material_vectors）
material_vector ( material_id PK FK, milvus_pk, embedding_model,
                  embedded_at )

-- 品牌知识库文档（向量本体在 Milvus · collection: brand_kb）
kb_document ( doc_id PK, title, source_uri, chunk_count,
              embedding_model, uploaded_by, created_at )

-- 用户
app_user ( user_id PK, email UNIQUE, name, role,        -- admin / user
           password_hash, salt, created_at )
```


### 4.7 Agent / RAG 设计

**Milvus Collections**：

| Collection         | 维度来源         | 内容                           | 写入时机       |
| ------------------ | ------------ | ---------------------------- | ---------- |
| `material_vectors` | embedding 模型 | 素材名 + 标签 + 分类 + 视觉描述         | 素材上传后异步向量化 |
| `brand_kb`         | embedding 模型 | 品牌手册/企业信息/文化墙文案分块（MinerU 解析） | 管理员上传文档后   |

**两条 RAG 链路（均 P0）**：

- **素材语义检索（F4.5 升 P0）**：管理端搜索框输入"科技感强的背景图" → embedding → Milvus topK → 混合关键词过滤 → 返回素材列表；上传时 LLM 依据文件名/分类自动补语义描述再入库
- **品牌知识库（F4.9 新增 P0）**：Agent A 生成会议页文案前，按会议主题检索 brand_kb top3 分块垫进 prompt → 文案自动带企业调性；管理员可管理知识库文档（上传/列表/删除）

**LangGraph / CrewAI 边界**：LangGraph 管"确定性调度 pipeline"（状态、重试、可观测）；CrewAI 管"内容生成团队"（Agent A+B 协作、工具绑定 RAG 检索）；两者通过 store/PG 交接，不互相嵌套。

---

## 五、功能需求清单（一期 = 全部 P0）

> 一期只含 P0。原 P1/P2 条目（点餐、OTA、Google 日历、素材有效期、播放看板等）→「九、二期规划」。

### 5.1 F1 设备注册与绑定【P0】

| 编号   | 功能点     | 说明                                                  |
| ---- | ------- | --------------------------------------------------- |
| F1.1 | 设备绑定    | 扫门口码（room_id）→ 后台选中 device_id → 确认；device_id 开机画面展示 |
| F1.2 | 设备心跳保活  | 30s 一次；连续 3 次未上报标记 offline                          |
| F1.3 | 设备列表与状态 | 所属会议室、在线状态、当前播放内容、agent 版本                          |
| F1.4 | 设备解绑/换绑 | 支持换会议室、注销                                           |

**验收**：绑定 10 秒内生效免重启；离线 90 秒内反映到后台；换绑 5 分钟内调度生效。

### 5.2 F2 日历对接【P0】

> 背景与边界沿用定稿：M365 资源邮箱（IT 一次性创建）；**只读** Calendars.Read；上传链接走 Mail.Send 邮件单通道；不加 Calendars.ReadWrite。Azure AD 凭据申请完整步骤见「八、补充：Azure AD 凭据申请指南」。

| 编号   | 功能点        | 说明                                                 |
| ---- | ---------- | -------------------------------------------------- |
| F2.1 | M365 日历接入  | Graph calendarView，app-only + Calendars.Read       |
| F2.3 | 会议室资源同步    | 定时同步会议室清单（/places/microsoft.graph.room）            |
| F2.4 | 日程定时拉取（分层） | 编排拉取：5 分钟/未来 12h；链接生成拉取：30 分钟/未来 7 天；上传截止=会前 30 分钟 |
| F2.5 | 多时区 + DST  | 全程 UTC 存储 + IANA 本地化；美欧两套 DST + 错位窗口零误差            |
| F2.7 | 日历连接测试     | 管理员一键测试连通性（**从 P1 升 P0**：真实联调必备）                   |
| F2.6 | 日历源异常告警    | 凭证过期/API 超限告警管理员                                   |

**验收**：拉取延迟 ≤5 分钟；单次批量 ≥20 间；跨时区换算零误差；日历 API 失败不影响已下发内容播放。

> **临时会议边界**：编排周期 5 分钟 + 提前量 10 分钟 → 临时会议须开始前 ≥15 分钟创建，否则按"来不及编排"处理。

### 5.3 F3 场景自动编排【P0 · 核心】

| 编号   | 功能点         | 说明                                                         |
| ---- | ----------- | ---------------------------------------------------------- |
| F3.1 | 状态机         | 四态齐全（IDLE/MEETING_PREP/MEETING/FALLBACK），见 §4.1            |
| F3.2 | 双时刻自动切换     | prepare_at（会前 10min）+ switch_at（会前 1min）；自动切换唯一路径 = 设备本地定时 |
| F3.3 | 提前预拉取       | 会议页+素材提前落本地，拉完再切                                           |
| F3.4 | 标牌时段策略      | 早/中/晚三套，按会议室本地时区选                                          |
| F3.5 | Agent 自动选版式 | CrewAI 选配 + 兜底固定版式（minimal 仅敏感会议硬规则）                       |
| F3.6 | 兜底策略        | **断网自愈/绝不黑屏（升 P0）**：下载失败保持旧内容 + 离线角标；服务不可达转 FALLBACK       |

**验收**：单日 5 场切换成功率 100%；会前 ≤2 分钟完成预拉取；会后 ≤2 分钟恢复；断网 10 分钟恢复后内容自动恢复且无闪黑。

### 5.4 F4 素材管理【P0】

| 编号   | 功能点                  | 说明                                                               |
| ---- | -------------------- | ---------------------------------------------------------------- |
| F4.1 | 素材上传                 | jpg/png/mp4/mp3；冷门格式默认不支持                                        |
| F4.2 | 素材库管理                | 分类、标签、删除、预览                                                      |
| F4.3 | 兜底固定版式               | 2~3 个，Agent 拿不准时使用                                               |
| F4.4 | 设备本地清理               | 15 天 LRU（设备端执行，128G 盘）                                           |
| F4.5 | **素材语义检索（升 P0）**     | 向量检索 + 关键词混合；上传自动生成语义描述并入 Milvus                                 |
| F4.7 | 会议专属素材直传             | 免登录链接 + 邮件单通道（Mail.Send），token 绑 meeting_id                      |
| F4.8 | 专属素材生命周期             | 会后双侧清理：CLEAN_MATERIAL 删设备本地 + 服务端 expire_at 过期                   |
| F4.9 | **品牌知识库 RAG（新增 P0）** | 管理员上传品牌/企业文档（MinerU 解析分块）→ Milvus；Agent A 文案生成前检索垫 prompt；文档可增删查 |

### 5.5 F5 会议页内容生成【P0】

| 编号   | 功能点            | 说明                                 |
| ---- | -------------- | ---------------------------------- |
| F5.1 | 会议页文案生成        | CrewAI Agent A；RAG 检索品牌知识库垫 prompt |
| F5.2 | 参会人信息展示        | 主题/时间/参会人；敏感会议按 F5.5 脱敏            |
| F5.3 | 企业品牌融入         | Logo（图标版）+ 白紫主题（#7C3AED/#4C1D95）   |
| F5.4 | 降级策略           | 顺序固定：敏感判定 → LLM → 失败降纯文字标题         |
| F5.5 | 敏感信息脱敏         | 黑名单命中 → 标题"会议中"，跳过 LLM，任何路径不泄露     |
| F5.6 | **内容审核（升 P0）** | 管理员可预览/编辑 Agent 生成的会议页后再下发         |

**验收**：生成 ≤10 秒；失败 5 秒内降级；敏感会议全流程零泄露。

### 5.6 F7 运维与可观测（P0 部分）

| 编号   | 功能点     | 说明                                |
| ---- | ------- | --------------------------------- |
| F7.1 | 指令下发记录  | 全量审计日志（含 initiated_by）            |
| F7.2 | 指令重试与告警 | 超时未 ACK 自动重试，超限告警（**生产级升 P0**）    |
| F7.5 | 手动干预    | 管理员强制切换某设备内容（SWITCH_CONTENT 唯一入口） |

> F7.3 播放日志 / F7.4 健康看板 → 二期。

### 5.7 F8 账号权限【P0】

| 编号   | 功能点             | 说明                                                                              |
| ---- | --------------- | ------------------------------------------------------------------------------- |
| F8.1 | 普通用户            | 上传素材、查看会议室与设备                                                                   |
| F8.2 | 管理员             | 全部功能                                                                            |
| F8.3 | initiated_by 审计 | 枚举：admin:<uid> / system / meeting:<mid> / organizer:<email> / device_user:<did> |
| F8.4 | app-only 服务账号   | Azure AD 注册，日历+邮件专用，与人工账号解耦                                                     |

---

## 六、里程碑（生产级排期）

| 阶段              | 内容                                                                                | 周期             | 交付物                    |
| --------------- | --------------------------------------------------------------------------------- | -------------- | ---------------------- |
| M0 规范定稿         | API 规范 v1.0 重写（本文档同步）；数据模型 SQL 化评审                                                | 0.5 周          | API_Spec v1.0 + 建表 SQL |
| M1 服务端生产化骨架     | PG 落库（SQLAlchemy+Alembic 全表）、seed 幂等化、登录/JWT 完整化、Redis 接入（长轮询唤醒+缓存）、现有 22 接口迁到 PG | 1.5 周          | 可持久化运行的后端              |
| M2 macOS 设备端生产版 | 四态状态机补全（FALLBACK/断网自愈）、AVPlayer 播放、LaunchAgent、OTA 前的版本上报                         | 1.5 周（与 M1 并行） | 生产级 macOS App          |
| M3 M365 真接入     | Azure AD app-only（凭据申请见 §八）、calendarView/places/Mail.Send 真联调、连接测试、DST 真数据验证      | 1.5 周          | 真 M365 全链路             |
| M4 Agent 编排层    | 调度 pipeline 迁 LangGraph（checkpointer 落 PG）；文案/选版式迁 CrewAI crew；降级链回归测试            | 1.5 周          | 可观测的 LangGraph+CrewAI  |
| M5 RAG 能力       | Milvus 双 collection；素材上传自动向量化 + 语义检索接口；MinerU 知识库入库链路；Agent A 接知识库 RAG            | 1.5 周          | 语义搜图 + 知识库文案           |
| M6 内容审核+加固      | F5.6 审核流（预览/编辑/确认下发）、F7.2 重试告警、审计补全、压测（20 间房/高频切换）                                | 1 周            | 生产加固完成                 |
| M7 试点           | 4 城 4 会议室真机试点（上海/新加坡/巴塞罗那/美国），含 DST 错位窗口实测                                        | 2 周            | 试点报告                   |

**总计约 10 周**（M1/M2 并行可压缩至 ~8.5 周）。

> **现状差距说明（诚实口径）**：当前代码为"内存库 demo 版"（22 接口 + macOS App 已跑通正向闭环），M1 起按本 PRD 逐项生产化；demo 已验证的业务逻辑（状态机/双时刻/免登录/双轨素材）平移不重写。

---

## 七、风险与应对

| 风险                         | 影响     | 应对                                            |
| -------------------------- | ------ | --------------------------------------------- |
| M365 getSchedule 缓存延迟 40 秒 | 切换时机偏差 | 用 calendarView；实时性敏感场景绕过忙闲缓存                  |
| 美欧 DST 切换日 + 错位窗口          | 换算错误   | 全程 UTC + IANA；切换日/错位窗口专项测试；预拉取时刻防呆            |
| LLM 不确定性                   | 主链路阻塞  | 降级链固定（敏感判定→LLM→模板）；超时 6 秒即降                   |
| Agent 生成版式质量不可控            | 用户差评   | CrewAI 选配 + 兜底固定版式 + F5.6 人工审核兜底              |
| 敏感会议标题泄露                   | 合规风险   | 敏感判定前置，任何路径（含降级）不显示真实标题                       |
| 向量检索召回不准                   | 搜图体验差  | embedding 模型选型评测；混合检索（向量+关键词+标签过滤）            |
| Azure 凭据泄露                 | 租户安全   | secret 只存 server/.env（gitignore）；过期轮换告警（F2.6） |
| 多实例部署的指令竞争                 | 重复下发   | command_id 幂等 + Redis 分布式锁（调度图单实例执行）          |

---

## 八、补充：Azure AD 凭据申请指南（F2.1/F8.4 实施前提）

> 目标：拿到 4 个值——`tenant_id`、`client_id`、`client_secret`、房间邮箱地址。全程约 30 分钟，需 **M365 租户的 Entra 管理员**权限（无租户可用 M365 开发者租户免费建，或由客户 IT 代办）。

**Step 1 注册应用**

1. 登录 [entra.microsoft.com](https://entra.microsoft.com) → Identity → Applications → **App registrations** → **New registration**
2. Name：`meetcast-agent`；Supported account types：**Accounts in this organizational directory only**；Redirect URI：留空
3. Register 后，Overview 页记下 **Directory (tenant) ID** 和 **Application (client) ID**

**Step 2 创建客户端密钥**

1. 左侧 **Certificates & secrets** → Client secrets → **New client secret**
2. 描述随意、有效期选 24 个月 → Add
3. **立即复制 Value 列**（只在此时可见；Secret ID 不是密钥本体）

**Step 3 授应用权限（Application 权限，非 Delegated）**

1. **API permissions** → Add a permission → **Microsoft Graph** → **Application permissions**
2. 勾选：`Calendars.Read`（读所有会议室日历）、`Mail.Send`（发上传链接邮件）
3. 点 **Grant admin consent for <租户名>** → 状态变绿色 ✓（必须点，否则 401/403）

**Step 4 确认会议室资源邮箱**

1. [admin.microsoft.com](https://admin.microsoft.com) → Resources → **Rooms & equipment**
2. 确认每间试点会议室都有房间邮箱（没有则 New room 创建，半天工作量）
3. 记下邮箱地址（如 `room-a3-01@客户域名.com`）

**Step 5 写入服务端配置（server/.env，勿入库）**

```bash
MEETCAST_GRAPH_MOCK=0
MEETCAST_GRAPH_TENANT_ID=<Directory tenant ID>
MEETCAST_GRAPH_CLIENT_ID=<Application client ID>
MEETCAST_GRAPH_CLIENT_SECRET=<client secret Value>
MEETCAST_MAIL_MOCK=0
```

**Step 6 验证**

```bash
bash scripts/restart_server.sh
# 后台「日历源 → 连接测试」（POST /api/admin/calendar/test）应返回连通成功
```

**排错速查**：

| 现象                  | 原因                                     |
| ------------------- | -------------------------------------- |
| 401 invalid_client  | client_secret 复制错（误复制 Secret ID）或已过期   |
| 403 / Access denied | 忘了 Grant admin consent，或权限勾成 Delegated |
| 日历拉到但会议室缺           | 房间邮箱未创建，或 places 返回被租户策略隐藏             |
| 邮件发出但对方没收到          | 房间邮箱/应用被传输规则限制；先发给自己邮箱验证               |

---

## 九、二期规划（原 P1/P2 集中收口，条目不丢）

| 来源       | 功能                 | 说明                                                                         |
| -------- | ------------------ | -------------------------------------------------------------------------- |
| F1.5     | 设备 OTA 升级          | 推送升级（固件已确认支持）                                                              |
| F1.6     | 手动指定会议室            | 二维码不可用时兜底                                                                  |
| F1.7     | 设备远程重启             | REBOOT 指令                                                                  |
| F2.2     | Google 日历接入        | Admin SDK + Calendar API，域级委派                                              |
| F3.7     | 日程冲突处理             | 冲突/临时改期/取消应对增强                                                             |
| F3.8     | 自定义切换规则            | 提前量可配 + 延后恢复（拖堂场景）                                                         |
| F4.6     | 素材有效期              | 素材使用时间范围                                                                   |
| F5 白名单   | 敏感词白名单/自定义词库增强     | —                                                                          |
| F6 点餐全家桶 | 触发判断/提醒卡/确认/推荐/跳转  | 结束前 45 分钟 + "无既定安排"定义；平台矩阵（DoorDash/Glovo/GrabFood/美团等）只跳转不下单              |
| F7.3     | 设备播放日志             | 播放内容/切换记录上报                                                                |
| F7.4     | 链路健康看板             | 日历源状态/指令成功率/在线率                                                            |
| 设备端      | **Android APK 适配** | 一期 macOS 验证协议与状态机后换壳：WebView/Media3/WorkManager/Room/BOOT_COMPLETED，OTA 灰度 |

---

## 十、确认结论

**历史定稿（继续有效）**：

- ✅ 素材双轨制：公共素材运营/行政传、15 天 LRU；专属素材定会者免登录直传、绑 meeting_id、会后双侧清理
- ✅ 扫码绑定：门口码只含 room_id；device_id 设备开机画面展示；管理员手机扫码后台确认
- ✅ 双时刻：prepare_at 会前 10min / switch_at 会前 1min；自动切换唯一路径 = 设备本地定时
- ✅ 免登录链接：邮件单通道（Mail.Send）；不加 Calendars.ReadWrite
- ✅ 敏感判定前置：黑名单命中任何路径（含降级）只显示"会议中"
- ✅ 试点 4 城 4 时区带：上海 + 新加坡 / 巴塞罗那 / 美国
- ✅ 品牌资产：Logo 图标版（logo_icon）；色板 白 #FFFFFF / 紫 #7C3AED / 深紫 #4C1D95
- ✅ 不对接 Signage Pro 素材库，全新系统

**本次 v1.0 新增决策（2026-10-28）**：

- ✅ 全面转生产级，删除 4 天快速交付叙事；一期只做 P0
- ✅ 技术栈定稿：FastAPI / Pydantic / Alembic / PostgreSQL / Redis / Milvus / LangChain / **LangGraph（主编排）/ CrewAI（文案 crew）/ RAG / MinerU / DeepSeek**
- ✅ RAG 双链路 P0：素材语义检索（F4.5 升 P0）+ 品牌知识库（F4.9 新增）
- ✅ 设备端一期 = macOS（四态状态机 + 断网自愈 P0）；Android APK 二期适配
- ✅ F5.6 内容审核升 P0；F2.7 日历连接测试升 P0；F7.2 指令重试告警升 P0
- ✅ 点餐（F6 全家桶）等 P1/P2 集中挪「九、二期规划」

---

## 附：与竞品的差异化定位

| 对比项              | MAXHUB / 海信 | 本产品          |
| ---------------- | ----------- | ------------ |
| 会议纪要             | 已做透         | 不做（无差异化空间）   |
| 会议/标牌统一编排        | 无           | ✅ 核心差异化      |
| 多时区自适应（含 DST）    | 无           | ✅ 核心差异化      |
| 语义搜图 + 品牌知识库 RAG | 无           | ✅ 核心差异化      |
| 点餐/茶歇服务          | 无           | 二期（会议室最后一公里） |

**一句话定位：以「会议室那块屏」为核心，用日历驱动实现会议/标牌双场景自动切换，叠加 RAG 素材/知识库能力，专攻出海企业的多时区（含冬夏令时）与多会议室管理。**
