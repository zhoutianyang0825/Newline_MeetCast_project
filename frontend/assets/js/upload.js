/* ============================================================
   Newline MeetCast · 免登录上传页逻辑（S5）
   接口：GET /api/upload/{token}（会议信息）
         POST /api/upload/{token}（上传专属素材）
   错误分支：1004 token 无效/过期/超额 ｜ 2005 格式 ｜ 2006 已截止 ｜ 2007 超限
   ============================================================ */

// ---- URL 上的免登录 token（规范 §五：URL 中 {token} 认证） ----
const UPLOAD_TOKEN = new URLSearchParams(location.search).get("token") || "";

// 已接受格式（服务端 accepted_formats 为准，前端先挡一道）
let acceptedFormats = ["png", "jpg", "mp4", "mp3"];
let maxSizeMb = 500;

// ---- 校验 token 并拉会议信息 ----
async function initUploadPage() {
  const loading = document.getElementById("up-loading");
  try {
    const info = await uploadGetInfo(UPLOAD_TOKEN);

    acceptedFormats = info.accepted_formats || acceptedFormats;
    maxSizeMb = info.max_size_mb || maxSizeMb;

    document.getElementById("up-subject").textContent = info.subject;
    document.getElementById("up-room").textContent = info.room_name;
    document.getElementById("up-time").textContent = fmtMeetingTime(info);
    document.getElementById("up-limits").textContent =
      "支持 " + acceptedFormats.map((f) => f.toUpperCase()).join(" / ") +
      " · 单文件 ≤ " + maxSizeMb + "MB · 截止会前 30 分钟";

    loading.hidden = true;
    document.getElementById("up-card").hidden = false;

    // 已上传列表（服务端返回 uploaded[]）
    for (const f of info.uploaded || []) {
      appendFileRow({ name: f.name, size: f.size_mb * 1024 * 1024 }, "done", f.size_mb);
    }

    bindDropzone();
  } catch (e) {
    loading.hidden = true;
    showUploadError(e);
  }
}

// 会议时间串：UTC → 会议室时区本地渲染（F2.5）
function fmtMeetingTime(info) {
  const opt = {
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: info.timezone || undefined
  };
  const s = new Intl.DateTimeFormat("zh-CN", opt).format(new Date(info.start_time_utc));
  const e = new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: info.timezone || undefined
  }).format(new Date(info.end_time_utc));
  return s + " – " + e;
}

// 错误卡（1004 / 2006 / 2010 / 其他）
function showUploadError(e) {
  const card = document.getElementById("up-err");
  const title = document.getElementById("up-err-title");
  const text = document.getElementById("up-err-text");
  const map = {
    1004: ["链接已失效", "本链接无效、已过期或使用次数超限。若需重新上传，请联系会议组织者获取新链接。"],
    2006: ["上传已截止", "已超过会前 30 分钟的上传截止时间，本场会议素材已锁定。"],
    2010: ["会议不存在或已取消", "本场会议已被取消或改期，专属素材链接随之失效。"],
    5000: ["网络异常", "请检查网络后刷新重试。"]
  };
  const [t, x] = map[e && e.code] || ["链接不可用", (e && e.message) || "请稍后重试或联系会议组织者。"];
  title.textContent = t;
  text.textContent = x;
  card.hidden = false;
}

// ---- 拖拽 / 点击选择 ----
function bindDropzone() {
  const zone = document.getElementById("dropzone");
  const input = document.getElementById("file-input");

  zone.addEventListener("click", () => input.click());
  input.addEventListener("change", () => {
    for (const f of input.files) handleFile(f);
    input.value = "";
  });
  zone.addEventListener("dragover", (e) => {
    e.preventDefault();
    zone.classList.add("drag");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("drag");
    for (const f of e.dataTransfer.files) handleFile(f);
  });
}

// ---- 单文件处理：本地校验 → 上传（2005 格式 / 2007 超限前置拦截） ----
async function handleFile(file) {
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  const normExt = ext === "jpeg" ? "jpg" : ext;

  if (!acceptedFormats.includes(normExt)) {
    appendFileRow(file, "err", null, "[2005] 格式不支持：" + ext);
    return;
  }
  if (file.size > maxSizeMb * 1024 * 1024) {
    appendFileRow(file, "err", null, "[2007] 文件超限（>" + maxSizeMb + "MB）");
    return;
  }

  const row = appendFileRow(file, "uploading", null);
  try {
    await uploadSendFile(UPLOAD_TOKEN, file, (p) => {
      row.querySelector(".st").textContent = "上传中 " + p + "%";
    });
    row.querySelector(".st").textContent = "已完成";
    row.querySelector(".st").classList.remove("err");
  } catch (e) {
    const st = row.querySelector(".st");
    st.textContent = "[" + e.code + "] " + e.message;
    st.classList.add("err");
  }
}

// ---- 文件行渲染 ----
function appendFileRow(file, state, sizeMb, errMsg) {
  const list = document.getElementById("file-list");
  const ext = (file.name.split(".").pop() || "").toUpperCase();
  const mb = sizeMb != null ? sizeMb : Math.round((file.size / 1024 / 1024) * 10) / 10;

  const row = document.createElement("div");
  row.className = "file";
  row.innerHTML =
    '<div class="ft' + (ext === "PNG" ? " png" : "") + '">' + ext + "</div>" +
    '<div class="fn">' + file.name +
    "<small>" + mb + " MB · " +
    (state === "done" ? "已就绪" : state === "err" ? "未上传" : "上传中") +
    "</small></div>" +
    '<div class="st' + (state === "err" ? " err" : "") + '">' +
    (errMsg || (state === "done" ? "已完成" : "上传中 0%")) + "</div>";
  list.appendChild(row);
  return row;
}

initUploadPage();
