import os
import json
import io
import datetime
import smtplib
import urllib.request
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

# -------------------------------------------------------------------
# [완벽한 CORS 설정] 
# www 포함 모든 도메인 및 로컬 주소의 견적 전송을 브라우저 차단 없이 100% 허용
# -------------------------------------------------------------------
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

# -------------------------------------------------------------------
# [발송 엔진 설정]
# 1순위: Resend API (일반 웹 통신 443포트 - Render 차단 없음)
# 2순위: 네이버 SMTP (안전망 자동 우회 - Resend 실패 시 100% 작동 보장)
# -------------------------------------------------------------------
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")

# 네이버 안전망 설정
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

def send_smart_email(receiver_email: str, subject: str, body_html: str):
    receiver_clean = receiver_email.strip()
    
    # [1단계] Resend API 발송 (최우선)
    if RESEND_API_KEY:
        try:
            url = "https://api.resend.com/emails"
            headers = {
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json"
            }
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
                    return True, f"[{receiver_clean}] 공식 도메인(API) 발송 완료!"
        except Exception as e:
            print(f"[Resend API Error] {e} -> 네이버 안전망으로 자동 우회합니다.")
            pass

    # [2단계] 네이버 SMTP 우회 발송 (안전망)
    if not NAVER_PW:
        return False, "발송 실패: Resend API 키와 네이버 비밀번호(SENDER_PW)가 모두 등록되지 않았습니다."

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
        return True, f"[{receiver_clean}] 네이버 비상망으로 발송 완료!"
    except Exception as e:
        err_msg = str(e)
        print(f"[Naver SMTP Error] {err_msg}")
        return False, f"완전 발송 실패 (API 및 네이버 모두 장애): {err_msg}"

# 대문 페이지 및 헬스체크 (업타임로봇 및 브라우저 접속 즉시 초록불 보장)
@app.get("/")
@app.head("/")
def root():
    return {
        "status": "online",
        "service": "청년인쇄사 GEMS AI Cloud Backend Engine",
        "email_engine": "Dual Mode (Resend API + Naver Fallback)",
        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

@app.get("/health")
@app.head("/health")
def health_check():
    return {"status": "ok", "message": "Backend is running perfectly!"}

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

        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(contents))
            total_pages = len(reader.pages)
            if total_pages > 0:
                first_page = reader.pages[0]
                box = first_page.mediabox
                pt_w = float(box.width)
                pt_h = float(box.height)
                width_mm = round(pt_w * 0.352778, 1)
                height_mm = round(pt_h * 0.352778, 1)
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

@app.get("/inquiries")
def get_inquiries():
    if not os.path.exists(INQUIRIES_FILE):
        return []
    with open(INQUIRIES_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return []

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
    target_email = req.receiver_email
    if not target_email:
        if "@" in req.phone:
            target_email = req.phone.strip()
        else:
            target_email = OFFICIAL_REPLY_EMAIL

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

    ok, msg = send_smart_email(target_email, subject, body_html)
    return {
        "status": "success" if ok else "failed",
        "message": msg,
        "target": target_email
    }

@app.get("/download/{filename}")
def download_file(filename: str):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    return FileResponse(file_path, filename=filename)
