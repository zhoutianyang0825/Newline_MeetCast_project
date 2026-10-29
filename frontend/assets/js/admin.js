/* ============================================================
   Newline MeetCast · 管理后台 SPA
   页面：总览 / 设备(S3) / 会议室 / 素材(S4) / 日历源(S9) / 审计日志
   弹层：S7 扫码确认绑定 / 手动干预切换 / 上传素材
   接口：api.js（规范 §三/四/六/七）
   ============================================================ */

// ---- 路由状态 ----
let currentRoute = "overview";
const deviceFilter = { status: "all", page: 1, page_size: 10 };
const materialFilter = { scope: "meeting", category: "all", page: 1, page_size: 12 };
const commandFilter = { device_id: "", initiated_by: "", page: 1, page_size: 10 };

/* ============================================================
   小工具
   ============================================================ */

// UTC ISO → 本地时间串（随行 timezone 优先，F2.5）
function fmtUTC(iso, tz) {
  if (!iso) return "—";
  const d = new Date(iso);
  const opt = {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  };
  if (tz) opt.timeZone = tz;
  return new Intl.DateTimeFormat("zh-CN", opt).format(d);
}

// UTC ISO → 相对时间（“12s 前 / 3 分钟前”）
function fmtAgo(iso) {
  if (!iso) return "—";
  const diff = Math.max(0, Date.now() - Date.parse(iso));
  const s = Math.round(diff / 1000);
  if (s < 60) return s + "s 前";
  const m = Math.round(s / 60);
  if (m < 60) return m + " 分钟前";
  return Math.round(m / 60) + " 小时前";
}

// 数字千分位
function fmtNum(n) {
  return (n == null ? "—" : n).toLocaleString("zh-CN");
}

// toast 轻提示（ok / err）
function toast(msg, type) {
  const wrap = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = "toast" + (type ? " " + type : "");
  el.textContent = msg;
  wrap.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

// 打开 / 关闭弹层
function openModal(html) {
  document.getElementById("modal-card").innerHTML = html;
  document.getElementById("modal").hidden = false;
}
function closeModal() {
  document.getElementById("modal").hidden = true;
}

// 空态
function emptyHTML(text) {
  return (
    '<div class="empty"><div class="ic">∅</div>' + text + "</div>"
  );
}

// 统一错误处理：ApiError → toast；1002（未登录/token 过期）→ 弹登录页
function showError(e) {
  if (e && e.code === 1002) {
    openLogin();
    return;
  }
  const code = e && e.code != null ? e.code : 5000;
  const msg = (e && e.message) || "操作失败";
  toast("[" + code + "] " + msg, "err");
}

// ---- 登录弹层（邮箱 + 密码 → POST /api/auth/login → JWT） ----
var loginOpen = false; // 登录弹层不允许点遮罩关掉，必须登录或退出

function openLogin() {
  loginOpen = true;
  openModal(
    '<div class="modal-head"><div><h4>登录管理后台</h4>' +
    "<p>邮箱 + 密码登录，签发 8 小时有效的 JWT</p></div></div>" +
    '<div class="modal-body">' +
    '<div class="field"><label>邮箱</label>' +
    '<input id="login-email" type="email" placeholder="admin@honghe.com"></div>' +
    '<div class="field"><label>密码</label>' +
    '<input id="login-password" type="password" placeholder="••••••••" ' +
    'onkeydown="if(event.key===\'Enter\')doLogin()"></div>' +
    '<div class="m-hint" id="login-err"></div></div>' +
    '<div class="modal-foot">' +
    '<button class="btn-primary" onclick="doLogin()">登录</button></div>'
  );
}

async function doLogin() {
  const email = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;
  const errEl = document.getElementById("login-err");
  if (!email || !password) {
    errEl.textContent = "请输入邮箱和密码";
    return;
  }
  try {
    const data = await loginRequest(email, password);
    setToken(data.token);
    loginOpen = false;
    closeModal();
    setUserChip(data.name, data.role);
    toast("登录成功：" + data.name, "ok");
    onRouteChange();
  } catch (e) {
    errEl.textContent = (e && e.message) || "登录失败";
  }
}

function logout() {
  setToken("");
  const nameEl = document.getElementById("user-name");
  const avEl = document.getElementById("user-av");
  if (nameEl) nameEl.textContent = "未登录";
  if (avEl) avEl.textContent = "?";
  openLogin();
}

// 登录后把左下角身份块换成真实姓名/角色
function setUserChip(name, role) {
  const nameEl = document.getElementById("user-name");
  const avEl = document.getElementById("user-av");
  if (!nameEl || !avEl) return;
  nameEl.textContent = name + " · " + (role === "admin" ? "管理员" : "普通用户");
  avEl.textContent = (name || "?")[0];
}

/* ============================================================
   路由
   ============================================================ */
function navigate(route) {
  location.hash = "#/" + route;
}

function onRouteChange() {
  const route = (location.hash || "#/overview").replace("#/", "") || "overview";
  currentRoute = route;
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.route === route);
  });
  const view = document.getElementById("view");
  view.innerHTML = '<div class="loading">加载中…</div>';
  const pages = {
    overview: renderOverview,
    devices: renderDevices,
    rooms: renderRooms,
    materials: renderMaterials,
    calendar: renderCalendar,
    commands: renderCommands
  };
  (pages[route] || renderOverview)();
}

/* ============================================================
   总览（S3 指标条扩展为整页）
   ============================================================ */
async function renderOverview() {
  const view = document.getElementById("view");
  try {
    const devData = await adminListDevices({ page_size: 100 });
    const devices = devData.items || [];
    const online = devices.filter((d) => d.status === "online").length;
    const total = devices.length;

    const cmdData = await adminListCommands({ page_size: 100 });
    const cmds = cmdData.items || [];
    const acked = cmds.filter((c) => c.status === "ACKED").length;
    const rate = cmds.length ? ((acked / cmds.length) * 100).toFixed(1) : "—";

    const cal = await adminGetCalendarConfig();
    const calOk = cal.connection_status === "connected" ? 4 : 0;

    const meetings = MOCK_ROOMS.reduce((sum, r) => sum + (r.today_meetings || 0), 0);

    view.innerHTML =
      '<div class="main-head"><div><h3>总览</h3>' +
      "<p>试点：上海 / 新加坡 / 巴塞罗那 / 纽约 · 日历驱动自动编排</p></div></div>" +
      '<div class="stat-row">' +
      '<div class="stat"><div class="k">Online</div><div class="v">' + online +
      "<small> / " + total + '</small></div><div class="d up">在线率 ' +
      (total ? ((online / total) * 100).toFixed(1) : 0) + "%</div></div>" +
      '<div class="stat"><div class="k">Meetings Today</div><div class="v">' + meetings +
      '</div><div class="d">4 间试点会议室合计</div></div>' +
      '<div class="stat"><div class="k">Command</div><div class="v">' + rate +
      '<small>%</small></div><div class="d up">指令成功率（ACKED）</div></div>' +
      '<div class="stat"><div class="k">Calendar</div><div class="v">' + calOk +
      '<small> / 4</small></div><div class="d up">M365 源全部正常</div></div>' +
      "</div>" +
      '<div class="panel"><div class="panel-head"><h4>设备状态速览</h4>' +
      '<button class="btn-mini" onclick="navigate(\'devices\')">进入设备列表</button></div>' +
      (devices.length
        ? "<table><thead><tr><th>设备</th><th>会议室</th><th>状态</th><th>当前播放</th></tr></thead><tbody>" +
          devices
            .map(
              (d) =>
                "<tr><td class='dev-name'>" + d.device_id +
                "<small>" + d.device_name + "</small></td><td>" +
                (d.room_name || "未绑定") + "</td><td>" + statusBadge(d) +
                "</td><td>" + (d.playing || "—") + "</td></tr>"
            )
            .join("") +
          "</tbody></table>"
        : emptyHTML("暂无设备")) +
      "</div>";
  } catch (e) {
    showError(e);
  }
}

// 设备状态徽标：online + device_state 组合（S3 同款）
function statusBadge(d) {
  if (d.status !== "online") {
    return '<span class="badge off"><i></i>离线</span>';
  }
  if (d.device_state === "MEETING") {
    return '<span class="badge busy"><i></i>会议中</span>';
  }
  return '<span class="badge on"><i></i>在线</span>';
}

/* ============================================================
   设备列表（S3）+ 绑定弹层（S7）
   ============================================================ */
// 扫码落地只自动弹一次绑定框，避免每次刷新页面都弹
let scanBindHandled = false;

async function renderDevices() {
  const view = document.getElementById("view");
  try {
    const data = await adminListDevices(deviceFilter);
    const devices = data.items || [];

    // 扫码落地：URL 带 room_id → 顶部提示 + 自动打开绑定框（管理员少点一步）
    const presetRoom = new URLSearchParams(location.search).get("room_id") || "";
    const scanBanner = presetRoom
      ? '<div class="panel" style="border-left:3px solid #7C3AED"><div style="padding:12px 16px">' +
        "<b>扫码进入</b>：会议室 <code>" + presetRoom + "</code> · 请从下方待绑定列表选中屏幕上显示的设备码" +
        ' <button class="btn-ghost" onclick="openBindModal()">立即绑定</button></div></div>'
      : "";

    view.innerHTML =
      '<div class="main-head"><div><h3>设备</h3>' +
      "<p>4 间会议室 · 试点：上海 / 新加坡 / 巴塞罗那 / 纽约</p></div>" +
      '<div class="actions">' +
      '<button class="btn-primary" onclick="openBindModal()">绑定新设备</button>' +
      "</div></div>" +
      scanBanner +
      '<div class="panel"><div class="panel-head"><h4>设备列表</h4>' +
      '<div class="filter">' +
      filterChip("全部", "all", deviceFilter.status, "setDeviceStatus") +
      filterChip("在线", "online", deviceFilter.status, "setDeviceStatus") +
      filterChip("离线", "offline", deviceFilter.status, "setDeviceStatus") +
      "</div></div>" +
      (devices.length
        ? "<table><thead><tr><th>设备</th><th>会议室</th><th>状态</th><th>当前播放</th><th>心跳</th><th>版本</th><th></th></tr></thead><tbody>" +
          devices.map(deviceRow).join("") +
          "</tbody></table>"
        : emptyHTML("没有符合条件的设备")) +
      pagerHTML(data, "deviceFilter", "renderDevices") +
      "</div>";

    if (presetRoom && !scanBindHandled) {
      scanBindHandled = true;
      openBindModal();
    }
  } catch (e) {
    showError(e);
  }
}

function deviceRow(d) {
  return (
    "<tr><td class='dev-name'>" + d.device_id + "<small>" + d.device_name +
    "</small></td><td>" + (d.room_name || "未绑定") + "</td><td>" + statusBadge(d) +
    "</td><td>" + (d.playing || "—") + "</td><td>" + fmtAgo(d.last_heartbeat) +
    "</td><td>v" + d.agent_version + "</td>" +
    "<td><div class='td-actions'>" +
    "<button class='btn-mini ghost' onclick=\"openSwitchModal('" + d.device_id +
    "')\">切换</button>" +
    (d.room_id
      ? "<button class='btn-mini danger' onclick=\"unbindDevice('" + d.device_id +
        "')\">解绑</button>"
      : "") +
    "</div></td></tr>"
  );
}

// 过滤 chip
function filterChip(label, value, current, setter) {
  const on = current === value ? " on" : "";
  return (
    '<span class="' + on.trim() + '" onclick="' + setter + "('" + value + "')\">" +
    label + "</span>"
  );
}

// 分页条
function pagerHTML(data, stateVar, renderFn) {
  const total = data.total || 0;
  const page = data.page || 1;
  const size = data.page_size || 20;
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    '<div class="pager"><span>共 ' + total + " 条 · 第 " + page + "/" + pages + " 页</span>" +
    '<div class="btns">' +
    '<button ' + (page <= 1 ? "disabled" : "") + ' onclick="pageGo(\'' + stateVar +
    "'," + (page - 1) + ",'" + renderFn + "')\">上一页</button>" +
    '<button ' + (page >= pages ? "disabled" : "") + ' onclick="pageGo(\'' + stateVar +
    "'," + (page + 1) + ",'" + renderFn + "')\">下一页</button>" +
    "</div></div>"
  );
}

function pageGo(stateVar, page, renderFn) {
  const st = { deviceFilter, materialFilter, commandFilter }[stateVar];
  st.page = page;
  window[renderFn]();
}

function setDeviceStatus(status) {
  deviceFilter.status = status;
  deviceFilter.page = 1;
  renderDevices();
}

// ---- S7 绑定弹层：扫码解析 room_id → 选待绑定设备 → 确认 ----
async function openBindModal() {
  try {
    const rooms = (await listRooms()).items || [];
    const devs = (await adminListDevices({ page_size: 100 })).items || [];
    const pending = devs.filter((d) => !d.room_id);

    // 扫码落地：URL 上带 room_id 就预选该会议室（F1.1 门口二维码只含 room_id）
    const presetRoom = new URLSearchParams(location.search).get("room_id") || "";
    const preset = rooms.find((r) => r.room_id === presetRoom);
    const headHint = preset
      ? "已从二维码识别会议室：" + preset.room_name + " · 请核对设备码与屏幕显示一致"
      : "门口二维码只含 room_id · 请核对设备码与屏幕显示一致";

    openModal(
      '<div class="modal-head"><div><h4>确认绑定这台设备？</h4>' +
      "<p>" + headHint + "</p></div>" +
      '<div class="modal-x" onclick="closeModal()">×</div></div>' +
      '<div class="modal-body">' +
      '<div class="field"><label>会议室（扫码解析结果）</label>' +
      '<select id="bind-room">' +
      rooms
        .map((r) => '<option value="' + r.room_id + '"' +
          (r.room_id === presetRoom ? " selected" : "") + ">" + r.room_name +
          (r.occupant_device_id ? "（已绑 " + r.occupant_device_id + "）" : "") + "</option>")
        .join("") +
      "</select></div>" +
      '<div class="field"><label>待绑定设备（对照设备屏上显示）</label>' +
      '<select id="bind-device">' +
      (pending.length
        ? pending
            .map((d) => '<option value="' + d.device_id + '">' + d.device_id +
              "（" + d.device_name + "）</option>")
            .join("")
        : '<option value="">暂无待绑定设备</option>') +
      "</select></div>" +
      '<div class="m-dev"><div class="lbl">待绑定设备</div>' +
      '<div class="code" id="bind-code">' +
      (pending[0] ? pending[0].device_id : "—") +
      "<span>" + (pending[0] ? pending[0].device_name : "") + "</span></div></div>" +
      '<div class="m-hint">请与设备屏幕上显示的设备码核对一致后再确认。绑定后 5 分钟内该会议室调度生效；换绑走「解绑/换绑」。</div>' +
      "</div>" +
      '<div class="modal-foot"><button class="btn-ghost" onclick="closeModal()">取消</button>' +
      '<button class="btn-primary" onclick="confirmBind()">确认绑定</button></div>'
    );

    // 选中设备变化 → 高亮区跟着变
    const sel = document.getElementById("bind-device");
    if (sel) {
      sel.addEventListener("change", () => {
        const d = devs.find((x) => x.device_id === sel.value);
        document.getElementById("bind-code").innerHTML = d
          ? d.device_id + "<span>" + d.device_name + "</span>"
          : "—";
      });
    }
  } catch (e) {
    showError(e);
  }
}

// 确认绑定（POST /api/admin/devices/bind）
async function confirmBind() {
  const roomId = document.getElementById("bind-room").value;
  const deviceId = document.getElementById("bind-device").value;
  if (!deviceId) {
    toast("请选择待绑定设备", "err");
    return;
  }
  try {
    const res = await adminBindDevice(deviceId, roomId, false);
    closeModal();
    toast("绑定成功：" + res.device_id + " → " + res.room_id + "（5 分钟内调度生效）", "ok");
    renderDevices();
  } catch (e) {
    if (e.code === 2002 || e.code === 2008) {
      if (confirm("[" + e.code + "] " + e.message + "，是否强制覆盖（force=true）？")) {
        try {
          const res = await adminBindDevice(deviceId, roomId, true);
          closeModal();
          toast("已强制绑定：" + res.device_id + " → " + res.room_id, "ok");
          renderDevices();
        } catch (e2) {
          showError(e2);
        }
      }
      return;
    }
    showError(e);
  }
}

// 解绑（POST /api/admin/devices/unbind）
async function unbindDevice(deviceId) {
  if (!confirm("确认解绑 " + deviceId + "？解绑后设备回到待绑定状态。")) return;
  try {
    await adminUnbindDevice(deviceId);
    toast("已解绑 " + deviceId, "ok");
    renderDevices();
  } catch (e) {
    showError(e);
  }
}

// ---- 手动干预切换弹层（F7.5，POST /api/admin/commands/switch） ----
function openSwitchModal(deviceId) {
  openModal(
    '<div class="modal-head"><div><h4>手动干预切换</h4>' +
    "<p>唯一人工触发 SWITCH_CONTENT 的入口（F7.5）· 自动路径走 switch_at</p></div>" +
    '<div class="modal-x" onclick="closeModal()">×</div></div>' +
    '<div class="modal-body">' +
    '<div class="field"><label>设备</label><input id="switch-device" value="' +
    deviceId + '" readonly></div>' +
    '<div class="field"><label>内容地址 content_url</label>' +
    '<input id="switch-url" type="text" placeholder="https://meetcast.app/c/emergency"></div>' +
    '<div class="field"><label>截止时间 until（UTC ISO，可空）</label>' +
    '<input id="switch-until" type="text" placeholder="2026-10-27T05:00:00Z"></div>' +
    '<div class="m-hint">设备离线时命令入队 PENDING，上线后经 poll 下发（错误码 2009 不阻塞）。</div>' +
    "</div>" +
    '<div class="modal-foot"><button class="btn-ghost" onclick="closeModal()">取消</button>' +
    '<button class="btn-primary" onclick="confirmSwitch()">下发指令</button></div>'
  );
}

async function confirmSwitch() {
  const deviceId = document.getElementById("switch-device").value;
  const url = document.getElementById("switch-url").value.trim();
  const until = document.getElementById("switch-until").value.trim();
  if (!url) {
    toast("请填写 content_url", "err");
    return;
  }
  try {
    const res = await adminSwitchContent(deviceId, url, until || null);
    closeModal();
    toast("指令已入队：" + res.command_id, "ok");
  } catch (e) {
    if (e.code === 2009) {
      toast("[2009] 设备离线，命令已入队 PENDING，上线后重试", "err");
      return;
    }
    showError(e);
  }
}

/* ============================================================
   会议室（rooms 接口规范未定义；聚合展示）
   ============================================================ */
// 会议室数据缓存：二维码弹窗/打印时按 room_id 取整行
let ROOM_CACHE = {};

async function renderRooms() {
  const view = document.getElementById("view");
  try {
    const data = await listRooms();
    const rooms = data.items || [];
    ROOM_CACHE = {};
    rooms.forEach((r) => { ROOM_CACHE[r.room_id] = r; });
    view.innerHTML =
      '<div class="main-head"><div><h3>会议室</h3>' +
      "<p>资源邮箱（Room Mailbox）= M365 现成功能 · 本系统只读账本指挥屏幕</p></div></div>" +
      '<div class="panel"><div class="panel-head"><h4>会议室列表</h4>' +
      '<span class="badge-prob"><i></i>试点 4 间 · 3 个时区带</span></div>' +
      (rooms.length
        ? "<table><thead><tr><th>会议室</th><th>资源邮箱</th><th>时区</th><th>容量</th><th>今日会议</th><th>日历</th><th>绑定码</th></tr></thead><tbody>" +
          rooms
            .map(
              (r) =>
                "<tr><td class='dev-name'>" + r.room_name +
                "<small>" + (r.occupant_device_id ? "设备 " + r.occupant_device_id : "未绑定设备") + "</small></td><td>" +
                (r.room_email || "—") + "</td><td>" + (r.timezone || "—") +
                "</td><td>" + (r.capacity || "—") + " 人</td><td>" +
                (r.today_meetings != null ? r.today_meetings + " 场" : "—") +
                "</td><td>" +
                (r.calendar_status === "connected"
                  ? '<span class="badge on"><i></i>已同步</span>'
                  : '<span class="badge off"><i></i>未连接</span>') +
                "</td><td>" +
                (r.qr_svg
                  ? '<button class="btn-ghost" onclick="openRoomQR(\'' + r.room_id + '\')">二维码</button>'
                  : "—") +
                "</td></tr>"
            )
            .join("") +
          "</tbody></table>"
        : emptyHTML("暂无会议室")) +
      "</div>";
  } catch (e) {
    showError(e);
  }
}

/* ---------- 会议室绑定二维码（F1.1 扫码入口） ---------- */

// SVG 字符串 → data URI（btoa 不能直接吃中文，先转 UTF-8）
function svgToDataUri(svg) {
  return "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svg)));
}

function openRoomQR(roomId) {
  const r = ROOM_CACHE[roomId];
  if (!r || !r.qr_svg) {
    toast("该会议室未生成二维码", "err");
    return;
  }
  openModal(
    '<div class="modal-head"><div><h4>' + r.room_name + " · 绑定二维码</h4>" +
    "<p>打印后贴在门口；扫码即进入本页并自动带上 room_id</p></div>" +
    '<div class="modal-x" onclick="closeModal()">×</div></div>' +
    '<div class="modal-body" style="text-align:center">' +
    '<div style="background:#fff;display:inline-block;padding:14px;border-radius:12px">' +
    '<img src="' + svgToDataUri(r.qr_svg) + '" style="width:220px;height:220px;display:block">' +
    "</div>" +
    '<div class="m-hint" style="word-break:break-all;margin-top:12px">' + r.bind_url + "</div>" +
    '<div class="m-dev" style="margin-top:14px"><div class="lbl">当前占用设备</div>' +
    '<div class="code">' + (r.occupant_device_id || "未绑定") + "</div></div>" +
    "</div>" +
    '<div class="modal-foot">' +
    '<button class="btn-ghost" onclick="closeModal()">关闭</button>' +
    '<button class="btn-primary" onclick="printRoomQR(\'' + r.room_id + '\')">打印二维码</button></div>'
  );
}

function printRoomQR(roomId) {
  const r = ROOM_CACHE[roomId];
  if (!r) return;
  const win = window.open("", "_blank", "width=520,height=720");
  if (!win) {
    toast("浏览器拦截了弹窗，请允许后重试", "err");
    return;
  }
  win.document.write(
    "<html><head><meta charset='utf-8'><title>" + r.room_name + " 绑定二维码</title>" +
    "<style>body{font-family:-apple-system,'PingFang SC',sans-serif;text-align:center;padding:36px;color:#111}" +
    "h2{font-size:18px;margin:0 0 6px}p{color:#666;font-size:12px;margin:0 0 22px}" +
    "img{width:320px;height:320px}.url{margin-top:18px;font-size:11px;color:#888;word-break:break-all}</style>" +
    "</head><body>" +
    "<h2>" + r.room_name + "</h2>" +
    "<p>用手机扫码 → 打开绑定页 → 选择屏幕上显示的设备码</p>" +
    "<img src='" + svgToDataUri(r.qr_svg) + "'>" +
    "<div class='url'>" + r.bind_url + "</div>" +
    "</body></html>"
  );
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 300);
}

/* ============================================================
   素材双轨（S4）
   ============================================================ */

// F4.2 一级业务分类（与后端 Material.category 对应）
const MATERIAL_CATEGORIES = [
  ["all", "全部分类"],
  ["brand", "品牌资产"],
  ["culture", "文化墙"],
  ["meeting", "会议素材"],
  ["other", "其他"]
];

// 分类中文名（卡片徽标用）
const CATEGORY_LABEL = { brand: "品牌", culture: "文化墙", meeting: "会议", other: "其他" };

// 当前页素材缓存：预览弹窗按 material_id 取整条
let MATERIAL_CACHE = {};

async function renderMaterials() {
  const view = document.getElementById("view");
  try {
    // 双轨计数：当前 Tab 精确 total，另一轨并行取 total 供徽标
    const otherScope = materialFilter.scope === "meeting" ? "public" : "meeting";
    const [data, other] = await Promise.all([
      adminListMaterials(materialFilter),
      adminListMaterials({ scope: otherScope, page: 1, page_size: 1 })
    ]);
    const items = data.items || [];
    MATERIAL_CACHE = {};
    items.forEach((m) => { MATERIAL_CACHE[m.material_id] = m; });
    const counts = {
      meeting: materialFilter.scope === "meeting" ? data.total : other.total,
      public: materialFilter.scope === "public" ? data.total : other.total
    };

    view.innerHTML =
      '<div class="main-head"><div><h3>素材</h3>' +
      "<p>公共素材全会议室共享（15 天 LRU）· 会议专属随会生效、会后自动清理</p></div>" +
      '<div class="actions"><button class="btn-primary" onclick="openUploadModal()">上传素材</button></div></div>' +
      '<div class="mat-tabs">' +
      '<div class="mat-tab' + (materialFilter.scope === "meeting" ? " on" : "") +
      '" onclick="setMaterialScope(\'meeting\')">会议专属<span class="cnt">' +
      counts.meeting + "</span></div>" +
      '<div class="mat-tab' + (materialFilter.scope === "public" ? " on" : "") +
      '" onclick="setMaterialScope(\'public\')">公共素材<span class="cnt">' +
      counts.public + "</span></div>" +
      "</div>" +
      '<div class="filter" style="margin:0 0 12px">' +
      MATERIAL_CATEGORIES.map(([key, label]) =>
        '<button class="chip' + (materialFilter.category === key ? " on" : "") +
        '" onclick="setMaterialCategory(\'' + key + '\')">' + label + "</button>"
      ).join("") +
      "</div>" +
      '<div class="mat-banner"><div class="ic">' +
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M12 8v5m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>' +
      "</div><p><b>会议专属素材</b>仅在本场会议期间对指定会议室可见，<b>会后自动清理</b>（设备本地同步删除）。公共素材不受影响，按 15 天未用 LRU 自动淘汰。</p></div>" +
      (items.length
        ? '<div class="mat-grid">' + items.map(materialCard).join("") + "</div>"
        : emptyHTML("该分类暂无素材")) +
      pagerHTML(data, "materialFilter", "renderMaterials");
  } catch (e) {
    showError(e);
  }
}

function materialCard(m, i) {
  const isVideo = m.format === "mp4";
  const isAudio = m.format === "mp3";
  const isImage = ["png", "jpg", "jpeg"].includes(m.format);

  // F4.2 预览：能出图就出真图，不能出就给占位（不再用纯色块假装封面）
  let thumb = "";
  if (isImage) {
    thumb = '<img src="' + m.url + '" alt="" loading="lazy"' +
      ' onerror="this.replaceWith(Object.assign(document.createElement(\'div\'),{className:\'file-ph\',textContent:\'无预览\'}))">';
  } else if (isVideo) {
    thumb = '<video src="' + m.url + '" muted preload="metadata"></video><div class="play"></div>';
  } else if (isAudio) {
    thumb = '<div class="file-ph">♪ 音频</div>';
  } else {
    thumb = '<div class="file-ph">' + (m.format || "file").toUpperCase() + "</div>";
  }

  return (
    '<div class="mat-card"><div class="mat-cover" style="cursor:zoom-in"' +
    ' onclick="previewMaterial(\'' + m.material_id + '\')">' +
    thumb +
    (m.scope === "meeting"
      ? '<span class="badge-t exp">会后清理</span>'
      : '<span class="badge-t">公共素材</span>') +
    '<span class="badge-cat">' + (CATEGORY_LABEL[m.category] || m.category || "其他") + "</span>" +
    '<button class="del" title="删除" onclick="event.stopPropagation();deleteMaterial(\'' + m.material_id +
    "')\">×</button></div>" +
    '<div class="mat-info"><div class="t">' + m.name + "</div>" +
    '<div class="m"><span>' +
    (m.scope === "meeting"
      ? (m.meeting_id || "—") + " · " + (m.uploaded_by || "").replace("organizer:", "")
      : (m.uploaded_by || "").replace("admin:", "").replace("user:", "")) +
    "</span><span>" + fmtUTC(m.created_at) + "</span></div></div></div>"
  );
}

// 素材预览：图片看大图、视频可直接播、音频给播放器
function previewMaterial(materialId) {
  const m = MATERIAL_CACHE[materialId];
  if (!m) return;
  let body = "";
  if (["png", "jpg", "jpeg"].includes(m.format)) {
    body = '<img src="' + m.url + '" style="max-width:100%;max-height:60vh;border-radius:10px;display:block;margin:0 auto">';
  } else if (m.format === "mp4") {
    body = '<video src="' + m.url + '" controls autoplay style="max-width:100%;max-height:60vh;border-radius:10px;display:block;margin:0 auto"></video>';
  } else if (m.format === "mp3") {
    body = '<audio src="' + m.url + '" controls autoplay style="width:100%"></audio>';
  } else {
    body = '<div class="m-hint">该格式不支持预览</div>';
  }
  openModal(
    '<div class="modal-head"><div><h4>' + m.name + "</h4>" +
    "<p>" + (CATEGORY_LABEL[m.category] || "其他") + " · " + m.format + " · " + m.size_mb + "MB</p></div>" +
    '<div class="modal-x" onclick="closeModal()">×</div></div>' +
    '<div class="modal-body">' + body +
    '<div class="m-hint" style="word-break:break-all;margin-top:14px">' + m.url + "</div></div>" +
    '<div class="modal-foot"><button class="btn-ghost" onclick="closeModal()">关闭</button></div>'
  );
}

function setMaterialScope(scope) {
  materialFilter.scope = scope;
  materialFilter.page = 1;
  renderMaterials();
}

function setMaterialCategory(category) {
  materialFilter.category = category;
  materialFilter.page = 1;
  renderMaterials();
}

// ---- 上传公共素材弹层（POST /api/admin/materials） ----
function openUploadModal() {
  openModal(
    '<div class="modal-head"><div><h4>上传公共素材</h4>' +
    "<p>F4.1 · 常规格式：png / jpg / mp4 / mp3 · 单文件 ≤ 500MB</p></div>" +
    '<div class="modal-x" onclick="closeModal()">×</div></div>' +
    '<div class="modal-body">' +
    '<div class="field"><label>选择文件</label>' +
    '<input id="up-file" type="file" accept=".png,.jpg,.jpeg,.mp4,.mp3"></div>' +
    '<div class="field"><label>业务分类</label>' +
    '<select id="up-category">' +
    MATERIAL_CATEGORIES.filter(([k]) => k !== "all")
      .map(([k, label]) => '<option value="' + k + '">' + label + "</option>").join("") +
    "</select></div>" +
    '<div class="field"><label>标签（可空，逗号分隔）</label>' +
    '<input id="up-tags" type="text" placeholder="品牌,宣传片"></div>' +
    '<div class="m-hint">会议专属素材不走本通道——由定会者经免登录链接直传（F4.7）。</div>' +
    "</div>" +
    '<div class="modal-foot"><button class="btn-ghost" onclick="closeModal()">取消</button>' +
    '<button class="btn-primary" onclick="doUploadMaterial()">上传</button></div>'
  );
}

async function doUploadMaterial() {
  const input = document.getElementById("up-file");
  const file = input.files && input.files[0];
  if (!file) {
    toast("请选择文件", "err");
    return;
  }
  const tags = document.getElementById("up-tags").value.trim();
  const categoryEl = document.getElementById("up-category");
  const category = categoryEl ? categoryEl.value : "other";
  try {
    const res = await adminUploadMaterial(file, tags, (p) => console.log("upload", p + "%"), category);
    closeModal();
    toast("上传成功：" + res.material_id, "ok");
    renderMaterials();
  } catch (e) {
    showError(e);
  }
}

// 删除素材（DELETE /api/admin/materials/{id}）
async function deleteMaterial(materialId) {
  if (!confirm("确认删除 " + materialId + "？专属素材删除时同步下发 CLEAN_MATERIAL。")) return;
  try {
    await adminDeleteMaterial(materialId);
    toast("已删除 " + materialId, "ok");
    renderMaterials();
  } catch (e) {
    showError(e);
  }
}

/* ============================================================
   日历源配置（S9）
   ============================================================ */
let calConfig = null;

async function renderCalendar() {
  const view = document.getElementById("view");
  try {
    calConfig = await adminGetCalendarConfig();
    const c = calConfig;
    const p = c.pull_policy;

    view.innerHTML =
      '<div class="main-head"><div><h3>日历源</h3>' +
      "<p>试点 4 间会议室统一 M365 · Google 日历 P1 不启用</p></div>" +
      '<div class="actions">' +
      '<button class="btn-ghost" onclick="saveCalendar()">保存配置</button>' +
      '<button class="btn-primary" onclick="testCalendar()">连接测试</button>' +
      "</div></div>" +
      '<div class="cal-grid">' +
      '<div class="cal-panel"><div class="cal-panel-head"><h4>M365 · 应用身份（app-only）</h4>' +
      (c.connection_status === "connected"
        ? '<span class="badge-prob"><i></i>已连接</span>'
        : '<span class="badge off"><i></i>未连接</span>') +
      "</div><div class='cal-body'>" +
      calRow("租户", "<code>" + c.tenant + "</code>") +
      calRow("服务账号", "<code>" + c.service_account + "</code>") +
      calRow("权限范围", c.scopes.map((s) => "<code>" + s + "</code>").join(" + ")) +
      calRow("权限边界", "日历只读 · 发链接邮件；不加 ReadWrite") +
      calRow("资源邮箱", "4 个已同步<small>room-a3-01 / b2-05 / c1-02 / 12f-01</small>") +
      calRow("凭证状态", "有效 · " + fmtUTC(c.credential_expire_at) + " 到期<small>到期前 14 天告警管理员</small>") +
      "</div></div>" +
      '<div class="cal-panel"><div class="cal-panel-head"><h4>拉取策略</h4>' +
      '<span class="badge-prob"><i></i>运行中</span></div><div class="cal-body">' +
      pullItem("schedule", "编排拉取 · 12 小时窗口",
        "每 " + p.schedule.interval_min + " 分钟触发，驱动状态机与指令生成", p.schedule.enabled) +
      pullItem("link_gen", "链接生成拉取 · 7 天窗口",
        "每 " + p.link_gen.interval_min + " 分钟触发，只为发专属素材上传链接", p.link_gen.enabled) +
      pullItem("dst_enabled", "时区与夏令时",
        "UTC 存储 + IANA 渲染；美欧两套 DST 已启用", p.dst_enabled) +
      pullItem("alert_enabled", "异常告警",
        "API 超限 / 凭证过期 → 邮件通知管理员", p.alert_enabled) +
      pullItem("google_enabled", "Google 日历",
        "P1 不启用 · 待真实客户需求再开（需域级委派）", p.google_enabled) +
      '<div class="cal-row"><div class="k">告警邮箱</div><div class="v">' +
      '<input id="cal-alert-email" value="' + (c.alert_email || "") +
      '" style="text-align:right;border:1px solid var(--hair);border-radius:10px;padding:8px 12px;font-size:13px;width:220px;">' +
      "</div></div>" +
      "</div></div></div>";
  } catch (e) {
    showError(e);
  }
}

function calRow(k, v) {
  return '<div class="cal-row"><div class="k">' + k + '</div><div class="v">' + v + "</div></div>";
}

function pullItem(key, title, sub, enabled) {
  return (
    '<div class="pull-item"><div class="pi">' +
    '<svg viewBox="0 0 24 24" fill="none"><path d="M12 8v4l3 2m6-2a9 9 0 11-18 0 9 9 0 0118 0z" stroke="#7C3AED" stroke-width="2" stroke-linecap="round"/></svg>' +
    '</div><div class="pt"><div class="t">' + title + '</div><div class="s">' + sub + "</div></div>" +
    '<button class="switch' + (enabled ? "" : " off") + '" data-key="' + key +
    '" onclick="toggleSwitch(this)"></button></div>'
  );
}

// 开关切换：只改本地状态，点「保存配置」才 PUT
function toggleSwitch(btn) {
  const key = btn.dataset.key;
  const p = calConfig.pull_policy;
  if (key === "schedule") p.schedule.enabled = !p.schedule.enabled;
  else if (key === "link_gen") p.link_gen.enabled = !p.link_gen.enabled;
  else p[key] = !p[key];
  btn.classList.toggle("off");
}

// 保存（PUT /api/admin/calendar/config）
async function saveCalendar() {
  const email = document.getElementById("cal-alert-email").value.trim();
  calConfig.alert_email = email;
  try {
    await adminSaveCalendarConfig(calConfig);
    toast("配置已保存", "ok");
  } catch (e) {
    showError(e);
  }
}

// 连接测试（POST /api/admin/calendar/test）
async function testCalendar() {
  toast("正在测试连接…");
  try {
    const res = await adminTestCalendar();
    if (res.auth_ok) {
      toast("连接正常 · 同步 " + res.rooms_synced + " 间 · 延迟 " + res.api_latency_ms + "ms", "ok");
    } else {
      toast("[3001] 日历源凭证失效", "err");
    }
  } catch (e) {
    showError(e);
  }
}

/* ============================================================
   审计日志（F7.1 / F8.3）
   ============================================================ */
async function renderCommands() {
  const view = document.getElementById("view");
  try {
    const data = await adminListCommands(commandFilter);
    const items = data.items || [];
    view.innerHTML =
      '<div class="main-head"><div><h3>审计日志</h3>' +
      "<p>所有指令含 initiated_by（谁触发的）· 支持事故定责追溯</p></div>" +
      '<div class="actions">' +
      '<button class="btn-ghost" onclick="clearCommandFilter()">清空筛选</button>' +
      "</div></div>" +
      '<div class="panel"><div class="panel-head"><h4>指令记录</h4>' +
      '<div class="filter">' +
      filterChip("全部", "", commandFilter.initiated_by, "setInitiatedBy") +
      filterChip("system", "system", commandFilter.initiated_by, "setInitiatedBy") +
      filterChip("admin", "admin:ops01", commandFilter.initiated_by, "setInitiatedBy") +
      "</div></div>" +
      (items.length
        ? "<table><thead><tr><th>指令 ID</th><th>设备</th><th>类型</th><th>状态</th><th>触发者</th><th>创建</th><th>回执</th><th>重试</th></tr></thead><tbody>" +
          items
            .map(
              (c) =>
                "<tr><td class='dev-name'>" + c.command_id + "</td><td>" + c.device_id +
                "</td><td>" + c.type + "</td><td>" + cmdBadge(c.status) + "</td><td>" +
                c.initiated_by + "</td><td>" + fmtUTC(c.created_at) + "</td><td>" +
                (c.acked_at ? fmtUTC(c.acked_at) : "—") + "</td><td>" + c.retry_count +
                "</td></tr>"
            )
            .join("") +
          "</tbody></table>"
        : emptyHTML("暂无指令记录")) +
      pagerHTML(data, "commandFilter", "renderCommands") +
      "</div>";
  } catch (e) {
    showError(e);
  }
}

function cmdBadge(status) {
  const map = {
    ACKED: '<span class="badge on"><i></i>ACKED</span>',
    FAILED: '<span class="badge off"><i></i>FAILED</span>',
    TIMEOUT: '<span class="badge off"><i></i>TIMEOUT</span>',
    SENT: '<span class="badge busy"><i></i>SENT</span>',
    PENDING: '<span class="badge busy"><i></i>PENDING</span>'
  };
  return map[status] || status;
}

function setInitiatedBy(v) {
  commandFilter.initiated_by = v;
  commandFilter.page = 1;
  renderCommands();
}

function clearCommandFilter() {
  commandFilter.device_id = "";
  commandFilter.initiated_by = "";
  commandFilter.page = 1;
  renderCommands();
}

/* ============================================================
   启动
   ============================================================ */
document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => navigate(btn.dataset.route));
});
document.getElementById("modal").addEventListener("click", (e) => {
  if (e.target.id === "modal" && !loginOpen) closeModal();
});
window.addEventListener("hashchange", onRouteChange);
onRouteChange();

// 启动即判登录态：没 token 直接弹登录；有 token 静默恢复身份显示
if (!getToken()) {
  openLogin();
} else {
  meRequest()
    .then((d) => setUserChip(d.name, d.role))
    .catch(() => {});
}
