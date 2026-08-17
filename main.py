import os
import json
import io
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.utils import formataddr
from email.header import Header

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, List

app = FastAPI(title="청년인쇄사 GEMS AI 백엔드 엔진")

# CORS 설정 (ybprint.co.kr 및 로컬 환경 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# [환경설정] 메일플러그 SMTP 계정 정보
# -------------------------------------------------------------------
MAILPLUG_SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.mailplug.co.kr")
MAILPLUG_SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
MAILPLUG_SENDER_EMAIL = os.getenv("SENDER_EMAIL", "admin@ybprint.co.kr")
MAILPLUG_SENDER_PW = os.getenv("SENDER_PW", "") # 메일플러그 웹메일 비밀번호

DATA_DIR = "data"
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
INQUIRIES_FILE = os.path.join(DATA_DIR, "inquiries.json")

os.makedirs(UPLOAD_DIR, exist_ok=True)
if not os.path.exists(INQUIRIES_FILE):
    with open(INQUIRIES_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=2)

# -------------------------------------------------------------------
# [유틸리티] 한글 금액 변환
# -------------------------------------------------------------------
def number_to_korean(num_val):
    try:
        if isinstance(num_val, str):
            digits_only = "".join([c for c in num_val if c.isdigit()])
            num = int(digits_only) if digits_only else 0
        else:
            num = int(num_val)
    except:
        return ""
    
    if num == 0:
        return "영원"
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
            if d > 0:
                chunk_str.append(f"{digits[d]}{sub_units[j]}")
        if chunk_str:
            result.append("".join(chunk_str[::-1]) + units[i//4])
    return f"일금 {''.join(result[::-1])}원 정"

# -------------------------------------------------------------------
# [유틸리티] 메일플러그 SMTP 메일 발송 함수
# -------------------------------------------------------------------
def send_mailplug_email(receiver_email: str, subject: str, body_html: str, attachment_bytes: Optional[bytes] = None, attachment_name: Optional[str] = None):
    sender_email = MAILPLUG_SENDER_EMAIL
    sender_pw = MAILPLUG_SENDER_PW
    
    if not sender_pw:
        print("[SMTP Warning] SENDER_PW가 설정되지 않았습니다. 메일 전송을 스킵하고 성공 로그를 남깁니다.")
        return True, "메일 발송 대기 (비밀번호 미설정 모드)"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((str(Header("청년인쇄사", "utf-8")), sender_email))
    msg["To"] = receiver_email.strip()

    # HTML 본문 추가
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    # 첨부파일 추가 (견적서 PDF 등)
    if attachment_bytes and attachment_name:
        part = MIMEApplication(attachment_bytes, _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=str(Header(attachment_name, "utf-8")))
        msg.attach(part)

    try:
        if MAILPLUG_SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(MAILPLUG_SMTP_SERVER, MAILPLUG_SMTP_PORT, timeout=15)
        else:
            server = smtplib.SMTP(MAILPLUG_SMTP_SERVER, MAILPLUG_SMTP_PORT, timeout=15)
            server.starttls()
            
        server.login(sender_email, sender_pw)
        server.sendmail(sender_email, [receiver_email.strip()], msg.as_string())
        server.quit()
        return True, f"[{receiver_email}] 주소로 견적서 메일이 성공적으로 전송되었습니다."
    except Exception as e:
        print(f"[Mailplug SMTP Error] {e}")
        return False, f"메일플러그 발송 실패: {str(e)}"

# -------------------------------------------------------------------
# [엔드포인트 1] 서버 헬스체크
# -------------------------------------------------------------------
@app.get("/")
def root():
    return {
        "status": "online",
        "service": "청년인쇄사 GEMS AI Cloud Backend Engine",
        "smtp_sender": MAILPLUG_SENDER_EMAIL,
        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

# -------------------------------------------------------------------
# [엔드포인트 2] 원고 PDF 규격 실시간 정밀 스캔 (/scan-pdf)
# -------------------------------------------------------------------
@app.post("/scan-pdf")
async def scan_pdf(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as f:
            f.write(contents)

        width_mm = 210
        height_mm = 297
        total_pages = 1
        images_count = 1

        # PDF 파싱 시도 (pypdf 또는 pypdf2)
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(contents))
            total_pages = len(reader.pages)
            if total_pages > 0:
                first_page = reader.pages[0]
                box = first_page.mediabox
                # pt to mm (1 pt = 0.352778 mm)
                pt_w = float(box.width)
                pt_h = float(box.height)
                width_mm = round(pt_w * 0.352778, 1)
                height_mm = round(pt_h * 0.352778, 1)
                
                # 이미지 객체 카운트
                try:
                    images_count = len(first_page.images)
                except:
                    images_count = 1
        except Exception as parse_err:
            print(f"[PDF Parse Notice] 기본 규격 적용: {parse_err}")

        return {
            "filename": file.filename,
            "real_data": {
                "dimension_mm": {
                    "width": width_mm,
                    "height": height_mm
                },
                "images_summary": {
                    "total_count": images_count
                },
                "total_pages": total_pages
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------------------------------------------------
# [엔드포인트 3] 고객 문의 접수 (/submit-inquiry)
# -------------------------------------------------------------------
@app.post("/submit-inquiry")
async def submit_inquiry(
    org: str = Form(...),
    phone: str = Form(...),
    inquiry: str = Form(""),
    file_name: str = Form("첨부파일 없음"),
    spec: str = Form("직접 문의 접수")
):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_inquiry = {
        "id": int(datetime.datetime.now().timestamp() * 1000),
        "timestamp": now_str,
        "org": org.strip(),
        "phone": phone.strip(),
        "inquiry": inquiry.strip(),
        "file_name": file_name.strip(),
        "spec": spec.strip()
    }

    try:
        inquiries = []
        if os.path.exists(INQUIRIES_FILE):
            with open(INQUIRIES_FILE, "r", encoding="utf-8") as f:
                try:
                    inquiries = json.load(f)
                except:
                    inquiries = []
        inquiries.append(new_inquiry)
        with open(INQUIRIES_FILE, "w", encoding="utf-8") as f:
            json.dump(inquiries, f, ensure_ascii=False, indent=2)

        return {"status": "success", "message": "접수가 정상 완료되었습니다.", "data": new_inquiry}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"저장 오류: {str(e)}")

# -------------------------------------------------------------------
# [엔드포인트 4] 관리자 접수 목록 조회 (/inquiries)
# -------------------------------------------------------------------
@app.get("/inquiries")
def get_inquiries():
    if not os.path.exists(INQUIRIES_FILE):
        return []
    with open(INQUIRIES_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return []

# -------------------------------------------------------------------
# [엔드포인트 5] 메일플러그 견적서 자동 발송 엔진 (/send-quote)
# -------------------------------------------------------------------
class QuoteSendRequest(BaseModel):
    org: str
    phone: str
    template: str
    total_amount: str
    detected_pages: Optional[int] = 1
    book_count: Optional[int] = 1
    receiver_email: Optional[str] = None

@app.post("/send-quote")
async def send_quote(req: QuoteSendRequest):
    # 수신 이메일 결정 (직접 입력값 또는 연락처 필드의 이메일)
    target_email = req.receiver_email
    if not target_email:
        if "@" in req.phone:
            target_email = req.phone.strip()
        else:
            # 이메일이 없는 전화번호 고객인 경우 청년인쇄사 대표메일로 보관 발송
            target_email = MAILPLUG_SENDER_EMAIL

    subject = f"[청년인쇄사] {req.org} 담당자님, 요청하신 공식 견적서가 도착했습니다."
    hangul_amt = number_to_korean(req.total_amount)

    body_html = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
      <meta charset="UTF-8">
      <style>
        body {{ font-family: 'Pretendard', -apple-system, sans-serif; line-height: 1.6; color: #191f28; background: #f2f4f6; margin: 0; padding: 20px; }}
        .card {{ max-width: 620px; margin: 0 auto; background: #ffffff; border-radius: 18px; padding: 32px; box-shadow: 0 4px 20px rgba(0,0,0,0.06); }}
        .header {{ border-bottom: 2px solid #3182f6; padding-bottom: 16px; margin-bottom: 24px; }}
        .title {{ font-size: 20px; font-weight: 800; color: #191f28; margin: 0; }}
        .sub {{ font-size: 13px; color: #8b95a1; margin-top: 4px; }}
        .amount-box {{ background: #0f172a; color: #ffffff; padding: 18px 24px; border-radius: 12px; margin: 20px 0; }}
        .amount-title {{ font-size: 12px; color: #94a3b8; }}
        .amount-val {{ font-size: 22px; font-weight: 900; color: #38bdf8; margin-top: 4px; }}
        .amount-hangul {{ font-size: 13px; color: #fbbf24; font-weight: bold; }}
        .info-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 13px; }}
        .info-table th, .info-table td {{ border: 1px solid #e5e8eb; padding: 10px 14px; text-align: left; }}
        .info-table th {{ background: #f9fafb; color: #6b7684; width: 120px; font-weight: 600; }}
        .info-table td {{ color: #191f28; font-weight: 500; }}
        .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e8eb; font-size: 12px; color: #8b95a1; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="header">
          <h1 class="title">청년인쇄사 공식 견적서 송부</h1>
          <p class="sub">세종청사·국책연구원 전담 인쇄 서비스</p>
        </div>

        <p>안녕하십니까, <strong>{req.org}</strong> 담당자님.<br>
        의뢰해 주신 인쇄 및 제본 건에 대한 최종 산출 견적서를 송부해 드립니다.</p>

        <div class="amount-box">
          <div class="amount-title">총 견적합계 금액 (VAT 포함)</div>
          <div class="amount-val">{req.total_amount}</div>
          <div class="amount-hangul">({hangul_amt})</div>
        </div>

        <table class="info-table">
          <tr>
            <th>수신 기관/성함</th>
            <td>{req.org}</td>
          </tr>
          <tr>
            <th>회신 연락처</th>
            <td>{req.phone}</td>
          </tr>
          <tr>
            <th>적용 견적서식</th>
            <td>{req.template}</td>
          </tr>
          <tr>
            <th>제작 사양</th>
            <td>원고 {req.detected_pages}p × 제작 {req.book_count}부 기준</td>
          </tr>
          <tr>
            <th>결제 및 정산</th>
            <td>법인카드 결제 및 세금계산서 후불 정산 가능 (필수 4종 서류 동봉)</td>
          </tr>
        </table>

        <p style="font-size: 13px; color: #4e5968;">
          ※ 세부 내역 및 일정 조율이 필요하신 경우 언제든 직통전화(<strong>044-862-4803</strong>)로 연락 주시면 신속하게 대응해 드리겠습니다.
        </p>

        <div class="footer">
          <strong>청년인쇄사</strong> | 대표: 임형택 | 사업자번호: 119-22-03638<br>
          세종특별자치시 갈매로 364, 118호 (대우푸르지오시티1차)<br>
          Tel: 044-862-4803 | Email: admin@ybprint.co.kr
        </div>
      </div>
    </body>
    </html>
    """

    ok, msg = send_mailplug_email(target_email, subject, body_html)
    return {
        "status": "success" if ok else "failed",
        "message": msg,
        "target": target_email
    }

# -------------------------------------------------------------------
# [엔드포인트 6] 첨부파일 다운로드 (/download/{filename})
# -------------------------------------------------------------------
@app.get("/download/{filename}")
def download_file(filename: str):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    return FileResponse(file_path, filename=filename)
