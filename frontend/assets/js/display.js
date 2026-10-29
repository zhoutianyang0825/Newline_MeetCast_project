/* ============================================================
   Newline MeetCast · 设备大屏页逻辑（display/*.html 共用）
   覆盖 UI 稿：S1 会议页 / S2 标牌页 / S6 待绑定屏 / S8 点餐浮卡
   数据来源：
     1. mock.js 的 MOCK_DISPLAY（演示默认值，与 UI 稿一致）
     2. URL query 覆盖（content_url 可带参：?subject=xxx&room=xxx&device_id=xxx）
   真实链路：设备 WebView 打开 PREPARE_MEETING.payload.content_url 即本页，
     query 由服务端生成；页面本身无数据接口（规范未定义 display API）。
   ============================================================ */

// ---- query 参数读取（覆盖演示数据用） ----
function queryParam(key) {
  return new URLSearchParams(location.search).get(key);
}

/* ============================================================
   F3.4 标牌时段策略：早 / 中 / 晚三套文案
   时段来源优先级：
     1) URL ?slot=（服务端 REPLAY_DEFAULT.payload.slot，按会议室本地时区算好）
     2) 本机小时数兜底推断（开机首次渲染时还没有指令）
   ============================================================ */
const SIGNAGE_SLOTS = {
  morning: {
    slogan_a: "上午好，",
    slogan_em: "议程已就绪",
    slogan_b: "。",
    desc: "会议室已准备就绪 · 请提前 5 分钟入场",
    banner: "Morning Briefing"
  },
  afternoon: {
    slogan_a: "下午的会，",
    slogan_em: "一切就位",
    slogan_b: "。",
    desc: "日程自动加载 · 会前 1 分钟自动切屏 · 无需操作",
    banner: "Afternoon Session"
  },
  evening: {
    slogan_a: "今天辛苦了，",
    slogan_em: "明日再见",
    slogan_b: "。",
    desc: "今日会议已结束 · 屏幕恢复企业形象展示",
    banner: "Evening Mode"
  }
};

// 解析当前应使用的时段
function resolveSignageSlot() {
  const fromQuery = queryParam("slot");
  if (fromQuery && SIGNAGE_SLOTS[fromQuery]) return fromQuery;
  const hour = new Date().getHours();
  if (hour < 12) return "morning";
  if (hour < 18) return "afternoon";
  return "evening";
}

// ---- 合并演示数据与 query 覆盖 ----
function displayData(key) {
  const base = JSON.parse(JSON.stringify(MOCK_DISPLAY[key]));
  const subject = queryParam("subject");
  const room = queryParam("room");
  if (subject && key === "meeting") base.subject = subject;
  if (room) base.room_label = room;
  return base;
}

// ---- 实时时钟：按 IANA 时区渲染（F2.5，不依赖设备本地猜时区） ----
function startClock(tick) {
  const tz = queryParam("tz") || null;
  const render = () => tick(new Date(), tz);
  render();
  setInterval(render, 1000);
}

// ---- 格式化：HH:mm（24h）----
function fmtTime(date, tz) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: tz || undefined
  }).format(date);
}

// ---- 格式化：10月27日 周二 ----
function fmtDateCN(date, tz) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "short",
    timeZone: tz || undefined
  }).format(date);
}

/* ============================================================
   S1 会议页
   ============================================================ */
function initMeetingPage() {
  const d = displayData("meeting");

  // ★ 服务端生成的内容优先：PREPARE_MEETING 的 content_url 会把算好的字段放进 query
  //   （敏感会议的 subject 到这里已经是「会议中」，设备端不参与任何脱敏判断）
  const q = new URLSearchParams(location.search);
  if (q.get("subject")) d.subject = q.get("subject");
  if (q.get("room")) d.room_label = q.get("room");
  if (q.get("time")) d.time_label = q.get("time");
  if (q.get("organizer")) d.organizer = q.get("organizer");
  if (q.get("attendees")) {
    const names = q.get("attendees").split(",").filter(Boolean);
    d.attendees = names.slice(0, 4);
    d.attendee_more = Math.max(0, names.length - 4);
  }
  if (q.get("tagline")) d.tagline = q.get("tagline");

  // F3.5 版式：LLM（或规则）选出的 standard / focus / minimal 在这里真正生效
  const layout = q.get("layout") || "standard";
  document.body.dataset.layout = layout;
  if (layout === "minimal") {
    // 极简版：敏感会议专用，不展示任何细节，只留一句「会议中」
    const liveEl = document.querySelector(".mp-live");
    if (liveEl) liveEl.textContent = "Private Meeting";
  }

  // 顶部：会议室 + 时钟
  document.getElementById("mp-room").textContent = d.room_label;
  startClock((date, tz) => {
    const t = fmtTime(date, tz);
    const day = fmtDateCN(date, tz);
    document.getElementById("mp-clock").textContent = t + " · " + day;
  });

  // 主体：主题 / 时间 / 组织者 / 参会人
  document.getElementById("mp-title").textContent = d.subject;

  // F5.1 引导语（LLM 或模板生成，服务端塞在 content_url 的 tagline 里）
  if (d.tagline) {
    let tagEl = document.getElementById("mp-tagline");
    if (!tagEl) {
      tagEl = document.createElement("div");
      tagEl.id = "mp-tagline";
      tagEl.className = "mp-tagline";
      const titleEl = document.getElementById("mp-title");
      if (titleEl && titleEl.parentNode) {
        titleEl.parentNode.insertBefore(tagEl, titleEl.nextSibling);
      }
    }
    tagEl.textContent = d.tagline;
  }

  document.getElementById("mp-time").textContent =
    d.time_label || (d.start_local + " – " + d.end_local);
  document.getElementById("mp-organizer").textContent = d.organizer;
  document.getElementById("mp-count").textContent = String(
    d.attendees.length + d.attendee_more
  );

  // 参会人头像（前 4 个姓氏 + N）
  const peopleBox = document.getElementById("mp-people");
  peopleBox.innerHTML = "";
  for (const name of d.attendees) {
    const av = document.createElement("div");
    av.className = "avatar";
    av.textContent = name;
    peopleBox.appendChild(av);
  }
  if (d.attendee_more > 0) {
    const more = document.createElement("div");
    more.className = "avatar more";
    more.textContent = "+" + d.attendee_more;
    peopleBox.appendChild(more);
  }

  // 议程列表
  const ul = document.getElementById("mp-agenda-list");
  ul.innerHTML = "";
  for (const item of d.agenda) {
    const li = document.createElement("li");
    const no = document.createElement("span");
    no.textContent = item.no;
    const text = document.createTextNode(item.text);
    li.appendChild(no);
    li.appendChild(text);
    ul.appendChild(li);
  }

  // 本场专属素材条
  document.getElementById("mp-asset-name").textContent = d.asset.name;
  document.getElementById("mp-asset-by").textContent = d.asset.by;

  // 底部预告
  document.getElementById("mp-next").textContent = d.next;

  // S8 点餐浮卡：?notice=meal 触发
  if (queryParam("notice") === "meal") {
    initMealCard();
  }
}

/* ============================================================
   S8 点餐提醒卡（SHOW_NOTICE 浮层，60s 自动收起，不切屏）
   ============================================================ */
function initMealCard() {
  const d = MOCK_DISPLAY.meal;
  const veil = document.getElementById("meal-veil");
  document.getElementById("meal-end").textContent = d.end_local;
  document.getElementById("meal-people").textContent = String(d.people);
  veil.hidden = false;

  // 60 秒无操作自动收起（UI 稿 S8 口径）
  const timer = setTimeout(() => {
    veil.hidden = true;
  }, 60000);

  // 忽略 → 立即收起
  document.getElementById("meal-ignore").addEventListener("click", () => {
    clearTimeout(timer);
    veil.hidden = true;
  });

  // 确认 → 真实链路：发起点餐推荐 + 携带关键词跳第三方（P1，demo 仅提示）
  document.getElementById("meal-confirm").addEventListener("click", () => {
    clearTimeout(timer);
    veil.hidden = true;
    console.log("[SHOW_NOTICE] 用户确认点餐 → P1：生成推荐清单并跳转第三方订餐页");
  });
}

/* ============================================================
   S2 标牌页
   ============================================================ */
function initSignagePage() {
  const d = displayData("signage");
  const slot = resolveSignageSlot();
  const preset = SIGNAGE_SLOTS[slot];

  // 时段落到 body.dataset，CSS 可据此换配色（.sign-page[data-slot=evening]）
  document.body.dataset.slot = slot;

  document.getElementById("sg-room").textContent = d.room_label;
  document.getElementById("sg-brand").textContent = d.brand_name;

  // 时段文案优先；显式 ?slogan_a= 等 query 仍可覆盖（运营临时换文案用）
  document.getElementById("sg-slogan-a").textContent = queryParam("slogan_a") || preset.slogan_a;
  document.getElementById("sg-slogan-em").textContent = queryParam("slogan_em") || preset.slogan_em;
  document.getElementById("sg-slogan-b").textContent = queryParam("slogan_b") || preset.slogan_b;
  document.getElementById("sg-desc").textContent = queryParam("desc") || preset.desc;
  document.getElementById("sg-banner-ghost").textContent = queryParam("banner") || preset.banner;

  // 下一场：服务端在 content_url 里带 ?next=19:43 – 20:43 产品评审会
  const nextFromQuery = queryParam("next");
  if (nextFromQuery) {
    document.getElementById("sg-next").textContent = nextFromQuery;
    document.getElementById("sg-next-sub").textContent = queryParam("next_sub")
      ? "· " + queryParam("next_sub")
      : "";
  } else {
    document.getElementById("sg-next").textContent = d.up_next;
    document.getElementById("sg-next-sub").textContent = d.up_next_sub;
  }

  document.getElementById("sg-status-text").textContent =
    queryParam("status") || (slot === "evening" ? "设备在线 · 今日日程已结束" : d.status);

  // 右上时钟（时区随 query tz 覆盖，默认会议室时区）
  const tz = queryParam("tz") || d.timezone;
  document.getElementById("sg-tz").textContent = fmtDateCN(new Date(), tz) + " · " + tz;
  startClock((date) => {
    document.getElementById("sg-time").textContent = fmtTime(date, tz);
    document.getElementById("sg-tz").textContent =
      fmtDateCN(date, tz) + " · " + tz;
  });
}

/* ============================================================
   S6 待绑定屏（开机展示 device_id，A1）
   ============================================================ */
function initBootPage() {
  const d = displayData("boot");
  const deviceId = queryParam("device_id") || d.device_id;

  document.getElementById("bt-code").textContent = deviceId;
  document.getElementById("bt-name").textContent = d.device_name;
  document.getElementById("bt-firmware").textContent = d.firmware;
  document.getElementById("bt-agent").textContent = d.agent_version;
}
