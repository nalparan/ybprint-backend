from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pypdf import PdfReader
import io

app = FastAPI()

# 웹페이지 통신 허용 (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"status": "ok", "message": "GEMS AI PDF Backend Running"}

@app.post("/scan-pdf")
async def scan_pdf(file: UploadFile = File(...)):
    contents = await file.read()
    reader = PdfReader(io.BytesIO(contents))
    
    # 1. 전체 페이지 수 즉시 파싱
    total_pages = len(reader.pages)
    
    # 2. 첫 페이지 크기 파싱 (pt -> mm 환산 : 1pt = 0.352778mm)
    first_page = reader.pages[0]
    width_pt = float(first_page.mediabox.width)
    height_pt = float(first_page.mediabox.height)
    
    width_mm = round(width_pt * 0.352778, 1)
    height_mm = round(height_pt * 0.352778, 1)
    
    # 3. 대표 상위 10페이지 이미지 객체만 파싱 (서버 메모리 폭주 완전 방지)
    max_scan_pages = min(total_pages, 10)
    image_count = 0
    
    for i in range(max_scan_pages):
        page = reader.pages[i]
        try:
            images = page.images
            image_count += len(images)
        except Exception:
            pass

    return {
        "filename": file.filename,
        "real_data": {
            "total_pages": total_pages,
            "dimension_pt": {
                "width_pt": round(width_pt, 2),
                "height_pt": round(height_pt, 2)
            },
            "dimension_mm": {
                "width": width_mm,
                "height": height_mm
            },
            "images_summary": {
                "total_count": image_count,
                "scanned_pages": max_scan_pages
            }
        }
    }
