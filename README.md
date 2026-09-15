# LINE Group Notification — ตัวอย่างระบบแจ้งเตือน

## ติดตั้งและรัน

```bash
pip install -r requirements.txt

export LINE_CHANNEL_ACCESS_TOKEN="xxxxx"   # จาก LINE Developers Console
export LINE_GROUP_ID="Cxxxxxxxxxxxxxxxx"   # group id ที่ดึงมาจาก webhook

uvicorn main:app --reload --port 8000
```

## ทดสอบกรณีที่ 1 (user แจ้งก่อน -> assign ทีหลัง)

```bash
# 1) user พิมพ์ฝากข้อความ -> ยิง LINE แจ้งเตือน #1
curl -X POST http://localhost:8000/messages \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u001","user_name":"คุณสมชาย","message":"แอร์ไม่เย็น ห้อง 302"}'

# response: {"ticket_id": 1, "status": "pending"}

# 2) เจ้าหน้าที่ assign ช่าง -> ยิง LINE แจ้งเตือน #2
curl -X PATCH http://localhost:8000/tickets/1/assign \
  -H "Content-Type: application/json" \
  -d '{"technician_id":"t01","technician_name":"ช่างเอ","assigned_by":"แอดมินบี"}'
```

## ทดสอบกรณีที่ 2 (จนท. สร้างงานเอง + assign พร้อมกัน)

```bash
curl -X POST http://localhost:8000/tickets/staff-create \
  -H "Content-Type: application/json" \
  -d '{"message":"ตรวจเช็คลิฟต์ตัวที่ 2","created_by":"แอดมินบี","technician_id":"t02","technician_name":"ช่างซี"}'
```

## จุดที่ควรทำต่อ (production checklist)

- [ ] เปลี่ยน in-memory dict ใน `main.py` เป็น database จริง (Postgres/MySQL) + ORM
- [ ] เพิ่ม authentication บน endpoint เหล่านี้ (JWT/session) ไม่ให้ยิงมั่ว
- [ ] เพิ่ม webhook endpoint แยกต่างหากสำหรับดึง `LINE_GROUP_ID` ตอน setup ครั้งแรก
- [ ] ทำ retry queue (เช่น ใช้ Celery/RQ) แทนการยิง push แบบ sync ตรงๆ ถ้าปริมาณงานเยอะ
- [ ] Log การแจ้งเตือนที่ fail ไว้ตรวจสอบย้อนหลัง (ตอนนี้แค่ log error เฉยๆ ไม่ retry)
- [ ] ถ้าอยากให้ข้อความสวยขึ้น เปลี่ยนจาก text message เป็น Flex Message (LINE รองรับการ์ดสวยๆ)
