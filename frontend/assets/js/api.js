/* ============================================================
   Newline MeetCast · API 客户端
   契约：Newline_MeetCast_API_Spec.md v0.2（前后端单一事实源）
   统一返回壳：{ code, message, data }；code=0 成功，非 0 见错误码表
   双模式：
     USE_MOCK=true  → 读 mock.js（前端并行对 Mock，规范 §九 t4）
     USE_MOCK=false → fetch 真实后端（开发期 http://localhost:8000/api）
   认证：管理端 Authorization: Bearer <JWT>（localStorage: meetcast_token）
         免登录：URL {token}；设备端 X-Device-Key（设备模拟器用，页面不走）
   ============================================================ */

// ---- 运行配置：联调真后端时把 USE_MOCK 改 false ----
const API_BASE = "http://localhost:8000/api";
const USE_MOCK = false;

// ---- 全局错误码（规范 §1.2） ----
const API_ERRORS = {
  1001: "参数校验失败",
  1002: "未认证",
  1003: "无权限",
  1004: "token 无效",
  2001: "设备不存在",
  2002: "设备已绑定",
  2003: "会议室不存在",
  2004: "素材不存在",
  2005: "格式不支持",
  2006: "上传已截止",
  2007: "文件超限",
  2008: "会议室已绑定其他设备",
  2009: "设备离线",
  2010: "会议不存在或已取消",
  2011: "素材配额超限",
  3001: "日历源凭证失效",
  3002: "日历 API 超限",
  4001: "指令下发超时",
  5000: "服务内部错误"
};

// ---- API 错误对象：携带业务码，页面按 code 分支处理 ----
class ApiError extends Error {
  constructor(code, message) {
    super(message || API_ERRORS[code] || "未知错误");
    this.code = code;
  }
}

// ---- 读写 JWT（管理端） ----
function getToken() {
  return localStorage.getItem("meetcast_token") || "";
}
function setToken(token) {
  localStorage.setItem("meetcast_token", token);
}

// ---- 登录：邮箱 + 密码 → JWT（POST /api/auth/login，规范 §一） ----
async function loginRequest(email, password) {
  return apiRequest("/auth/login", { method: "POST", json: { email: email, password: password } });
}

// ---- 当前身份：GET /api/auth/me（刷新页面时恢复显示名/角色） ----
async function meRequest() {
  return apiRequest("/auth/me");
}

// ---- mock 延迟：模拟网络往返，页面能看到 loading 态 ----
function mockDelay(ms = 260) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---- mock 分页：把数组切成 { items, total, page, page_size } ----
function mockPage(items, page, pageSize) {
  const p = page || 1;
  const size = pageSize || 20;
  const start = (p - 1) * size;
  return {
    items: items.slice(start, start + size),
    total: items.length,
    page: p,
    page_size: size
  };
}

// ---- 统一请求：解析 {code,message,data} 壳，非 0 抛 ApiError ----
async function apiRequest(path, options = {}) {
  const url = API_BASE + path;
  const headers = { Accept: "application/json" };
  const token = getToken();
  if (token) {
    headers.Authorization = "Bearer " + token;
  }
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const resp = await fetch(url, {
    method: options.method || "GET",
    headers: headers,
    body: options.json !== undefined ? JSON.stringify(options.json) : options.body
  });
  let body;
  try {
    body = await resp.json();
  } catch (_e) {
    throw new ApiError(5000, "响应不是合法 JSON（HTTP " + resp.status + "）");
  }
  if (body.code !== 0) {
    throw new ApiError(body.code, body.message);
  }
  return body.data;
}

// ---- multipart 上传（带进度，XMLHttpRequest；fetch 不便报进度） ----
function apiUpload(path, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", API_BASE + path);
    const token = getToken();
    if (token) {
      xhr.setRequestHeader("Authorization", "Bearer " + token);
    }
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      try {
        const body = JSON.parse(xhr.responseText);
        if (body.code !== 0) {
          reject(new ApiError(body.code, body.message));
          return;
        }
        resolve(body.data);
      } catch (_e) {
        reject(new ApiError(5000, "上传响应解析失败"));
      }
    };
    xhr.onerror = () => reject(new ApiError(5000, "网络错误，上传失败"));
    xhr.send(formData);
  });
}

/* ============================================================
   管理端 · 设备（规范 §三）
   ============================================================ */

// GET /api/admin/devices — 设备列表（F1.3）
async function adminListDevices(params = {}) {
  const { status, page, page_size } = params;
  if (USE_MOCK) {
    await mockDelay();
    let rows = MOCK_DEVICES.slice();
    if (status && status !== "all") {
      rows = rows.filter((d) => d.status === status);
    }
    return mockPage(rows, page, page_size);
  }
  const q = new URLSearchParams();
  if (status && status !== "all") q.set("status", status);
  if (page) q.set("page", page);
  if (page_size) q.set("page_size", page_size);
  return apiRequest("/admin/devices?" + q.toString());
}

// POST /api/admin/devices/bind — 绑定设备（F1.1）
async function adminBindDevice(deviceId, roomId, force = false) {
  if (USE_MOCK) {
    await mockDelay();
    const dev = MOCK_DEVICES.find((d) => d.device_id === deviceId);
    if (!dev) throw new ApiError(2001);
    const room = MOCK_ROOMS.find((r) => r.room_id === roomId);
    if (!room) throw new ApiError(2003);
    if (dev.room_id && !force) throw new ApiError(2002);
    const occupied = MOCK_DEVICES.find(
      (d) => d.room_id === roomId && d.device_id !== deviceId
    );
    if (occupied && !force) throw new ApiError(2008);
    dev.room_id = roomId;
    dev.room_name = room.room_name;
    return {
      device_id: deviceId,
      room_id: roomId,
      bound_at: new Date().toISOString(),
      effective_in_sec: 300
    };
  }
  return apiRequest("/admin/devices/bind", {
    method: "POST",
    json: { device_id: deviceId, room_id: roomId, force: force }
  });
}

// POST /api/admin/devices/unbind — 解绑（F1.4）
async function adminUnbindDevice(deviceId) {
  if (USE_MOCK) {
    await mockDelay();
    const dev = MOCK_DEVICES.find((d) => d.device_id === deviceId);
    if (!dev) throw new ApiError(2001);
    dev.room_id = null;
    dev.room_name = "未绑定";
    return null;
  }
  return apiRequest("/admin/devices/unbind", {
    method: "POST",
    json: { device_id: deviceId }
  });
}

/* ============================================================
   管理端 · 素材（规范 §四）
   ============================================================ */

// GET /api/admin/materials — 素材列表（F4.2）
async function adminListMaterials(params = {}) {
  const { scope, meeting_id, category, tag, page, page_size } = params;
  if (USE_MOCK) {
    await mockDelay();
    let rows = MOCK_MATERIALS.slice();
    if (scope && scope !== "all") {
      rows = rows.filter((m) => m.scope === scope);
    }
    if (meeting_id) {
      rows = rows.filter((m) => m.meeting_id === meeting_id);
    }
    if (category && category !== "all") {
      rows = rows.filter((m) => m.category === category);
    }
    if (tag) {
      rows = rows.filter((m) => (m.tags || []).includes(tag));
    }
    return mockPage(rows, page, page_size);
  }
  const q = new URLSearchParams();
  if (scope && scope !== "all") q.set("scope", scope);
  if (meeting_id) q.set("meeting_id", meeting_id);
  if (category && category !== "all") q.set("category", category);
  if (tag) q.set("tag", tag);
  if (page) q.set("page", page);
  if (page_size) q.set("page_size", page_size);
  return apiRequest("/admin/materials?" + q.toString());
}

// POST /api/admin/materials — 公共素材上传（F4.1）
async function adminUploadMaterial(file, tags, onProgress, category) {
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  const accepted = ["png", "jpg", "jpeg", "mp4", "mp3"];
  if (USE_MOCK) {
    await mockDelay(500);
    if (!accepted.includes(ext)) throw new ApiError(2005);
    if (file.size > 500 * 1024 * 1024) throw new ApiError(2007);
    if (onProgress) onProgress(100);
    const item = {
      material_id: "mat_" + Math.random().toString(36).slice(2, 8),
      name: file.name,
      format: ext === "jpeg" ? "jpg" : ext,
      size_mb: Math.round((file.size / 1024 / 1024) * 10) / 10,
      url: "https://cdn.meetcast.app/m/mock-" + file.name,
      scope: "public",
      meeting_id: null,
      category: category || "other",
      tags: (tags || "").split(",").map((s) => s.trim()).filter(Boolean),
      uploaded_by: "admin:" + (getToken() || "demo"),
      expire_at: null,
      created_at: new Date().toISOString()
    };
    MOCK_MATERIALS.unshift(item);
    return { material_id: item.material_id, url: item.url };
  }
  const form = new FormData();
  form.append("file", file);
  form.append("scope", "public");
  form.append("category", category || "other");
  if (tags) form.append("tags", tags);
  return apiUpload("/admin/materials", form, onProgress);
}

// DELETE /api/admin/materials/{material_id} — 删除（F4.2）
async function adminDeleteMaterial(materialId) {
  if (USE_MOCK) {
    await mockDelay();
    const idx = MOCK_MATERIALS.findIndex((m) => m.material_id === materialId);
    if (idx < 0) throw new ApiError(2004);
    MOCK_MATERIALS.splice(idx, 1);
    return null;
  }
  return apiRequest("/admin/materials/" + encodeURIComponent(materialId), {
    method: "DELETE"
  });
}

/* ============================================================
   免登录上传（规范 §五）· URL token 认证
   ============================================================ */

// GET /api/upload/{token} — 会议与上传信息
async function uploadGetInfo(token) {
  if (USE_MOCK) {
    await mockDelay();
    if (!token || token === "invalid") throw new ApiError(1004);
    return Object.assign({}, MOCK_UPLOAD_INFO);
  }
  return apiRequest("/upload/" + encodeURIComponent(token));
}

// POST /api/upload/{token} — 上传专属素材
async function uploadSendFile(token, file, onProgress) {
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  const accepted = ["png", "jpg", "jpeg", "mp4", "mp3"];
  if (USE_MOCK) {
    await mockDelay(600);
    if (!token || token === "invalid") throw new ApiError(1004);
    if (!accepted.includes(ext)) throw new ApiError(2005);
    if (file.size > 500 * 1024 * 1024) throw new ApiError(2007);
    const deadline = Date.parse(MOCK_UPLOAD_INFO.upload_deadline_utc);
    if (Date.now() > deadline) throw new ApiError(2006);
    if (onProgress) onProgress(100);
    const item = {
      name: file.name,
      size_mb: Math.round((file.size / 1024 / 1024) * 10) / 10,
      status: "ready"
    };
    MOCK_UPLOAD_INFO.uploaded.push(item);
    return {
      material_id: "mat_" + Math.random().toString(36).slice(2, 8),
      name: item.name,
      status: item.status
    };
  }
  const form = new FormData();
  form.append("file", file);
  return apiUpload("/upload/" + encodeURIComponent(token), form, onProgress);
}

/* ============================================================
   管理端 · 日历源（规范 §六）
   ============================================================ */

// GET /api/admin/calendar/config — 读取配置
async function adminGetCalendarConfig() {
  if (USE_MOCK) {
    await mockDelay();
    return JSON.parse(JSON.stringify(MOCK_CALENDAR_CONFIG));
  }
  return apiRequest("/admin/calendar/config");
}

// PUT /api/admin/calendar/config — 保存配置（scopes/connection_status/credential_expire_at 不可改）
async function adminSaveCalendarConfig(cfg) {
  if (USE_MOCK) {
    await mockDelay();
    Object.assign(MOCK_CALENDAR_CONFIG, {
      alert_email: cfg.alert_email,
      pull_policy: cfg.pull_policy
    });
    return null;
  }
  const body = {
    provider: cfg.provider,
    tenant: cfg.tenant,
    service_account: cfg.service_account,
    pull_policy: cfg.pull_policy,
    alert_email: cfg.alert_email
  };
  return apiRequest("/admin/calendar/config", { method: "PUT", json: body });
}

// POST /api/admin/calendar/test — 连接测试（F2.7）
async function adminTestCalendar() {
  if (USE_MOCK) {
    await mockDelay(800);
    return Object.assign({}, MOCK_CALENDAR_TEST, {
      checked_at: new Date().toISOString()
    });
  }
  return apiRequest("/admin/calendar/test", { method: "POST", json: {} });
}

/* ============================================================
   管理端 · 运维（规范 §七）
   ============================================================ */

// GET /api/admin/commands — 指令审计记录（F7.1 / F8.3）
async function adminListCommands(params = {}) {
  const { device_id, initiated_by, page, page_size } = params;
  if (USE_MOCK) {
    await mockDelay();
    let rows = MOCK_COMMANDS.slice();
    if (device_id) rows = rows.filter((c) => c.device_id === device_id);
    if (initiated_by) {
      rows = rows.filter((c) => c.initiated_by === initiated_by);
    }
    return mockPage(rows, page, page_size);
  }
  const q = new URLSearchParams();
  if (device_id) q.set("device_id", device_id);
  if (initiated_by) q.set("initiated_by", initiated_by);
  if (page) q.set("page", page);
  if (page_size) q.set("page_size", page_size);
  return apiRequest("/admin/commands?" + q.toString());
}

// POST /api/admin/commands/switch — 手动干预切换（F7.5，唯一人工 SWITCH_CONTENT 入口）
async function adminSwitchContent(deviceId, contentUrl, until) {
  if (USE_MOCK) {
    await mockDelay();
    const dev = MOCK_DEVICES.find((d) => d.device_id === deviceId);
    if (!dev) throw new ApiError(2001);
    if (dev.status !== "online") throw new ApiError(2009);
    const cmd = {
      command_id: "cmd_" + Math.random().toString(36).slice(2, 8),
      device_id: deviceId,
      type: "SWITCH_CONTENT",
      status: "PENDING",
      initiated_by: "admin:" + (getToken() || "demo"),
      created_at: new Date().toISOString(),
      acked_at: null,
      retry_count: 0
    };
    MOCK_COMMANDS.unshift(cmd);
    return { command_id: cmd.command_id };
  }
  return apiRequest("/admin/commands/switch", {
    method: "POST",
    json: {
      device_id: deviceId,
      content_url: contentUrl,
      until: until || null
    }
  });
}

/* ============================================================
   会议室（GET /api/admin/rooms —— 含绑定二维码）
   ============================================================ */

async function listRooms() {
  if (USE_MOCK) {
    await mockDelay();
    return { items: MOCK_ROOMS.slice(), total: MOCK_ROOMS.length };
  }
  // 真接口由后端提供：会议室清单 + 每间房的扫码绑定二维码（F1.1）
  try {
    return await apiRequest("/admin/rooms");
  } catch (e) {
    // 兜底：接口异常时仍从设备列表聚合，页面不至于整块空白
    const devs = await adminListDevices({ page_size: 100 });
    const seen = new Map();
    for (const d of devs.items || []) {
      if (d.room_id && !seen.has(d.room_id)) {
        seen.set(d.room_id, {
          room_id: d.room_id,
          room_name: d.room_name,
          room_email: "",
          timezone: "",
          building: "",
          floor: "",
          capacity: null,
          calendar_status: "connected",
          today_meetings: null
        });
      }
    }
    return { items: Array.from(seen.values()), total: seen.size };
  }
}
