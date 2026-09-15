"""
line_client.py
โมดูลกลางสำหรับยิง push message เข้ากลุ่ม LINE ผ่าน Messaging API
ใช้ร่วมกันได้ทั้งกรณีที่ 1 (user แจ้ง -> assign) และกรณีที่ 2 (จนท. สร้างงานเอง)
"""
 
import os
# pyrefly: ignore [missing-import]
import httpx
import logging
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
 
# โหลดค่าจากไฟล์ .env ที่อยู่โฟลเดอร์เดียวกัน (ถ้ามี)
# วิธีนี้กันปัญหา 'export'/'set' ไม่ทำงานตาม shell ที่ต่างกัน (Windows cmd, PowerShell, bash)
load_dotenv()
 
logger = logging.getLogger(__name__)
 
 
def _get_required_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(
            f"ไม่พบตัวแปร {key} — กรุณาสร้างไฟล์ .env ในโฟลเดอร์นี้ "
            f"แล้วเพิ่มบรรทัด {key}=ค่าของคุณ (ดูตัวอย่างใน .env.example)"
        )
    return value
 
 
LINE_CHANNEL_ACCESS_TOKEN = _get_required_env("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = _get_required_env("LINE_CHANNEL_SECRET")  # ใช้ตรวจสอบ webhook signature
LINE_GROUP_ID = _get_required_env("LINE_GROUP_ID")  # group id ที่ดึงมาจาก webhook ตอน setup
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
 
 
async def push_to_group(text: str, group_id: str = LINE_GROUP_ID) -> None:
    """
    ยิงข้อความ text เข้ากลุ่ม LINE ที่ group_id
    ไม่ raise exception ออกไปนอกฟังก์ชัน เพื่อไม่ให้การแจ้งเตือนที่ fail
    ไปทำให้ flow หลัก (บันทึก ticket / assign งาน) ล้มตามไปด้วย
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "to": group_id,
        "messages": [{"type": "text", "text": text}],
    }
 
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(LINE_PUSH_URL, headers=headers, json=payload)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error(f"LINE push failed: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        logger.error(f"LINE push error: {e}")
 
 
def _escape_v2_braces(text: str) -> str:
    """
    text message (v2) ใช้ { และ } เป็นตัวคั่น placeholder
    ถ้าข้อความจริงมี { หรือ } ปนอยู่ ต้อง escape เป็น {{ }} ไม่งั้น LINE จะตีความผิด
    """
    return text.replace("{", "{{").replace("}", "}}")
 
 
async def push_mention_message(
    body_text: str,
    mention_name: str,
    mention_user_id: str,
    group_id: str = LINE_GROUP_ID,
) -> None:
    """
    ยิงข้อความเข้ากลุ่ม พร้อม mention ช่างจริง (ต้องรู้ LINE userId ของช่างก่อน)
 
    ใช้ text message (v2) ของ LINE (type: "textV2") แทนแบบเก่า
    วิธีเก่า (type: "text" + mention.mentionees index/length) ทำให้ได้แค่ตัวหนังสือ
    "@ชื่อ" ธรรมดา ไม่ใช่ mention ที่กดได้จริง — v2 นี้ LINE จะแทนที่ {mention}
    ด้วย mention chip จริงที่กดดูโปรไฟล์ได้ และมีสีตามที่ LINE กำหนดเอง
    """
    escaped_body = _escape_v2_braces(body_text)
    full_text = f"{{mention}}\n{escaped_body}"
 
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "to": group_id,
        "messages": [
            {
                "type": "textV2",
                "text": full_text,
                "substitution": {
                    "mention": {
                        "type": "mention",
                        "mentionee": {
                            "type": "user",
                            "userId": mention_user_id,
                        },
                    }
                },
            }
        ],
    }
 
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(LINE_PUSH_URL, headers=headers, json=payload)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error(f"LINE mention push failed: {e.response.status_code} - {e.response.text}")
        # fallback: ถ้ายิง mention ไม่สำเร็จ ให้ยิงข้อความธรรมดาแทน ดีกว่าไม่แจ้งเตือนเลย
        await push_to_group(body_text, group_id)
    except Exception as e:
        logger.error(f"LINE mention push error: {e}")
        await push_to_group(body_text, group_id)
 
 
def build_new_message_text(ticket_id: int, user_name: str, message: str) -> str:
    """ข้อความแจ้งเตือน #1 : user เพิ่งฝากข้อความเข้ามา (กรณีที่ 1 ขั้นตอนแรก)"""
    return (
        f"🔔 มีข้อความใหม่จากลูกค้า\n"
        f"เลขงาน: #{ticket_id}\n"
        f"จาก: {user_name}\n"
        f"ข้อความ: {message}\n"
        f"สถานะ: รอมอบหมายช่าง"
    )
 
 
def build_assigned_text(ticket_id: int, technician_name: str, assigned_by: str, source: str) -> str:
    """
    ข้อความแจ้งเตือนตอน assign งาน
    ใช้ร่วมกันทั้งกรณีที่ 1 (assign ทีหลัง) และกรณีที่ 2 (สร้างพร้อม assign)
    """
    if source == "staff":
        return (
            f"✅ งานใหม่ถูกสร้างและมอบหมายแล้ว\n"
            f"เลขงาน: #{ticket_id}\n"
            f"มอบหมายให้: {technician_name}\n"
            f"สร้างโดย: {assigned_by}"
        )
    return (
        f"✅ งานถูกมอบหมายแล้ว\n"
        f"เลขงาน: #{ticket_id}\n"
        f"มอบหมายให้: {technician_name}\n"
        f"มอบหมายโดย: {assigned_by}"
    )
 