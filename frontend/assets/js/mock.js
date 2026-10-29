/* ============================================================
   Newline MeetCast · Mock 数据层
   规则（API 规范 §九 工程注意）：前端 Mock 只准复制规范返回示例
   → 核心结构严格照抄 Newline_MeetCast_API_Spec.md v0.2 的 JSON 示例，
     行数据可按 UI 稿 S3/S4 的演示行扩展（同构不同值）。
   用途：USE_MOCK=true 时 api.js 直接读本文件返回，前端可离线演示。
   ============================================================ */

// 心跳/回执演示时间取“相对当前时刻”，页面一打开就像真设备在线
function _agoIso(sec) {
  return new Date(Date.now() - sec * 1000).toISOString();
}

// ---- 设备列表（规范 §3.1 结构 + UI 稿 S3 五行演示数据） ----
const MOCK_DEVICES = [
  {
    device_id: "SH-A3-01-01",
    device_name: "device_sh_001",
    room_id: "room-a3-01",
    room_name: "Room-A3-01 · 上海总部 3F",
    status: "online",
    device_state: "MEETING",
    playing: "产品评审会 · 会议页",
    agent_version: "1.0.0",
    last_heartbeat: _agoIso(12),
    storage_used_mb: 34200
  },
  {
    device_id: "SH-B2-05-01",
    device_name: "device_sh_002",
    room_id: "room-b2-05",
    room_name: "Room-B2-05 · 上海总部 2F",
    status: "online",
    device_state: "IDLE",
    playing: "品牌宣传片 · 标牌页",
    agent_version: "1.0.0",
    last_heartbeat: _agoIso(8),
    storage_used_mb: 28100
  },
  {
    device_id: "SG-C1-02-01",
    device_name: "device_sg_001",
    room_id: "room-c1-02",
    room_name: "Room-C1-02 · 新加坡",
    status: "online",
    device_state: "IDLE",
    playing: "使用须知 · 标牌页",
    agent_version: "1.0.0",
    last_heartbeat: _agoIso(15),
    storage_used_mb: 19800
  },
  {
    device_id: "BCN-01-01",
    device_name: "device_bcn_001",
    room_id: "room-bcn-01",
    room_name: "Room-01 · 巴塞罗那",
    status: "online",
    device_state: "IDLE",
    playing: "品牌宣传片 · 标牌页",
    agent_version: "1.0.0",
    last_heartbeat: _agoIso(21),
    storage_used_mb: 22400
  },
  {
    device_id: "NYC-12F-01",
    device_name: "device_nyc_001",
    room_id: "room-nyc-12f",
    room_name: "Room-12F · 纽约",
    status: "offline",
    device_state: "IDLE",
    playing: "—",
    agent_version: "0.9.8",
    last_heartbeat: _agoIso(180),
    storage_used_mb: 15600
  }
];

// ---- 素材列表（规范 §4.1 结构；会议专属 6 + 公共 4） ----
const MOCK_MATERIALS = [
  {
    material_id: "mat_001",
    name: "Q3-review-cover.png",
    format: "png",
    size_mb: 2.4,
    url: "https://cdn.meetcast.app/m/mat_001.png",
    scope: "meeting",
    meeting_id: "meeting_123",
    uploaded_by: "organizer:zhangsan@honghe.com",
    expire_at: "2026-10-27T03:30:00Z",
    created_at: "2026-10-27T00:12:00Z"
  },
  {
    material_id: "mat_002",
    name: "agenda-v2.mp4",
    format: "mp4",
    size_mb: 48.1,
    url: "https://cdn.meetcast.app/m/mat_002.mp4",
    scope: "meeting",
    meeting_id: "meeting_123",
    uploaded_by: "organizer:zhangsan@honghe.com",
    expire_at: "2026-10-27T03:30:00Z",
    created_at: "2026-10-27T00:15:00Z"
  },
  {
    material_id: "mat_003",
    name: "roadmap-q4.png",
    format: "png",
    size_mb: 3.1,
    url: "https://cdn.meetcast.app/m/mat_003.png",
    scope: "meeting",
    meeting_id: "meeting_124",
    uploaded_by: "organizer:lisi@honghe.com",
    expire_at: "2026-10-27T01:30:00Z",
    created_at: "2026-10-26T11:40:00Z"
  },
  {
    material_id: "mat_004",
    name: "kickoff-intro.mp4",
    format: "mp4",
    size_mb: 86.3,
    url: "https://cdn.meetcast.app/m/mat_004.mp4",
    scope: "meeting",
    meeting_id: "meeting_125",
    uploaded_by: "organizer:wangwu@honghe.com",
    expire_at: "2026-10-26T09:30:00Z",
    created_at: "2026-10-26T06:02:00Z"
  },
  {
    material_id: "mat_005",
    name: "seating-map.png",
    format: "png",
    size_mb: 1.8,
    url: "https://cdn.meetcast.app/m/mat_005.png",
    scope: "meeting",
    meeting_id: "meeting_126",
    uploaded_by: "organizer:chenliu@honghe.com",
    expire_at: "2026-10-25T02:30:00Z",
    created_at: "2026-10-25T00:20:00Z"
  },
  {
    material_id: "mat_006",
    name: "demo-script.png",
    format: "png",
    size_mb: 0.9,
    url: "https://cdn.meetcast.app/m/mat_006.png",
    scope: "meeting",
    meeting_id: "meeting_127",
    uploaded_by: "organizer:zhaoqi@honghe.com",
    expire_at: "2026-10-24T07:30:00Z",
    created_at: "2026-10-24T02:10:00Z"
  },
  {
    material_id: "mat_010",
    name: "brand-film.mp4",
    format: "mp4",
    size_mb: 210.5,
    url: "https://cdn.meetcast.app/m/mat_010.mp4",
    scope: "public",
    meeting_id: null,
    uploaded_by: "admin:ops01",
    expire_at: null,
    created_at: "2026-10-20T03:00:00Z"
  },
  {
    material_id: "mat_011",
    name: "usage-guide.png",
    format: "png",
    size_mb: 1.2,
    url: "https://cdn.meetcast.app/m/mat_011.png",
    scope: "public",
    meeting_id: null,
    uploaded_by: "admin:ops01",
    expire_at: null,
    created_at: "2026-10-20T03:05:00Z"
  },
  {
    material_id: "mat_012",
    name: "culture-wall.png",
    format: "png",
    size_mb: 4.6,
    url: "https://cdn.meetcast.app/m/mat_012.png",
    scope: "public",
    meeting_id: null,
    uploaded_by: "admin:ops02",
    expire_at: null,
    created_at: "2026-10-18T08:30:00Z"
  },
  {
    material_id: "mat_013",
    name: "slogan-loop.mp3",
    format: "mp3",
    size_mb: 6.2,
    url: "https://cdn.meetcast.app/m/mat_013.mp3",
    scope: "public",
    meeting_id: null,
    uploaded_by: "admin:ops02",
    expire_at: null,
    created_at: "2026-10-18T08:35:00Z"
  }
];

// ---- 免登录上传页信息（规范 §5.1 示例原样） ----
const MOCK_UPLOAD_INFO = {
  meeting_id: "meeting_123",
  subject: "产品评审会",
  room_name: "Room-A3-01 · 上海总部 3F",
  start_time_utc: "2026-10-27T02:00:00Z",
  end_time_utc: "2026-10-27T03:00:00Z",
  timezone: "Asia/Shanghai",
  upload_deadline_utc: "2026-10-27T01:30:00Z",
  max_size_mb: 500,
  accepted_formats: ["png", "jpg", "mp4", "mp3"],
  uploaded: [
    { name: "Q3-review-cover.png", size_mb: 2.4, status: "ready" }
  ]
};

// ---- 日历源配置（规范 §6.1 示例原样） ----
const MOCK_CALENDAR_CONFIG = {
  provider: "m365",
  tenant: "honghe.onmicrosoft.com",
  service_account: "svc-meetcast@honghe.com",
  scopes: ["Calendars.Read", "Mail.Send"],
  connection_status: "connected",
  credential_expire_at: "2027-01-04T00:00:00Z",
  pull_policy: {
    schedule: { enabled: true, interval_min: 5, window_hours: 12 },
    link_gen: { enabled: true, interval_min: 30, window_days: 7 },
    dst_enabled: true,
    alert_enabled: true,
    google_enabled: false
  },
  alert_email: "it-admin@honghe.com"
};

// ---- 连接测试结果（规范 §6.3 示例原样） ----
const MOCK_CALENDAR_TEST = {
  auth_ok: true,
  rooms_synced: 4,
  api_latency_ms: 420,
  checked_at: "2026-10-27T04:30:00Z"
};

// ---- 指令审计（规范 §7.1 结构 + UI 稿补充演示行） ----
const MOCK_COMMANDS = [
  {
    command_id: "cmd_9f3a1b",
    device_id: "SH-A3-01-01",
    type: "PREPARE_MEETING",
    status: "ACKED",
    initiated_by: "system",
    created_at: "2026-10-27T01:50:00Z",
    acked_at: "2026-10-27T01:50:02Z",
    retry_count: 0
  },
  {
    command_id: "cmd_9f3a1c",
    device_id: "SH-A3-01-01",
    type: "REPLAY_DEFAULT",
    status: "ACKED",
    initiated_by: "system",
    created_at: "2026-10-27T03:00:00Z",
    acked_at: "2026-10-27T03:00:01Z",
    retry_count: 0
  },
  {
    command_id: "cmd_a1b2c3",
    device_id: "SH-B2-05-01",
    type: "SWITCH_CONTENT",
    status: "ACKED",
    initiated_by: "admin:ops01",
    created_at: "2026-10-27T02:10:00Z",
    acked_at: "2026-10-27T02:10:03Z",
    retry_count: 0
  },
  {
    command_id: "cmd_b4c5d6",
    device_id: "SH-A3-01-01",
    type: "CLEAN_MATERIAL",
    status: "ACKED",
    initiated_by: "meeting:meeting_122",
    created_at: "2026-10-27T01:35:00Z",
    acked_at: "2026-10-27T01:35:02Z",
    retry_count: 0
  },
  {
    command_id: "cmd_c7d8e9",
    device_id: "SG-C1-02-01",
    type: "SHOW_NOTICE",
    status: "SENT",
    initiated_by: "system",
    created_at: "2026-10-27T04:20:00Z",
    acked_at: null,
    retry_count: 1
  },
  {
    command_id: "cmd_d0e1f2",
    device_id: "NYC-12F-01",
    type: "PREPARE_MEETING",
    status: "TIMEOUT",
    initiated_by: "system",
    created_at: "2026-10-27T04:00:00Z",
    acked_at: null,
    retry_count: 3
  }
];

// ---- 绑定返回（规范 §3.2 示例原样） ----
const MOCK_BIND_RESULT = {
  device_id: "SH-A3-01-01",
  room_id: "room-a3-01",
  bound_at: "2026-10-27T04:30:00Z",
  effective_in_sec: 300
};

// ---- 会议室（规范未定义 rooms 接口；仅演示聚合，UI 稿 S7/S9 需要） ----
const MOCK_ROOMS = [
  {
    room_id: "room-a3-01",
    room_name: "Room-A3-01 · 上海总部 3F",
    room_email: "room-a3-01@honghe.com",
    timezone: "Asia/Shanghai",
    building: "上海总部",
    floor: "3F",
    capacity: 10,
    calendar_status: "connected",
    today_meetings: 3
  },
  {
    room_id: "room-b2-05",
    room_name: "Room-B2-05 · 上海总部 2F",
    room_email: "room-b2-05@honghe.com",
    timezone: "Asia/Shanghai",
    building: "上海总部",
    floor: "2F",
    capacity: 6,
    calendar_status: "connected",
    today_meetings: 5
  },
  {
    room_id: "room-c1-02",
    room_name: "Room-C1-02 · 新加坡",
    room_email: "room-c1-02@honghe.com",
    timezone: "Asia/Singapore",
    building: "新加坡办公室",
    floor: "1F",
    capacity: 8,
    calendar_status: "connected",
    today_meetings: 2
  },
  {
    room_id: "room-bcn-01",
    room_name: "Room-01 · 巴塞罗那",
    room_email: "room-bcn-01@honghe.com",
    timezone: "Europe/Madrid",
    building: "巴塞罗那办公室",
    floor: "1F",
    capacity: 12,
    calendar_status: "connected",
    today_meetings: 1
  },
  {
    room_id: "room-nyc-12f",
    room_name: "Room-12F · 纽约",
    room_email: "room-nyc-12f@honghe.com",
    timezone: "America/New_York",
    building: "纽约总部",
    floor: "12F",
    capacity: 16,
    calendar_status: "connected",
    today_meetings: 4
  }
];

// ---- 设备大屏页演示数据（display/*.html 用，对应 UI 稿 S1/S2/S6） ----
const MOCK_DISPLAY = {
  meeting: {
    room_label: "Room-A3-01 · 上海总部 3F",
    timezone: "Asia/Shanghai",
    subject: "产品评审会",
    start_local: "10:00",
    end_local: "11:00",
    organizer: "张三",
    attendees: ["张", "李", "王", "陈"],
    attendee_more: 2,
    agenda: [
      { no: "01", text: "Q3 复盘：指标与缺口" },
      { no: "02", text: "Q4 路线图对齐" },
      { no: "03", text: "资源与排期确认" }
    ],
    asset: { name: "Q3-review-cover.png", by: "本场专属素材 · 张三上传" },
    next: "11:30 周会"
  },
  signage: {
    brand_name: "Newline MeetCast",
    room_label: "Room-A3-01",
    timezone: "Asia/Shanghai",
    slogan_a: "智能会议室，",
    slogan_em: "从日程开始",
    slogan_b: "。",
    desc: "会议自动切换 · 会间展示企业形象 · 多时区自适应",
    banner_ghost: "Brand Film",
    up_next: "10:00 产品评审会",
    up_next_sub: "· 张三 · 6 人",
    status: "设备在线 · 日历已同步"
  },
  boot: {
    device_id: "SH-A3-01-01",
    device_name: "device_sh_003",
    firmware: "Android 15",
    agent_version: "v1.0.0"
  },
  meal: {
    end_local: "13:30",
    people: 6
  }
};
