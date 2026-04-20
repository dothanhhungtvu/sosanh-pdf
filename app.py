import streamlit as st
import fitz  # PyMuPDF
from pdf2image import convert_from_bytes
import pytesseract
import requests
import re
from PIL import Image
import os
import json

# ==========================================
# CẤU HÌNH HỆ THỐNG
# ==========================================
# Đường dẫn tesseract (chỉ áp dụng thủ công cho Windows nếu không có trong PATH)
if os.name == 'nt':
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Cấu hình trang Streamlit
st.set_page_config(page_title="Hệ thống Soi Chiếu PDF Bằng AI", layout="wide", page_icon="🔍")

# ==========================================
# HÀM XỬ LÝ (BACKEND LOGIC)
# ==========================================
def extract_text_from_pdf(pdf_file, progress_bar, max_pages=50) -> str:
    """
    Trích xuất text từ file PDF. 
    Thử PyMuPDF trước, nếu text quá ngắn (<=50 ký tự), dùng Tesseract OCR.
    Giới hạn tối đa số trang để tránh quá tải theo yêu cầu.
    """
    file_bytes = pdf_file.read()
    
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        raise Exception(f"Không thể đọc file PDF. Lỗi: {e}")
        
    total_text = ""
    num_pages = min(len(doc), max_pages)
    if len(doc) > max_pages:
        st.warning(f"File PDF quá dài ({len(doc)} trang), hệ thống tự động giới hạn phân tích {max_pages} trang đầu tiên.")
    
    for page_num in range(num_pages):
        page = doc.load_page(page_num)
        text = page.get_text()
        
        # Kiểm tra nếu trang có quá ít chữ (có khả năng là ảnh scan)
        if len(text.strip()) <= 50:
            try:
                # Chuyển đổi trang đó thành ảnh (Dùng page_num + 1 vì pdf2image đếm từ 1)
                images = convert_from_bytes(
                    file_bytes, 
                    first_page=page_num + 1, 
                    last_page=page_num + 1,
                    dpi=200
                )
                if images:
                    # Chạy OCR
                    try:
                        text = pytesseract.image_to_string(images[0], lang='vie+eng')
                    except Exception:
                        text = pytesseract.image_to_string(images[0]) # Fallback nếu không có dataset vie
            except Exception as e:
                # Bỏ qua lỗi chuyển đổi nếu gặp vấn đề với poppler
                # Sẽ giữ lại đoạn text gốc nhỏ lẻ (nếu có)
                pass 
                
        total_text += f"\n--- Trang {page_num + 1} ---\n{text}\n"
        
        # Cập nhật thanh tiến trình
        progress_bar.progress((page_num + 1) / num_pages)
        
    return total_text

def call_openrouter_api(api_key, model_id, text_a, text_b):
    """
    Gọi OpenRouter API để phân tích so sánh 2 văn bản.
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    system_prompt = """Bạn là một chuyên gia kiểm toán và pháp chế tài liệu. Nhiệm vụ của bạn là so sánh Bản gốc (A) và Bản sửa đổi (B). Hãy đối chiếu từng câu, từng từ. Đặc biệt chú ý đến các thay đổi về số liệu, điều khoản, định mức và thông số kỹ thuật. 
Trình bày báo cáo kết quả so sánh dưới dạng bảng hoặc danh sách rõ ràng gồm 3 phần:
[1] Các nội dung bị xóa bỏ (Highlight đỏ),
[2] Các nội dung được thêm mới (Highlight xanh),
[3] Các nội dung bị chỉnh sửa (Hiển thị rõ trước/sau). 
Nếu văn bản quá dài, hãy tập trung vào những thay đổi cốt lõi nhất làm thay đổi ý nghĩa tài liệu.
Lưu ý: Để highlight đỏ, bạn có thể dùng thẻ HTML <span style="background-color: #ffdce0; color: #b31d28; padding: 2px 4px; border-radius: 3px;">...</span>; Highlight xanh dùng thẻ <span style="background-color: #dcedc8; color: #2e7d32; padding: 2px 4px; border-radius: 3px;">...</span>. Hãy hiển thị chuyên nghiệp và dễ nhìn nhất trên nền trắng."""

    user_prompt = f"==== BẢN GỐC (A) ====\n{text_a}\n\n==== BẢN SỬA ĐỔI (B) ====\n{text_b}"

    data = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=120)
        
        # Thử lấy json trước để xem có "error" không
        try:
            result = response.json()
            if "error" in result:
                raise Exception(f"API Error: {result['error']['message']}")
        except ValueError:
            result = None
            
        # Ném ra lỗi nếu mã trạng thái không phải 2xx
        response.raise_for_status()
        
        if result:
            return result['choices'][0]['message']['content']
        else:
            raise Exception("Lỗi: Phản hồi từ API trống rỗng hoặc không phải JSON hợp lệ.")
            
    except requests.exceptions.Timeout:
        raise Exception("Thời gian chờ phản hồi quá lâu (Timeout). Có thể văn bản quá dài hoặc API đang quá tải.")
    except requests.exceptions.RequestException as e:
        # Nếu có lỗi http (ví dụ key sai -> 401)
        if hasattr(e, 'response') and e.response is not None:
            if e.response.status_code == 401:
                raise Exception("API Key không hợp lệ. Vui lòng kiểm tra lại.")
            elif e.response.status_code == 402:
                raise Exception("Tài khoản OpenRouter của bạn không đủ số dư để gọi Model này.")
        raise Exception(f"Lỗi khi gửi request đến API: {str(e)}")
    except (KeyError, IndexError) as e:
        raise Exception(f"Lỗi khi phân tích dữ liệu trả về từ API: Dữ liệu không đúng định dạng mong đợi. Lỗi: {str(e)}")

# ==========================================
# GIAO DIỆN NGƯỜI DÙNG (UI)
# ==========================================
def main():
    # CSS Tùy chỉnh làm đẹp UI
    st.markdown("""
        <style>
        .main-header {
            text-align: center;
            color: #2e4a62;
            font-size: 2.2em;
            font-weight: 700;
            margin-bottom: 20px;
        }
        .stButton>button {
            width: 100%;
            height: 50px;
            font-size: 18px;
            font-weight: bold;
            background-color: #4CAF50;
            color: white;
            border-radius: 8px;
            border: none;
            transition: 0.3s;
        }
        .stButton>button:hover {
            background-color: #45a049;
            box-shadow: 0 4px 8px 0 rgba(0,0,0,0.2);
        }
        .stButton>button:disabled {
            background-color: #cccccc;
            color: #666666;
            cursor: not-allowed;
        }
        </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="main-header">Ứng Dụng Soi Chiếu Tự Động PDF (<span style="color:#d9534f">Bản Gốc</span> vs <span style="color:#5cb85c">Bản Sửa Đổi</span>)</div>', unsafe_allow_html=True)
    
    # Khu vực Sidebar
    st.sidebar.title("⚙️ Cấu hình hệ thống")
    api_key = st.sidebar.text_input("🔑 OpenRouter API Key", type="password", help="Nhập API Key cung cấp bởi OpenRouter.")
    
    models = {
        "Gemini 2.0 Flash": "google/gemini-2.0-flash-001",
        "GPT-4o Mini": "openai/gpt-4o-mini",
        "Gemini 2.0 Flash Lite": "google/gemini-2.0-flash-lite-001",
        "Claude 3 Haiku": "anthropic/claude-3-haiku",
    }
    model_name = st.sidebar.selectbox("🧠 Chọn AI Model", list(models.keys()))
    selected_model_id = models[model_name]
    
    st.sidebar.markdown("---")
    st.sidebar.info("💡 Hướng dẫn:\n\n1. Nhập API Key ở thanh bên.\n2. Tải lên 2 file PDF cần so sánh.\n3. Bấm Bắt đầu soi chiếu để AI tự động trích xuất text (hỗ trợ cả ảnh scan bằng OCR) và phân tích lỗi.")

    # Khu vực Main
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("📄 Bản gốc (Bản A)")
        file_a = st.file_uploader("Tải lên PDF Bản gốc", type="pdf", key="pdf_a")
        
    with col_b:
        st.subheader("📄 Bản sửa đổi (Bản B)")
        file_b = st.file_uploader("Tải lên PDF Bản sửa đổi", type="pdf", key="pdf_b")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # Nút bấm bắt đầu (chỉ enabled khi đủ điều kiện)
    can_start = bool(api_key and file_a and file_b)
    if st.button("🚀 Bắt đầu Soi chiếu", disabled=not can_start):
        if not can_start:
            pass  # Nút đã disable nên logic này chỉ thêm an toàn
        else:
            try:
                # Bước 1: Trích xuất xử lý OCR
                col_prog_a, col_prog_b = st.columns(2)
                
                with col_prog_a:
                    st.info("Đang đọc và trích xuất nội dung Bản A...")
                    progress_bar_a = st.progress(0)
                    text_a = extract_text_from_pdf(file_a, progress_bar_a, max_pages=50)
                    st.success(f"Hoàn thành trích xuất Bản A ({len(text_a)} ký tự)")
                    
                with col_prog_b:
                    st.info("Đang đọc và trích xuất nội dung Bản B...")
                    progress_bar_b = st.progress(0)
                    text_b = extract_text_from_pdf(file_b, progress_bar_b, max_pages=50)
                    st.success(f"Hoàn thành trích xuất Bản B ({len(text_b)} ký tự)")

                # Bước 2 & 3: Gọi API OpenRouter
                st.markdown("---")
                st.info("🔄 Bắt đầu gửi dữ liệu lên AI Model để phân tích, vui lòng chờ (có thể mất vài phút)...")
                
                with st.spinner("🤖 Đang tiến hành đối chiếu từng câu chữ..."):
                    report = call_openrouter_api(api_key, selected_model_id, text_a, text_b)
                
                # Hiển thị kết quả
                st.success("✅ So sánh và soi chiếu hoàn tất!")
                st.markdown("### 📊 Báo cáo Kết quả Đối chiếu")
                st.markdown(
                    f"<div style='background-color:#ffffff; padding:20px; border-radius:10px; border:1px solid #ddd; color: #333;'>\n\n{report}\n\n</div>", 
                    unsafe_allow_html=True
                )
                
            except Exception as e:
                st.error(f"❌ Đã có lỗi xảy ra: {e}")

if __name__ == "__main__":
    main()
