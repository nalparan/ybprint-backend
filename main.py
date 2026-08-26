import os
import json
import io
import datetime
import smtplib
import urllib.request
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from email.header import Header

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, List

app = FastAPI(title="청년인쇄사 GEMS AI 백엔드 엔진")

# --- CORS 및 환경 설정 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ybprint.co.kr",
        "https://www.ybprint.co.kr",
        "http://ybprint.co.kr",
        "http://www.ybprint.co.kr",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5500",
    ],
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
NAVER_EMAIL = os.getenv("NAVER_EMAIL", "serviceonm@naver.com")
NAVER_PW = os.getenv("NAVER_PW", os.getenv("SENDER_PW", ""))
OFFICIAL_REPLY_EMAIL = "admin@ybprint.co.kr"

DATA_DIR = "data"
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
INQUIRIES_FILE = os.path.join(DATA_DIR, "inquiries.json")

os.makedirs(UPLOAD_DIR, exist_ok=True)
if not os.path.exists(INQUIRIES_FILE):
    with open(INQUIRIES_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=2)

# --- 알리고 비동기 발송 모듈 ---
ALIGO_USERID = os.getenv("ALIGO_USERID", "")
ALIGO_APIKEY = os.getenv("ALIGO_APIKEY", "")
ALIGO_SENDER = os.getenv("ALIGO_SENDER", "")
ALIGO_SENDERKEY = os.getenv("ALIGO_SENDERKEY", "")

def send_aligo_alimtalk_bg(phone: str, org: str, template: str, book_count: int, pages: int, total_amount_str: str):
    """
    백그라운드에서 실행되며 실패하더라도 메인 시스템(메일/저장)에 영향을 주지 않음
    """
    if not all([ALIGO_USERID, ALIGO_APIKEY, ALIGO_SENDER, ALIGO_SENDERKEY]):
        print("[Aligo] 환경변수 누락으로 알림톡 발송 스킵")
        return

    try:
        digits_only = "".join([c for c in total_amount_str if c.isdigit()])
        total_num = int(digits_only) if digits_only else 0
        unit_price = total_num // max(1, book_count)
        
        amt_format = f"{total_num:,}"
        unit_format = f"{unit_price:,}"
        
        # 카카오 승인 규격과 100% 일치하는 본문
        message = f"""[청년인쇄사] 견적 안내드립니다.

{org} 담당자님, 청년인쇄사에 견적을 문의해 주셔서 감사합니다.
요청하신 공식 견적 내역을 안내해 드립니다.

■ 제작 사양 : {template}
■ 제작 수량 : {book_count}부 ({pages}p / 맞춤제본)
■ 총 견적금액 : {amt_format}원 (VAT 포함)
■ 1부당 단가 : {unit_format}원

아래 [견적서 확인하기] 버튼을 누르시면 정식 직인이 날인된 견적서(A4)를 열람 및 다운로드하실 수 있습니다.

☎ 직통 문의 : 044-862-4803"""

        button_info = {
            "button": [
                {
                    "name": "견적서 확인하기",
                    "linkType": "WL",
                    "linkPc": "https://ybprint.co.kr",
                    "linkMo": "https://ybprint.co.kr"
                }
            ]
        }

        # 1. 토큰 생성
        token_url = "https://kakaoapi.aligo.in/akv10/token/create/30/d/"
        token_data = urllib.parse.urlencode({'apikey': ALIGO_APIKEY, 'userid': ALIGO_USERID}).encode('utf-8')
        token_req = urllib.request.Request(token_url, data=token_data)
        
        with urllib.request.urlopen(token_req, timeout=5) as res:
            token_res = json.loads(res.read().decode('utf-8'))
            if token_res.get('code') != 0:
                print(f"[Aligo Token Error] {token_res.get('message')}")
                return
            token = token_res.get('token')

        # 2. 알림톡 발송
        send_url = "https://kakaoapi.aligo.in/akv10/alimtalk/send/"
        clean_phone = phone.replace("-", "").strip()
        
        send_data = {
            'apikey': ALIGO_APIKEY,
            'userid': ALIGO_USERID,
            'token': token,
            'senderkey': ALIGO_SENDERKEY,
            'tpl_code': 'UK_5781',
            'sender': ALIGO_SENDER,
            'receiver_1': clean_phone,
            'subject_1': '청년인쇄사 견적서 안내',
            'message_1': message,
            'button_1': json.dumps(button_info, ensure_ascii=False)
        }
        
        encoded_send_data = urllib.parse.urlencode(send_data).encode('utf-8')
        send_req = urllib.request.Request(send_url, data=encoded_send_data)
        
        with urllib.request.urlopen(send_req, timeout=5) as res:
            send_result = json.loads(res.read().decode('utf-8'))
            print(f"[Aligo Send Result] {send_result}")

    except Exception as e:
        print(f"[Aligo Background Error] {str(e)}")

# --- 한글 금액 변환 유틸리티 ---
def number_to_korean(num_val):
    try:
        if isinstance(num_val, str):
            digits_only = "".join([c for c in num_val if c.isdigit()])
            num = int(digits_only) if digits_only else 0
        else:
            num = int(num_val)
    except:
        return ""
    if num == 0: return "영원"
    units = ["", "만", "억", "조"]
    sub_units = ["", "십", "백", "천"]
    digits = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
    str_num = str(num)[::-1]
    result = []
    for i in range(0, len(str_num), 4):
        chunk = str_num[i:i+4]
        chunk_str = []
        for j, digit in enumerate(chunk):
            d = int(digit)
            if d > 0: chunk_str.append(f"{digits[d]}{sub_units[j]}")
        if chunk_str: result.append("".join(chunk_str[::-1]) + units[i//4])
    return f"일금 {''.join(result[::-1])}원 정"

# --- 스마트 이메일 발송 모듈 ---
def send_smart_email(receiver_email: str, subject: str, body_html: str):
    receiver_clean = receiver_email.strip()
    if RESEND_API_KEY:
        try:
            url = "https://api.resend.com/emails"
            headers = {"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"}
            data = {
                "from": "청년인쇄사 <admin@ybprint.co.kr>",
                "to": [receiver_clean],
                "subject": subject,
                "html": body_html,
                "reply_to": OFFICIAL_REPLY_EMAIL
            }
            req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=8) as response:
                if response.status in [200, 201]:
                    return True, f"[{receiver_clean}] API 발송 완료!"
        except Exception as e:
            print(f"[Resend API Error] {e}")
            pass

    if not NAVER_PW:
        return False, "발송 실패: 비밀번호 미등록"
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = formataddr((str(Header("청년인쇄사", "utf-8")), NAVER_EMAIL))
        msg["Reply-To"] = formataddr((str(Header("청년인쇄사", "utf-8")), OFFICIAL_REPLY_EMAIL))
        msg["To"] = receiver_clean
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        server = smtplib.SMTP_SSL("smtp.naver.com", 465, timeout=8)
        server.login(NAVER_EMAIL, NAVER_PW)
        server.sendmail(NAVER_EMAIL, [receiver_clean], msg.as_string())
        server.quit()
        return True, f"[{receiver_clean}] 네이버 비상망 발송 완료!"
    except Exception as e:
        return False, f"발송 실패: {str(e)}"

# --- 라우터 엔드포인트 ---
@app.get("/")
def root(): return {"status": "online", "service": "GEMS AI Backend"}

@app.get("/health")
def health_check(): return {"status": "ok"}

@app.post("/scan-pdf")
async def scan_pdf(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as f: f.write(contents)
        width_mm, height_mm, total_pages, images_count = 210, 297, 1, 1
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(contents))
            total_pages = len(reader.pages)
            if total_pages > 0:
                first_page = reader.pages[0]
                box = first_page.mediabox
                width_mm, height_mm = round(float(box.width) * 0.352778, 1), round(float(box.height) * 0.352778, 1)
                images_count = len(first_page.images) if hasattr(first_page, 'images') else 1
        except: pass
        return {"filename": file.filename, "real_data": {"dimension_mm": {"width": width_mm, "height": height_mm}, "images_summary": {"total_count": images_count}, "total_pages": total_pages}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/submit-inquiry")
async def submit_inquiry(org: str = Form(...), phone: str = Form(...), inquiry: str = Form(""), file_name: str = Form("첨부파일 없음"), spec: str = Form("직접 문의 접수"), file: Optional[List[UploadFile]] = File(None)):
    if file:
        for f in file:
            if f.filename:
                contents = await f.read()
                with open(os.path.join(UPLOAD_DIR, os.path.basename(f.filename)), "wb") as out_file: out_file.write(contents)
    new_inquiry = {"id": int(datetime.datetime.now().timestamp() * 1000), "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "org": org.strip(), "phone": phone.strip(), "inquiry": inquiry.strip(), "file_name": file_name.strip(), "spec": spec.strip()}
    try:
        inquiries = []
        if os.path.exists(INQUIRIES_FILE):
            with open(INQUIRIES_FILE, "r", encoding="utf-8") as f: inquiries = json.load(f)
        inquiries.append(new_inquiry)
        with open(INQUIRIES_FILE, "w", encoding="utf-8") as f: json.dump(inquiries, f, ensure_ascii=False, indent=2)
        return {"status": "success", "message": "접수 완료", "data": new_inquiry}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.get("/inquiries")
def get_inquiries():
    if not os.path.exists(INQUIRIES_FILE): return []
    with open(INQUIRIES_FILE, "r", encoding="utf-8") as f: return json.load(f)

class QuoteSendRequest(BaseModel):
    org: str
    phone: str
    template: str
    total_amount: str
    detected_pages: Optional[int] = 1
    book_count: Optional[int] = 1
    receiver_email: Optional[str] = None

@app.post("/send-quote")
async def send_quote(req: QuoteSendRequest, background_tasks: BackgroundTasks):
    target_email = req.receiver_email
    if not target_email:
        target_email = req.phone.strip() if "@" in req.phone else OFFICIAL_REPLY_EMAIL

    # 연락처 입력 시 백그라운드 알림톡 전송
    if "-" in req.phone or req.phone.isdigit():
        background_tasks.add_task(
            send_aligo_alimtalk_bg,
            req.phone, req.org, req.template, req.book_count, req.detected_pages, req.total_amount
        )

    # 이메일 발송
    subject = f"[청년인쇄사] {req.org} 담당자님, 요청하신 공식 견적서가 도착했습니다."
    hangul_amt = number_to_korean(req.total_amount)
    body_html = f"""
    <!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
    <style>
      body {{ font-family: 'Pretendard', sans-serif; line-height: 1.6; color: #191f28; background: #f2f4f6; padding: 20px; }}
      .card {{ max-width: 620px; margin: 0 auto; background: #ffffff; border-radius: 18px; padding: 32px; box-shadow: 0 4px 20px rgba(0,0,0,0.06); }}
      .header {{ border-bottom: 2px solid #3182f6; padding-bottom: 16px; margin-bottom: 24px; }}
      .title {{ font-size: 20px; font-weight: 800; margin: 0; }}
      .sub {{ font-size: 13px; color: #8b95a1; margin-top: 4px; }}
      .amount-box {{ background: #0f172a; color: #ffffff; padding: 18px 24px; border-radius: 12px; margin: 20px 0; }}
      .amount-val {{ font-size: 22px; font-weight: 900; color: #38bdf8; margin-top: 4px; }}
      .info-table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin: 20px 0; }}
      .info-table th, .info-table td {{ border: 1px solid #e5e8eb; padding: 10px; text-align: left; }}
      .info-table th {{ background: #f9fafb; width: 120px; }}
      .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e8eb; font-size: 12px; color: #8b95a1; }}
    </style></head>
    <body>
      <div class="card">
        <div class="header"><h1 class="title">청년인쇄사 공식 견적서 송부</h1><p class="sub">세종청사·국책연구원 전담 인쇄 서비스</p></div>
        <p><strong>{req.org}</strong> 담당자님.<br>의뢰해 주신 견적서를 송부해 드립니다.</p>
        <div class="amount-box">
          <div style="font-size: 12px; color: #94a3b8;">총 견적합계 금액 (VAT 포함)</div>
          <div class="amount-val">{req.total_amount} <span style="font-size:13px; color:#fbbf24;">({hangul_amt})</span></div>
        </div>
        <table class="info-table">
          <tr><th>수신 기관</th><td>{req.org}</td></tr>
          <tr><th>제작 사양</th><td>{req.template}</td></tr>
          <tr><th>제작 수량</th><td>원고 {req.detected_pages}p × {req.book_count}부</td></tr>
        </table>
        <div class="footer">청년인쇄사 | Tel: 044-862-4803 | Email: admin@ybprint.co.kr</div>
      </div>
    </body></html>
    """
    
    ok, msg = send_smart_email(target_email, subject, body_html)
    return {"status": "success" if ok else "failed", "message": msg, "target": target_email}

@app.get("/download/{filename:path}")
def download_file(filename: str):
    decoded_name = urllib.parse.unquote(filename).strip()
    file_path = os.path.join(UPLOAD_DIR, decoded_name)
    if not os.path.exists(file_path) and os.path.exists(UPLOAD_DIR):
        for existing in os.listdir(UPLOAD_DIR):
            if existing == decoded_name or existing == filename:
                file_path = os.path.join(UPLOAD_DIR, existing)
                decoded_name = existing
                break
    if not os.path.exists(file_path): raise HTTPException(status_code=404, detail="파일 없음")
    encoded_name = urllib.parse.quote(decoded_name)
    return FileResponse(file_path, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"}, media_type="application/octet-stream")
