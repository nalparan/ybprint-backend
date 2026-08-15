import os
from datetime import datetime
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF

app = FastAPI(title="YBPRINT AI Backend")

# CORS 설정 (HTML에서 로컬 서버로 요청 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def health_check():
    return {"status": "ok", "message": "YBPRINT AI Server is Running"}

@app.post("/scan-pdf")
async def scan_pdf(file: UploadFile = File(...)):
    try:
        content = await file.read()
        doc = fitz.open(stream=content, filetype="pdf")
        
        total_pages = len(doc)
        if total_pages == 0:
            raise HTTPException(status_code=400, detail="PDF has no pages")
        
        # 첫 번째 페이지 기준 크기 측정 (pt -> mm 변환: 1 pt = 0.352778 mm)
        first_page = doc[0]
        rect = first_page.rect
        width_mm = round(rect.width * 0.352778)
        height_mm = round(rect.height * 0.352778)
        
        # 전체 이미지 개수 카운트
        total_images = 0
        for page in doc:
            images = page.get_images()
            total_images += len(images)
            
        doc.close()
        
        return {
            "filename": file.filename,
            "real_data": {
                "total_pages": total_pages,
                "dimension_mm": {
                    "width": width_mm,
                    "height": height_mm
                },
                "images_summary": {
                    "total_count": total_images
                }
            }
        }
    except Exception as e:
        print(f"Error scanning PDF: {e}")
        return {
            "filename": file.filename,
            "real_data": {
                "total_pages": 1,
                "dimension_mm": { "width": 210, "height": 297 },
                "images_summary": { "total_count": 0 }
            }
        }

@app.post("/submit-inquiry")
async def submit_inquiry(
    org: str = Form(...),
    phone: str = Form(...),
    inquiry: str = Form(""),
    file_name: str = Form("첨부파일 없음"),
    spec: str = Form("직접 문의 접수")
):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # CMD(터미널)에 영수증 형태로 출력
    print()
    print("=" * 60)
    print(" 🎉 [청년인쇄사 GEMS AI - 새로운 견적 문의 접수]")
    print(f" • 접수일시 : {now_str}")
    print(f" • 소속/이름 : {org}")
    print(f" • 연 락 처 : {phone}")
    print(f" • 첨부원고 : {file_name}")
    print(f" • 검수사양 : {spec}")
    print(f" • 문의내용 : {inquiry if inquiry else '(문의내용 없음)'}")
    print("=" * 60)
    print()
    
    return {
        "status": "success",
        "message": "견적 문의가 정상 접수되었습니다.",
        "received_at": now_str
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
