import io
import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
import pypdf

app = FastAPI(title="청년인쇄사 AI - Real PDF Scan Engine API")

# 허용할 CORS 설정을 통해 프론트엔드(v33 웹페이지)와의 통신 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"status": "online", "message": "청년인쇄사 AI 백엔드 서버 가동 중"}

@app.post("/scan-pdf")
async def scan_pdf(file: UploadFile = File(...)):
    # 파일 확장자 검증
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="PDF 파일만 분석 가능합니다.")

    try:
        pdf_bytes = await file.read()
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))

        # 1. 실제 총 페이지 수 파싱
        total_pages = len(reader.pages)
        if total_pages == 0:
            raise HTTPException(status_code=400, detail="페이지가 없는 빈 PDF 파일입니다.")

        # 2. 실제 문서 규격 파싱 (첫 페이지 좌표 -> mm 환산)
        first_page = reader.pages[0]
        mediabox = first_page.mediabox
        width_pt = float(mediabox.width)
        height_pt = float(mediabox.height)

        width_mm = round(width_pt * 25.4 / 72, 1)
        height_mm = round(height_pt * 25.4 / 72, 1)

        # 3. 내부 이미지 실측 파싱
        total_images = 0
        image_samples = []

        for page_num, page in enumerate(reader.pages, start=1):
            for img_name, img_obj in page.images.items():
                total_images += 1
                try:
                    img_data = img_obj.data
                    img = Image.open(io.BytesIO(img_data))
                    w_px, h_px = img.size

                    if len(image_samples) < 5:
                        image_samples.append({
                            "page": page_num,
                            "name": img_name,
                            "width_px": w_px,
                            "height_px": h_px,
                            "format": img.format
                        })
                except Exception:
                    pass

        # AI 종합 검수 진단 생성
        quality_status = "Pass" if total_images > 0 and image_samples[0]["width_px"] >= 1500 else "Warning"

        return {
            "status": "success",
            "filename": file.filename,
            "real_data": {
                "total_pages": total_pages,
                "dimension_mm": {
                    "width": width_mm,
                    "height": height_mm,
                    "raw_pt": f"{width_pt:.0f}pt x {height_pt:.0f}pt"
                },
                "images_summary": {
                    "total_count": total_images,
                    "samples": image_samples,
                    "quality_check": quality_status
                }
            },
            "ai_report_text": f"✓ 실측 분석 완료: {total_pages}페이지 | 규격: {width_mm}mm x {height_mm}mm | 이미지 {total_images}개 감지"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 파싱 중 오류 발생: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
