# Speech Service API

Service REST API cho chuyển đổi Speech-to-Text và Text-to-Speech sử dụng Google Cloud APIs.

## Yêu cầu hệ thống

- Python 3.8+
- Google Cloud Platform account với Speech-to-Text và Text-to-Speech APIs được kích hoạt
- Google Cloud credentials (service account key)

## Cài đặt

1. Clone repository:
```bash
git clone <repository-url>
cd <repository-directory>
```

2. Tạo và kích hoạt môi trường ảo:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

3. Cài đặt dependencies:
```bash
pip install -r requirements.txt
```

4. Thiết lập Google Cloud credentials và cấu hình môi trường:

a) Tạo thư mục credentials:
```bash
mkdir credentials
```

b) Tạo file `.env` trong thư mục gốc của dự án:
```env
# Google Cloud Configuration
GOOGLE_APPLICATION_CREDENTIALS=./credentials/google-credentials.json

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000

# Speech-to-Text Configuration
DEFAULT_LANGUAGE_CODE=vi-VN
DEFAULT_SAMPLE_RATE=16000

# Text-to-Speech Configuration
DEFAULT_VOICE_NAME=vi-VN-Standard-A
DEFAULT_AUDIO_ENCODING=MP3
```

c) Tải file credentials từ Google Cloud Console:
- Truy cập Google Cloud Console
- Tạo service account mới hoặc sử dụng service account hiện có
- Tạo key mới (JSON format)
- Tải file JSON và đặt vào thư mục `credentials` với tên `google-credentials.json`

Cấu trúc thư mục cuối cùng sẽ như sau:
```
your-project/
├── credentials/
│   └── google-credentials.json    # File credentials từ Google Cloud
├── .env                          # File cấu hình môi trường
├── speech_service.py
├── requirements.txt
└── README.md
```

## Chạy service

```bash
python speech_service.py
```

Service sẽ chạy tại `http://localhost:8000`

## Sử dụng API

### 1. Speech-to-Text

**Endpoint:** `POST /speech-to-text/`

**Input:**
- File audio (multipart/form-data)
- Hỗ trợ định dạng: .wav, .mp3, .flac

**Ví dụ sử dụng curl:**
```bash
curl -X POST "http://localhost:8000/speech-to-text/" \
     -H "accept: application/json" \
     -H "Content-Type: multipart/form-data" \
     -F "audio_file=@path/to/your/audio.wav"
```

**Response:**
```json
{
    "text": "Văn bản được chuyển đổi",
    "confidence": 0.95
}
```

### 2. Text-to-Speech

**Endpoint:** `POST /text-to-speech/`

**Input:**
```json
{
    "text": "Văn bản cần chuyển thành giọng nói",
    "language_code": "vi-VN",
    "voice_name": "vi-VN-Standard-A",
    "audio_encoding": "MP3"
}
```

**Ví dụ sử dụng curl:**
```bash
curl -X POST "http://localhost:8000/text-to-speech/" \
     -H "accept: audio/mpeg" \
     -H "Content-Type: application/json" \
     -d '{"text": "Xin chào thế giới", "language_code": "vi-VN", "voice_name": "vi-VN-Standard-A"}'
```

**Response:**
- File audio MP3

## Lưu ý

1. Đảm bảo file audio đầu vào cho Speech-to-Text có định dạng phù hợp (16kHz, LINEAR16 encoding)
2. Service tự động xóa các file tạm sau khi xử lý
3. Mặc định sử dụng tiếng Việt (vi-VN)
4. Có thể tùy chỉnh voice và encoding cho Text-to-Speech

## Xử lý lỗi

Service trả về các HTTP status code sau:
- 200: Thành công
- 400: Input không hợp lệ
- 500: Lỗi server

Chi tiết lỗi được trả về trong response body. 