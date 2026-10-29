# MeetCast 设备屏 · macOS App

> 这是 **M2「设备端」在 macOS 上的可实测实现**，不是安卓 APK 的替代交付物。
> 协议完全一致（同一套 `poll / ack / heartbeat / profile / schedule / materials`），
> 换到安卓只是把"WKWebView"换成"Android WebView"、把"LaunchAgent"换成"BOOT_COMPLETED"。

## 一、为什么先做 macOS 版

| 原因 | 说明 |
|---|---|
| 能真跑真测 | 安卓需要 JDK17 + Android SDK + 真机；macOS 本机 `swiftc` 直接编译运行 |
| 验证的是逻辑不是壳 | 心跳、长轮询、指令状态机、素材落盘、LRU、断网兜底——这些与平台无关 |
| 交付快 | 不装完整 Xcode（省 10GB+）：`swiftc` + 手工 `.app` + ad-hoc 签名即可双击运行 |

**不具备的能力**（只能靠真机验证）：8 小时连续运行稳定性、128G 磁盘 LRU 压测、真实断网恢复、固件级 kiosk。

## 二、构建与启动

```bash
cd ~/zty-Developer/Newline_MeetCast_project

# ① 先起服务
cd server && uv run python -m uvicorn app.main:app --port 8000

# ② 构建 App（另开终端）
cd .. && bash device-app/build.sh
open device-app/build/MeetCastScreen.app
```

产物：`device-app/build/MeetCastScreen.app`（约 1MB）。

改了 Swift 源码后重跑 `build.sh` 即可；`build.sh run` 一步构建并启动。

## 三、绑定（设备端"注册"）

```
t1  App 启动 → 读 ~/Library/Application Support/MeetCastDevice/device.json
t2  没有凭据 → 显示绑定页，输入设备密钥
t3  GET /api/device/profile 校验密钥
t4  通过 → 落盘 device_id（服务端由密钥反查，不用手填）
t5  有凭据 → 直接自检进工作态（重启不需要人工干预）
```

**演示密钥**（种子数据）：

| 设备 | 密钥 | 初始状态 |
|---|---|---|
| `SH-A3-01-01` | `dev-key-sh-a3-01-01` | 已绑定 room-a3-01 |
| `SH-A3-01-02` | `dev-key-sh-a3-01-02` | 未绑定（可演练绑定/解绑） |

⚠️ **一个密钥同时只能有一个客户端**：服务端 `mock_device.py` 冒烟脚本与 App 共用 `SH-A3-01-01` 的密钥，同时跑会互相抢指令（长轮询是竞争消费）。跑冒烟前先停 App，跑完再开。

## 四、设备端 P0 功能对照

| PRD | 功能 | 实现位置 | 状态 |
|---|---|---|---|
| F1.1 | 绑定注册（设备侧） | 绑定页 + `GET /profile` | ✅ |
| F1.2 | 心跳 30s | `loopHeartbeat()` | ✅ |
| F1.3 | 状态 / 播放内容 / 存储占用上报 | `heartbeat()` 带真实 `storage_used_mb` | ✅ |
| F1.4 | 解绑感知 | `refreshProfileOnly()` → `bound=false` 切未绑定页 | ✅ |
| F2.4 | 拉取会议日历 | `GET /schedule`（60s 刷新） | ✅ |
| F3.1 | 指令状态机 | `handle()` 分派 4 类指令；四态上报 IDLE / MEETING_PREP / MEETING / FALLBACK | ✅ |
| F3.2 | 双时刻切屏 | `performPrepare()` 按 `switch_at` 本地定时 | ✅ |
| F3.3 | 预拉取 | 收到指令先同步素材 + **预缓存会议页 HTML**，到点才切屏；断网用缓存渲染 | ✅ |
| F4.1 | 素材下载 + 校验 | `MediaCache.sync()` + SHA256 比对 | ✅ |
| F4.4 | 15 天 LRU | `MediaCache.purgeExpired()` | ✅ |
| F4.8 | 专属素材到期清理 | `CLEAN_MATERIAL` → 删本地文件 | ✅ |
| A1 | 开机展示 device_id | 未绑定页大字 + 标牌页底部信息条 | ✅ |
| A4 | 页面渲染 | WKWebView 加载 `/ui/display/*.html` | ✅ |
| 断网不黑屏 | 本地兜底页 + **每 20 秒重试原地址**（`WebDisplay.Coordinator.scheduleRetry`） | ✅ |
| 开机自启 | LaunchAgent | `scripts/install_autostart.sh` | ✅（脚本待执行） |

## 五、目录结构

```
device-app/
├── build.sh                  构建：swiftc 编译 + 组装 .app + ad-hoc 签名
├── Sources/
│   ├── App.swift             入口：常亮 + kiosk + 窗口
│   ├── AppUI.swift           绑定页 / 未绑定页 / 屏幕页 / 日志面板
│   ├── DeviceAgent.swift     ★ 状态机：心跳 / 轮询 / 指令执行 / 切屏
│   ├── APIClient.swift       HTTP 客户端（长轮询独立超时）
│   ├── MediaCache.swift      素材下载 / 校验 / LRU
│   ├── WebDisplay.swift      WKWebView + 断网兜底
│   ├── DeviceConfig.swift    凭据持久化
│   ├── Models.swift          服务端数据结构
│   └── Settings.swift        唯一配置入口
└── build/MeetCastScreen.app  产物
```

## 六、本地数据位置

| 内容 | 路径 |
|---|---|
| 凭据（device_id / key / 校时偏差） | `~/Library/Application Support/MeetCastDevice/device.json` |
| 素材缓存 | `~/Library/Application Support/MeetCastDevice/cache/` |
| 会议页 HTML 预缓存 | `~/Library/Application Support/MeetCastDevice/pages/` |
| 运行日志（可 tail） | `~/Library/Application Support/MeetCastDevice/device.log` |

> `pages/` **必须与 `cache/` 平级、不能放在 `cache/` 里面**：素材同步的“清单外清理”和
> 15 天 LRU 都是遍历 `cache/` 删文件，页面缓存若放进去会被误删（实测日志出现过
> `清理清单外文件：pages`，F3.3 的预缓存被自己的清理任务干掉）。另外两处清理现在
> 都加了“遇到子目录直接跳过”的防御。

现场排障：`tail -f ~/Library/Application\ Support/MeetCastDevice/device.log`

## 七、开机自启（需你执行）

```bash
cd ~/zty-Developer/Newline_MeetCast_project
bash scripts/install_autostart.sh install    # 安装（登录即启动、崩溃自动重启）
bash scripts/install_autostart.sh status     # 查看
bash scripts/install_autostart.sh uninstall  # 卸载
```

写的是 `~/Library/LaunchAgents/com.newline.meetcast.screen.plist`，卸载即删。

## 八、已验证 vs 未验证

**已实测通过**（2026-10-27，本机 macOS 27 + Swift 6.3）：

| 能力 | 证据 |
|---|---|
| 绑定态自检 | 后台显示 `online`、`agent_version=1.0.0-macos`、`storage_used_mb` 为真实值 |
| 指令下发 → 回执 | 管理端 `switch` 下发后 **2 秒内**被取走并回执 `ACKED` |
| 素材预拉取 | 18KB PNG 落地，本地 SHA256 与服务端 `checksum` 完全一致 |
| 页面渲染 | 服务端日志可见 `GET /ui/display/meeting.html?...`（带版式/参会人/本地时间）与 `signage.html?slot=evening&next=19:43 – 20:43 产品评审会` |
| **双时刻切屏** | `预备完成，将在 59s 后切屏` → `已切到会议页`（`switch_at` 到点才切，预拉取在前） |
| **四态上报** | 实测后台依次看到 `MEETING_PREP`（预备中）→ `MEETING`（切屏后）→ `FALLBACK`（页面加载失败）→ 恢复 `MEETING` |
| **会议页预缓存** | `会议页已预缓存，断网可显示`，产物 `pages/meeting_a3_01_0.html`（3438 字节） |
| **断网自愈** | 服务停 35 秒期间 `轮询失败：Could not connect`，进程不退出；服务恢复当秒重连并重新收到 PREPARE |
| **降级页自动重试** | 加载失败进 FALLBACK 后，每 20 秒重试原地址（`Settings.pageRetryInterval`）：实测 23:20:34 失败 → 23:21:14 目标恢复即自动加载成功 → 日志 `页面已恢复，退出 FALLBACK` → 后台状态回到 `MEETING`，且成功后再无重复请求 |
| **会议结束回标牌** | `收到指令 REPLAY_DEFAULT` → 立即回执 → 屏幕切回标牌页 |
| 连续无人值守 | 19:41 启动 → 22:13 仍在跑，自动完成 **两轮完整会议周期**（预备→切屏→结束回标牌→下一场预备→切屏） |
| 断网兜底 | 服务被停期间 App 未崩溃，日志记失败并持续重试，服务恢复后自动续上心跳 |

无人值守 2.5 小时的真实日志节选：

```
[19:41:34] 收到指令 PREPARE_MEETING → 预备完成，将在 418s 后切屏（meeting_a3_01_0）
[19:48:39] 已切到会议页：meeting_a3_01_0
[20:49:33] 收到指令 REPLAY_DEFAULT → 屏幕切回标牌          ← 会议结束自动恢复
[21:06:33] 收到指令 PREPARE_MEETING → 540s 后切屏（meeting_a3_01_1）
[21:15:35] 已切到会议页：meeting_a3_01_1                    ← 第二场，仍在会议中
```

**未验证**（需真机或更长时间）：

- 8 小时以上连续运行、内存/文件句柄增长
- 大文件（>100MB 视频）下载与 `sha256-partial` 校验
- 15 天 LRU 的真实触发（只能改 mtime 模拟）
- `CLEAN_MATERIAL` 专属素材清理（需等一场带专属素材的会结束）
- macOS 无安卓前台服务，长期保活弱于真机固件

## 九、与安卓 APK 的关系

| | macOS App（本目录） | 安卓 APK（M2 未开工） |
|---|---|---|
| 归属 | 4 天快速交付计划的设备端实现 | 正常研发周期的 M2 交付物 |
| 能装会议室屏 | ❌ | ✅ |
| 协议 | 完全一致 | 完全一致 |
| 可复用 | 状态机 / 缓存策略 / 校验口径可直接翻译 | — |

**结论**：macOS 版把"设备端逻辑"验证到位了；安卓版是把这套逻辑翻译成 Kotlin + 真机保活能力，属独立工作量。

## 十、接 AI（LLM）

**当前状态：已接入并跑通真模型**（`server/.env` 已配好，密钥迁自 `HHT-PrismEdu_project/.env`）。

```
MEETCAST_LLM_BASE_URL=https://api.deepseek.com/v1
MEETCAST_LLM_MODEL=deepseek-chat        ← 不要用 deepseek-v4-flash（推理模型，content 为空）
MEETCAST_LLM_TIMEOUT=6
```

换 Key / 换网关：编辑 `server/.env` 后重启服务，代码一行不用改。新机器首次：

```bash
cd ~/zty-Developer/Newline_MeetCast_project/server
cp .env.example .env      # 再填 MEETCAST_LLM_API_KEY（DeepSeek / 阿里百炼 / vLLM 均可，OpenAI 兼容）
```

| 没配 Key | 配了 Key（当前状态） |
|---|---|
| 文案走模板（"6 位同事已就位…"） | **模型生成引导语**（实测 0.7~1.1s，`degraded=llm`） |
| 版式走规则（≥6 人 focus） | **模型按标题/人数/文案选版式**，白名单校验后落地 `?layout=` |
| 敏感会议直接「会议中」 | 同左，且**完全不调模型**（`chat_json` 调用 0 次，已加断言） |

实测样本（2026-10-27 22:47，真模型输出进了实际下发链路）：

```
[llm] copy ok 1096ms model=deepseek-chat
[llm] layout ok 1033ms model=deepseek-chat
content_url → subject=产品评审会 & tagline=产品评审会即将开始，请各位有序入场就座 & layout=standard
```

**降级铁律不变**：模型超时/报错/输出非 JSON → 自动回落模板，屏幕绝不空白（`app/llm.py` 里任何异常都返回 `None`）。

不烧真钱验证链路：`uv run python scripts/mock_llm.py` 会起一个假网关，
把「调用 → 解析 → 校验 → 降级 → 敏感隔离」全跑一遍（6 组断言，不消耗额度）。

