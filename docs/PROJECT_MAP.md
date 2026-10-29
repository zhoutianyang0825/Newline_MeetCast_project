# Newline MeetCast · 项目地图（代码怎么组织 / 怎么跑 / 怎么演示）

> 一页看懂当前代码。**改参数去 `server/app/settings.py`，改协议先改 `docs/Newline_MeetCast_API_Spec.md`。**
>
> ⚠️ **现状口径（2026-10-28）**：本文件描述的是 **demo 态代码**（内存库、无 PG/Redis/Milvus/LangGraph）。
> 生产级目标态以 `Newline_MeetCast_PRD.md` v1.0 为准，差距与路线见其 §六里程碑；
> 设计决策见 `04_设计决策记录_Newline_MeetCast.md`。**M1（PG 生产化）动工时本文件全量重写。**

## 一、目录职责

```
Newline_MeetCast_project/
├─ docs/                     契约与需求（只读参考，不写代码）
│  ├─ Newline_MeetCast_PRD.md
│  ├─ Newline_MeetCast_API_Spec.md   ← 21 个接口的唯一事实源
│  ├─ PROJECT_MAP.md                 本文件
│  └─ DEVICE_APP.md                  macOS 设备端 App 说明
├─ brand/                    Logo（图标版 logo_icon 为定稿）
├─ design/                   UI 设计稿（meetcast_ui_v1.html）
├─ device-app/               ★ macOS 设备屏 App（Swift，可实测的设备端）
│  ├─ build.sh               构建：swiftc 编译 + 组装 .app + ad-hoc 签名
│  ├─ Sources/               状态机 / HTTP / 素材缓存 / WKWebView / 绑定 UI
│  └─ build/MeetCastScreen.app  产物（双击运行）
├─ frontend/                 静态页面，由后端 /ui 挂载
│  ├─ index.html             后台入口
│  ├─ upload.html            免登录上传页（URL token）
│  ├─ display/               大屏三页：boot / signage / meeting
│  └─ assets/js/             api.js（USE_MOCK=false）· admin.js · display.js · upload.js · mock.js
└─ server/
   ├─ app/
   │  ├─ settings.py         ★ 唯一配置入口（地址/提前量/配额/密钥/开关/Graph 凭据）
   │  ├─ main.py             应用入口：异常壳、lifespan（seed + 调度器）、静态挂载
   │  ├─ calendar_source.py  fixture 日历（锚定启动时刻）
   │  ├─ graph_client.py     ★ Graph 客户端（Mock/真双轨，缺凭据自动回落）
   │  ├─ scheduler.py        ★ 调度层：日历 → 状态机 → 指令 → 到期清理 → 发上传链接
   │  ├─ content.py          ★ 会议页内容生成（敏感判定 → LLM → 模板降级）
   │  ├─ llm.py              ★ LLM 调用（OpenAI 兼容，失败一律返回 None）
   │  ├─ layouts.py          三套固定版式 + LLM/规则自动选版
   │  ├─ tz.py               ★ 时区/DST 换算（zoneinfo，不手工加减）
   │  ├─ mailer.py           上传链接邮件（MAIL_MOCK 只落日志）
   │  ├─ users.py            口令 PBKDF2 + 用户行
   │  ├─ store.py            内存存储（room/device/command/meeting/material/token/user）
   │  ├─ schemas.py          Pydantic 模型（model 即文档）
   │  ├─ errors.py + response.py   错误码表 + 统一返回壳
   │  ├─ security.py         认证：设备 X-Device-Key / JWT（auth_user 与 auth_admin）
   │  ├─ jwtauth.py          HS256 签发与校验（纯标准库）
   │  ├─ files.py            上传校验与分块落盘 + 素材校验哈希
   │  └─ routers/            auth / device / admin_devices / admin_rooms / admin_materials / upload / admin_calendar / admin_commands
   ├─ scripts/               冒烟与工具（见下）
   └─ data/uploads/          素材落盘目录（/media 静态访问）
```

## 二、怎么跑

```bash
cd ~/zty-Developer/Newline_MeetCast_project/server
uv run python -m uvicorn app.main:app --port 8000
```

改了配置/代码要重启时，**用这个脚本，别用 `lsof -ti :8000 | xargs kill`**：

```bash
cd ~/zty-Developer/Newline_MeetCast_project
bash scripts/restart_server.sh
```

> ⚠️ 踩过的坑：`lsof -ti :8000` 会把**连接过** 8000 端口的客户端也列出来（不只是监听方），
> 设备 App 正在长轮询，会被一起 `kill` 掉——现象是“服务重启后 App 莫名消失、且无崩溃报告”。
> 脚本用 `-sTCP:LISTEN` 只取监听方，实测重启后 App 存活并自行重连。

- 接口文档：<http://localhost:8000/docs>
- **设备屏 App（唯一设备端形态）**：见 [`DEVICE_APP.md`](./DEVICE_APP.md)，构建后双击运行
- 后台：<http://localhost:8000/ui/index.html>

常用环境变量（都可在 `settings.py` 里找到对应默认值）：

| 变量 | 作用 | 默认 |
|---|---|---|
| `MEETCAST_FIRST_MEETING_MIN` | fixture 首场会议几分钟后开始（彩排调小） | 8 |
| `MEETCAST_TICK_SEC` | 调度节拍（秒） | 60 |
| `MEETCAST_PUBLIC_BASE` | 设备页/素材 url 前缀 | http://localhost:8000 |
| `MEETCAST_JWT_SECRET` | JWT 签名密钥 | dev 值 |
| `MEETCAST_CALENDAR_FAULT` | 日历测试故障注入（expired / rate_limited） | 空 |
| `MEETCAST_GRAPH_MOCK` | 1=fixture 假日历，0=真调 Microsoft Graph | 1 |
| `MEETCAST_GRAPH_TENANT_ID` / `_CLIENT_ID` / `_CLIENT_SECRET` | 真模式 app-only 凭据 | 空 |
| `MEETCAST_MAIL_MOCK` | 1=邮件只落日志不发真信 | 1 |
| `MEETCAST_LLM_BASE_URL` | LLM 网关（OpenAI 兼容，**必须带 `/v1`**） | `https://api.deepseek.com/v1` |
| `MEETCAST_LLM_API_KEY` | LLM 密钥；空 = 文案走模板、版式走规则 | 已配（见 `server/.env`） |
| `MEETCAST_LLM_MODEL` | 模型名 | `deepseek-chat`（**别用 `deepseek-v4-flash`**，推理模型 content 为空） |
| `MEETCAST_LLM_TIMEOUT` | 单次调用超时（秒），超时即降模板 | 6 |

> 真实密钥只写在 `server/.env`（已加入 `.gitignore`，不会入库）。
> 也兼容通用键名 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`（`MEETCAST_` 前缀优先）。

默认账号（种子）：`admin@honghe.com / admin123`（管理员）、`ops@honghe.com / ops123`（普通用户）。

## 三、怎么验证（只记一个命令）

```bash
cd server
uv run python scripts/run_all_smoke.py          # 12 套全跑（需服务在跑）
uv run python scripts/run_all_smoke.py --skip-http   # 只跑不需 HTTP 的那几套
```

> ⚠️ **跑冒烟前先停设备 App**：`mock_device.py` 用 `SH-A3-01-01` 的同一把密钥做长轮询，
> 和 App 是**竞争消费**——指令被谁取到不确定，会出现随机失败。
> ```bash
> pkill -f "MeetCastScreen.app/Contents/MacOS/MeetCastScreen"   # 跑之前
> open device-app/build/MeetCastScreen.app                      # 跑完再开
> ```
> ⚠️ **冒烟会改状态**：`mock_admin.py` 会解绑 `SH-A3-01-01`，`mock_device_extra.py` 会复位 `SH-A3-01-02`。
> 跑完想继续演示，先把设备绑回去（后台「设备 → 绑定新设备」选 Room-A3-01，或调 `POST /api/admin/devices/bind`）。

单套脚本用途：

| 脚本 | 覆盖 |
|---|---|
| `mock_scheduler.py` | 日历→状态机→指令（含幂等、取消会议、跨时区） |
| `mock_content.py` | 内容生成 + 敏感脱敏 + 本地时间 |
| `mock_tz.py` | 美欧 DST 切换日 + 两段错位窗口 + 跨切换会议 |
| `mock_lifecycle.py` | 到期清理 + 标签筛选 + 时段标牌 + 自动选版式 |
| `mock_graph.py` | Graph Mock 双轨 + 上传链接自动生成 + 邮件落库 |
| `mock_llm.py` | LLM 调用/解析/降级/敏感隔离/选版式（自带假网关，不需真 Key） |
| `mock_p0_gap.py` | 会议室二维码 + 素材分类 + 大屏 slot/layout 参数 |
| `mock_auth.py` | 口令校验 + 管理员/普通用户角色 |
| `mock_device.py` | 设备端基础 3 接口（poll/ack/heartbeat） |
| `mock_device_extra.py` | 设备端档案/日程/素材 3 接口（profile/schedule/materials） |
| `mock_admin.py` | 管理端设备 3 接口（list/bind/unbind） |
| `mock_admin_extra.py` | 素材 3 + 免登录上传 2 + 日历 3 + 运维 2 |
| `make_admin_token.py` | 打印 dev 管理员 JWT（有登录接口后仅调试用） |

## 四、数据从哪来（避免两套数据源）

```
calendar_source.fixture_events()  ← 唯一会议数据源（锚定进程启动时刻）
        ↓  store.upsert_meeting()
    store.meetings  ──► scheduler 生成 PREPARE_MEETING / REPLAY_DEFAULT
        ↓                      ↓
  上传 token / 会议页 url    指令队列 ──► 设备 poll ──► ack
```

**不要**再在 `store.seed()` 里手写会议；要加演示场景就往 `calendar_source` 的 fixture 里加。

## 五、设备端形态

只有一种：**macOS App**（`device-app/`）——绑定/心跳/轮询/日程/素材落盘/LRU/离线兜底/开机自启。

> 原 PWA 网页设备屏（device.html 包壳方案）已整体移除；安卓 APK 是 M2 真机交付物，
> **未写一行代码**，属生产阶段任务（需 JDK17 + Android SDK + 真机），见「当前边界」。

## 六、测试账户总表（就四类）

- **管理员**：`admin@honghe.com / admin123` —— seed 灌入，后台全部页面与接口
- **运营（普通用户）**：`ops@honghe.com / ops123` —— seed 灌入，与 admin **同一个后台、同一个登录口**，仅权限不同：
  - `auth_admin`（设备/素材/日历/指令等管理接口）→ 只有 admin 放行，ops 拿 401/403
  - `auth_user`（看会议室/设备、传素材等读+传接口）→ 两种角色都放行
- **设备**：演示密钥表在 [`DEVICE_APP.md`](./DEVICE_APP.md)（种子内置，重启不变）—— App 绑定页输入
- **定会者**：**零账户** —— 上传链接里的 token 即凭据（`organizer_email` 只做审计归属）

> ⚠️ 内存库：每次重启服务全部数据重置，绑定关系、上传 token、素材都要重来。

## 七、PRD 场景 → 测试路径（速查）

- **A 进场自动亮会**：设备已绑 → 等 fixture 首场会（启动后 8 分钟）前 10 分钟 → App 自动切会议页；会后回标牌
- **B 安装绑定**：App 输设备密钥 → 后台「设备 → 绑定」选房间（或 `POST /api/admin/devices/bind`）→ 5 分钟内生效
- **C 内容更换**：管理员后台上传公共素材 → App 每 5 分钟素材循环拉到
- **D 断网自愈**：停服务 30 秒再起（用 `restart_server.sh`）→ App 不退出、恢复当秒重连
- **E 免登录直传**：等调度器 tick 打出 `[mail:mock] 链接：...` → 浏览器开链接 → 直接传文件 → 后台 `scope=meeting` 可见；会后自动清理

## 八、真实 vs Mock 功能清单（哪些能真测、哪些只能 mock）

- ✅ **真实可测**：登录/JWT、设备密钥认证、绑定/心跳/长轮询/ACK、到点自动切屏与恢复标牌、
  素材上传/列表/删除/标签、免登录上传全链路、会后清理下发、时区/DST 换算、
  LLM 文案与选版式（真调 DeepSeek，失败自动降模板）、PBKDF2 口令
- 🟡 **只能 Mock**（各留真模式开关，凭据就绪即切真）：
  - **M365 日历**（`MEETCAST_GRAPH_MOCK=1`）：现在用 fixture 假日历（锚定启动时刻）。
    切真需 Azure AD 应用注册凭据（`MEETCAST_GRAPH_TENANT_ID/_CLIENT_ID/_CLIENT_SECRET`，app-only `Calendars.Read`）+ 会议室邮箱
  - **邮件投递**（`MEETCAST_MAIL_MOCK=1`）：上传链接只落服务日志，不发真邮件。
    切真需 M365 邮箱凭据（同一套 app-only，`Mail.Send`）

## 九、M365 真实接入时的账户模型（试点前须知）

- **服务账户只有一个**：Azure AD 应用注册（app-only），服务端拿它统一读所有会议室邮箱的日历——
  不需要给每个定会者发账号、不需要他们授权
- **定会者侧零成本**：照常在 Outlook/M365 定会，把会议室（房间邮箱）加进与会人即可，
  系统轮询房间邮箱 `calendarView` 自动发现会议
- **上传链接触达**：真模式下按 `organizer_email` 发真邮件；mock 模式下去服务日志拿链接

## 十、当前边界（还没做的）

| 缺什么 | 位置 | 说明 |
|---|---|---|
| 真机 APK（M2） | — | 设备端逻辑已由 macOS App 实测覆盖；APK 需先装 JDK17 + Android SDK |
| 真 M365 联调 | `graph_client.py` | 客户端代码已就绪（client_credentials + calendarView + places），缺实账户凭据，M6 试点验证 |
| LLM 文案（F5.1） | `content.py` | ✅ 已接真模型（deepseek-chat）；模板只是降级兜底 |
| 数据持久化 | `store.py` | 内存版，重启即清空，后续换 PostgreSQL |
| 点餐提醒（P1） | — | 未做 |

## 十一、P0 覆盖情况（后端口径）

| PRD | 状态 | 落点 |
|---|---|---|
| F1.1~F1.4 绑定/心跳/列表/解绑 | ✅ | `routers/admin_devices.py`、`routers/device.py` |
| F2.3 会议室同步 | ✅ Mock／真接待验 | `graph_client.sync_rooms` |
| F2.4 编排拉取 + 链接生成 | ✅ | `scheduler.tick` / `ensure_upload_links` |
| F2.5 时区 + DST | ✅ | `tz.py` + `mock_tz.py` 11 项矩阵 |
| F3.1~F3.3 状态机/双时刻/预拉取 | ✅ | `scheduler.evaluate_device` |
| F3.4 时段标牌 | ✅ | `scheduler.signage_slot` |
| F3.5 + F4.3 自动选版式 + 兜底版式 | ✅ 规则版 | `layouts.py` |
| F4.1/F4.2 上传/列表/删除/标签 | ✅ | `routers/admin_materials.py` |
| F4.7 免登录上传 + 邮件 | ✅（邮件 Mock） | `routers/upload.py` + `mailer.py` |
| F4.8 会后清理 | ✅ | `scheduler.expire_materials` |
| F5.1~F5.5 会议页生成/脱敏/降级 | ✅ LLM 版 | `content.py`（真 DeepSeek，超时/失败降模板，minimal 只归敏感） |
| F8.1/F8.2/F8.3 账号与审计 | ✅ | `routers/auth.py`、`security.py` |
| F8.4 app-only 服务账号 | 🟡 代码就绪待凭据 | `graph_client` |
| F2.1 真 M365 接入 | 🟡 待试点验证 | 同上 |
