"""
main.py
ตัวอย่าง FastAPI endpoints ครอบคลุม 2 กรณีตามที่ต้องการ

กรณีที่ 1: user พิมพ์ฝากข้อความ -> แจ้งเตือน #1 -> จนท. assign -> แจ้งเตือน #2
กรณีที่ 2: จนท. สร้างงาน + assign พร้อมกัน -> แจ้งเตือนครั้งเดียว
"""

# pyrefly: ignore [missing-import]
from line_client import LINE_GROUP_ID
# pyrefly: ignore [missing-import]
from fastapi import FastAPI, HTTPException, Request, Header
# pyrefly: ignore [missing-import]
from fastapi.responses import FileResponse
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
# pyrefly: ignore [missing-import]
from pydantic import BaseModel
from datetime import datetime
import hashlib
import hmac
import base64

from line_client import (
    push_to_group,
    build_new_message_text,
    build_assigned_text,
    push_mention_message,
    LINE_CHANNEL_SECRET,
)

app = FastAPI()

# เปิด CORS สำหรับตอนทดสอบเท่านั้น — ตอนขึ้น production ให้เปลี่ยน allow_origins
# เป็นโดเมนจริงของเว็บทดสอบ/เว็บของเพื่อนคุณ อย่าใช้ "*" ในระบบจริง
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ตัวอย่าง in-memory store (ของจริงให้เปลี่ยนเป็น database)
TICKETS: dict[int, dict] = {}
_next_id = 1

# mapping ชื่อช่าง (technician_id) -> LINE userId
# วิธีใช้งานสำหรับทีมขนาดเล็ก: 
# 1. ให้ช่างพิมพ์ "ลงทะเบียนช่าง ชื่อ" ในกลุ่ม
# 2. บอทจะตอบกลับพร้อม "รหัสประจำตัว (User ID)" ที่ขึ้นต้นด้วยตัว U
# 3. นำรหัสที่บอทตอบกลับ มาใส่ใน Dictionary ด้านล่างนี้แทนที่ของเดิมได้เลย!
TECHNICIAN_LINE_IDS: dict[str, str] = {
    "ช่างแป้ง": "U42afcb075b5ef5a3dc1535402cb4038f",# ตัวอย่าง
    "ช่างฟ้า": "", # ตัวอย่าง
    "ช่างพลู": "Ub5559f13877cfb14f9afd3e76220b972", # ตัวอย่าง

    # เพิ่มชื่อช่างทั้ง 7 คนของคุณที่นี่...
}


def _new_id() -> int:
    global _next_id
    ticket_id = _next_id
    _next_id += 1
    return ticket_id


# ---------- กรณีที่ 1: user พิมพ์ฝากข้อความ ----------

class NewMessageIn(BaseModel):
    user_id: str
    user_name: str
    message: str


@app.post("/messages")
async def create_message(payload: NewMessageIn):
    """
    Step 1 ของกรณีที่ 1: user พิมพ์ฝากข้อความถึงช่างเข้ามาในระบบ
    -> บันทึก ticket สถานะ pending
    -> ยิงแจ้งเตือน LINE #1 ทันที (ยังไม่มีการ assign)
    """
    ticket_id = _new_id()
    TICKETS[ticket_id] = {
        "id": ticket_id,
        "message": payload.message,
        "source": "user",
        "status": "pending",
        "created_by": payload.user_id,
        "assigned_to": None,
        "assigned_by": None,
        "created_at": datetime.utcnow().isoformat(),
    }

    text = build_new_message_text(ticket_id, payload.user_name, payload.message)
    await push_to_group(text)

    return {"ticket_id": ticket_id, "status": "pending"}


# ---------- ใช้ร่วมกันทั้ง 2 กรณี: assign งาน ----------

class AssignIn(BaseModel):
    technician_id: str
    technician_name: str
    assigned_by: str  # ชื่อ/ไอดีเจ้าหน้าที่ที่กด assign


@app.patch("/tickets/{ticket_id}/assign")
async def assign_ticket(ticket_id: int, payload: AssignIn):
    """
    Step 2 ของกรณีที่ 1: เจ้าหน้าที่ assign งานให้ช่าง
    -> ยิงแจ้งเตือน LINE #2 (งานถูก assign แล้ว)
    """
    ticket = TICKETS.get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="ticket not found")

    ticket["assigned_to"] = payload.technician_id
    ticket["assigned_by"] = payload.assigned_by
    ticket["status"] = "assigned"

    text = build_assigned_text(
        ticket_id=ticket_id,
        technician_name=payload.technician_name,
        assigned_by=payload.assigned_by,
        source=ticket["source"],  # "user" -> ใช้ข้อความแบบกรณีที่ 1
    )
    await _notify_assigned(text, payload.technician_id, payload.technician_name)

    return {"ticket_id": ticket_id, "status": "assigned"}


# ---------- กรณีที่ 2: จนท. สร้างงานเอง + assign พร้อมกัน ----------

class StaffCreateIn(BaseModel):
    message: str
    created_by: str          # เจ้าหน้าที่ที่สร้างงาน
    technician_id: str
    technician_name: str


@app.post("/tickets/staff-create")
async def staff_create_and_assign(payload: StaffCreateIn):
    """
    กรณีที่ 2: เจ้าหน้าที่สร้างงานเองและ assign ในขั้นตอนเดียว
    -> บันทึก ticket สถานะ assigned ทันที
    -> ยิงแจ้งเตือน LINE ครั้งเดียว (ไม่ต้องมี 2 รอบเหมือนกรณีที่ 1)
    """
    ticket_id = _new_id()
    TICKETS[ticket_id] = {
        "id": ticket_id,
        "message": payload.message,
        "source": "staff",
        "status": "assigned",
        "created_by": payload.created_by,
        "assigned_to": payload.technician_id,
        "assigned_by": payload.created_by,
        "created_at": datetime.utcnow().isoformat(),
    }

    text = build_assigned_text(
        ticket_id=ticket_id,
        technician_name=payload.technician_name,
        assigned_by=payload.created_by,
        source="staff",  # -> ใช้ข้อความแบบกรณีที่ 2
    )
    await _notify_assigned(text, payload.technician_id, payload.technician_name)

    return {"ticket_id": ticket_id, "status": "assigned"}


async def _notify_assigned(text: str, technician_id: str, technician_name: str) -> None:
    """
    ยิงแจ้งเตือน assign — ถ้าช่างลงทะเบียน LINE userId ไว้แล้ว จะ @ ชื่อจริงในกลุ่ม
    ถ้ายังไม่ได้ลงทะเบียน จะยิงเป็นข้อความธรรมดา (ไม่ @ ใคร)
    """
    line_user_id = TECHNICIAN_LINE_IDS.get(technician_id)
    if line_user_id:
        await push_mention_message(text, mention_name=technician_name, mention_user_id=line_user_id)
    else:
        await push_to_group(text)


# ---------- Webhook: จับ LINE userId ของช่าง และ Group ID ตอนลงทะเบียนในกลุ่ม ----------

REGISTER_KEYWORD = "ลงทะเบียนช่าง"  # ช่างพิมพ์ "ลงทะเบียนช่าง ช่างเอ" ในกลุ่ม
LAST_GROUP_ID: str = None


def _verify_line_signature(body: bytes, signature: str) -> bool:
    """ตรวจสอบว่า request มาจาก LINE จริง ไม่ใช่คนอื่นปลอมมายิง webhook"""
    hash_ = hmac.new(LINE_CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    expected_signature = base64.b64encode(hash_).decode("utf-8")
    return hmac.compare_digest(expected_signature, signature)


@app.post("/line/webhook")
async def line_webhook(request: Request, x_line_signature: str = Header(None)):
    global LAST_GROUP_ID
    body = await request.body()

    if not x_line_signature or not _verify_line_signature(body, x_line_signature):
        raise HTTPException(status_code=400, detail="invalid signature")

    payload = await request.json()

    for event in payload.get("events", []):
        source = event.get("source", {})
        if source.get("type") == "group":
            LAST_GROUP_ID = source.get("groupId")
            print(f"📌 พบ Group ID: {LAST_GROUP_ID}")

        if event.get("type") != "message":
            continue
        message = event.get("message", {})
        if message.get("type") != "text":
            continue

        text = message.get("text", "").strip()
        user_id = source.get("userId")
        group_id = source.get("groupId")

        if text.startswith(REGISTER_KEYWORD) and user_id:
            # ตัวอย่าง: "ลงทะเบียนช่าง ช่างเอ" -> technician_id = "ช่างเอ"
            technician_id = text.replace(REGISTER_KEYWORD, "", 1).strip()
            if technician_id:
                TECHNICIAN_LINE_IDS[technician_id] = user_id
                target_id = group_id or LINE_GROUP_ID
                reply_text = (
                    f"ลงทะเบียน {technician_id} ชั่วคราวเรียบร้อย ✅\n\n"
                    f"⚠️ กรุณาก๊อปปี้รหัสประจำตัวด้านล่างนี้ไปให้แอดมินใส่ในโค้ด (main.py) เพื่อบันทึกถาวร:\n\n"
                    f"{user_id}"
                )
                await push_to_group(reply_text, group_id=target_id)

    return {"status": "ok"}


@app.get("/technicians")
async def list_technicians():
    """ดูรายชื่อช่างที่ลงทะเบียน LINE userId ไว้แล้ว"""
    return TECHNICIAN_LINE_IDS


@app.get("/group-id")
async def get_group_id():
    """ดู Group ID ล่าสุดที่จับได้จาก webhook"""
    return {
        "last_captured_group_id": LAST_GROUP_ID,
        "current_configured_group_id": LINE_GROUP_ID,
        "note": "Group ID ใน LINE จะขึ้นต้นด้วย C (เช่น Cxxxxxxxx...), หาก current_configured_group_id ขึ้นต้นด้วย U แสดงว่าเป็น User ID (แชทส่วนตัว)"
    }


@app.get("/test")
async def serve_test_console():
    return FileResponse("test_console.html")