from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import fitz  # PyMuPDF

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory inquiry store
inquiries_db = []

@app.get("/")
def read_root():
    return {"status": "ok", "message": "YBPRINT AI Backend is running 24/7 on Render!"}

@app.get("/inquiries")
def get_inquiries():
    return inquiries_db

@app.post("/scan-pdf")
async def scan_pdf(file: UploadFile = File(...)):
    try:
        content = await file.read()
        doc = fitz.open(stream=content, filetype="pdf")
        total_pages = len(doc)
        
        # Check first page size
        page = doc[0]
        rect = page.rect
        # Points to mm (1 pt = 0.352778 mm)
        w_mm = round(rect.width * 0.352778)
        h_mm = round(rect.height * 0.352778)
        
        # Check images
        image_list = page.get_images(full=True)
        img_count = len(image_list)
        
        return {
            "filename": file.filename,
            "real_data": {
                "total_pages": total_pages,
                "dimension_mm": {"width": w_mm, "height": h_mm},
                "images_summary": {"total_count": img_count}
            }
        }
    except Exception as e:
        return {
            "filename": file.filename,
            "real_data": {
                "total_pages": 1,
                "dimension_mm": {"width": 210, "height": 297},
                "images_summary": {"total_count": 0}
            },
            "error": str(e)
        }

@app.post("/submit-inquiry")
async def submit_inquiry(
    org: str = Form(...),
    phone: str = Form(...),
    inquiry: str = Form(""),
    file_name: str = Form("첨부파일 없음"),
    spec: str = Form("-")
):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record = {
        "timestamp": now_str,
        "org": org,
        "phone": phone,
        "inquiry": inquiry,
        "file_name": file_name,
        "spec": spec
    }
    inquiries_db.append(record)
    
    print("=" * 60)
    print(" 🎉 [청년인쇄사 GEMS AI - 새로운 견적 문의 접수]")
    print(f" • 접수일시 : {now_str}")
    print(f" • 소속/이름 : {org}")
    print(f" • 연 락 처 : {phone}")
    print(f" • 첨부원고 : {file_name}")
    print(f" • 검수사양 : {spec}")
    print(f" • 문의내용 : {inquiry}")
    print("=" * 60)
    
    return {"status": "success", "message": "Inquiry recorded successfully", "data": record}
