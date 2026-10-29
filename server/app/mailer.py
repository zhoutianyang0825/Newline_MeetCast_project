"""邮件发送（F4.7 免登录上传链接的投递通道）

PRD v0.8 定稿：**邮件单通道**（Graph Mail.Send 以应用身份发）。
开发期无 Mail.Send 权限 → MAIL_MOCK=1 时只打印并落库（store.mail_log），
联调时能核"该发的人收到的是哪条链接"，不发真信。
"""

from __future__ import annotations

import httpx

from app import graph_client
from app.settings import MAIL_MOCK, PUBLIC_BASE
from app.tz import local_time_range

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def mail_body(meeting, token: str) -> tuple[str, str]:
    """生成上传链接邮件的标题与正文。

    得到的数据：
        meeting（Meeting 行）；token（免登录上传 token）。

    要做的操作：
        拼会议主题、本地时间、上传截止（会前 30 分钟）与链接。

    返回：
        ("【MeetCast】请上传「产品评审会」的会议素材",
         "会议时间：10:00 – 11:00（Asia/Shanghai）\n上传链接：...\n截止：会前 30 分钟")

    为什么：定会者只认邮件里的链接；正文必须写清"哪场会、什么时候截止"。
    """
    link = f"{PUBLIC_BASE}/ui/upload.html?token={token}"
    time_label = local_time_range(meeting.start_time_utc, meeting.end_time_utc, meeting.timezone)
    subject = f"【MeetCast】请上传「{meeting.subject}」的会议素材"
    body = (
        f"会议：{meeting.subject}\n"
        f"时间：{time_label}（{meeting.timezone}）\n"
        f"上传链接：{link}\n"
        f"截止：会议开始前 30 分钟\n\n"
        f"无需登录，点开即可上传；素材仅本场会议可见，会后自动清理。"
    )
    return subject, body


def send_upload_link(meeting, token: str) -> dict:
    """把上传链接发给会组织者。

    得到的数据：
        meeting（Meeting 行，organizer_email 为收件人）；token（免登录凭据）。

    要做的操作：
        MAIL_MOCK=1 → 打印 + 写进 store.mail_log（不真发）；
        否则调 Graph sendMail（应用身份，需 Mail.Send）。

    返回：
        {"to": "zhangsan@honghe.com", "subject": "...", "mock": True, "token": "tok_..."}

    为什么：F4.7 的通道必须是"服务端主动发"，否则定会者根本不知道该去上传。
    """
    from app.store import store

    subject, body = mail_body(meeting, token)
    record = {
        "to": meeting.organizer_email,
        "subject": subject,
        "body": body,
        "token": token,
        "meeting_id": meeting.meeting_id,
        "mock": MAIL_MOCK,
    }

    if MAIL_MOCK:
        # Mock 模式必须把链接打出来：定会者收不到真信，测试只能从日志里取链接去做场景 E
        print(f"[mail:mock] → {record['to']}  {subject}")
        print(f"[mail:mock]   链接：{PUBLIC_BASE}/ui/upload.html?token={token}")
        store.mail_log.append(record)
        return record

    access_token = graph_client._access_token()  # 复用 Graph 的 app-only token
    resp = httpx.post(
        f"{GRAPH_BASE}/users/{graph_client.GRAPH_CLIENT_ID}/sendMail",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": meeting.organizer_email}}],
            },
            "saveToSentItems": False,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return record
