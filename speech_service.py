import os
import tempfile
import logging
from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from google.cloud import speech_v1, texttospeech, language_v1
from dotenv import load_dotenv
from langdetect import detect, LangDetectException
from pydub import AudioSegment
import io

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load biến môi trường
load_dotenv()

# Lấy các biến môi trường
GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
API_HOST = os.getenv('API_HOST', 'localhost')
API_PORT = int(os.getenv('API_PORT', '8000'))
DEFAULT_LANGUAGE_CODE = os.getenv('DEFAULT_LANGUAGE_CODE', 'vi-VN')
DEFAULT_SAMPLE_RATE = int(os.getenv('DEFAULT_SAMPLE_RATE', '16000'))
DEFAULT_VOICE_NAME = os.getenv('DEFAULT_VOICE_NAME', 'vi-VN-Standard-A')
DEFAULT_AUDIO_ENCODING = os.getenv('DEFAULT_AUDIO_ENCODING', 'MP3')

# Kiểm tra credentials
if not GOOGLE_APPLICATION_CREDENTIALS or not os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
    raise ValueError(
        "Google Cloud credentials không được tìm thấy. "
        "Vui lòng thiết lập biến môi trường GOOGLE_APPLICATION_CREDENTIALS "
        "và đảm bảo file credentials tồn tại."
    )

app = FastAPI(title="Speech Service API")

# Model cho Text-to-Speech request
class TextToSpeechRequest(BaseModel):
    text: str
    language_code: str = DEFAULT_LANGUAGE_CODE
    voice_name: str = DEFAULT_VOICE_NAME
    audio_encoding: str = DEFAULT_AUDIO_ENCODING

class SpeechToTextRequest(BaseModel):
    language_code: Optional[str] = None
    auto_detect_language: bool = False
    alternative_language_codes: Optional[list[str]] = None

# Khởi tạo clients
speech_client = speech_v1.SpeechClient()
tts_client = texttospeech.TextToSpeechClient()
language_client = language_v1.LanguageServiceClient()

def cleanup_temp_file(file_path: str):
    """Xóa file tạm sau khi sử dụng"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        logger.error(f"Lỗi khi xóa file tạm {file_path}: {str(e)}")

def get_available_voices(language_code: str = None) -> list:
    """
    Lấy danh sách các voice có sẵn cho một ngôn ngữ cụ thể
    """
    try:
        response = tts_client.list_voices(language_code=language_code)
        return [
            {
                "name": voice.name,
                "language_code": voice.language_codes[0],
                "gender": voice.ssml_gender.name,
                "natural_sample_rate_hertz": voice.natural_sample_rate_hertz
            }
            for voice in response.voices
        ]
    except Exception as e:
        logger.error(f"Lỗi khi lấy danh sách voice: {str(e)}")
        return []

def get_default_voice_for_language(language_code: str) -> str:
    """
    Tự động chọn voice mặc định cho một ngôn ngữ
    """
    voices = get_available_voices(language_code)
    if not voices:
        return DEFAULT_VOICE_NAME
    
    # Ưu tiên chọn voice Standard (thay vì Neural hoặc WaveNet)
    standard_voices = [v for v in voices if "Standard" in v["name"]]
    if standard_voices:
        return standard_voices[0]["name"]
    
    # Nếu không có Standard, lấy voice đầu tiên
    return voices[0]["name"]

def detect_language(text: str) -> str:
    """
    Phát hiện ngôn ngữ của văn bản sử dụng langdetect
    """
    try:
        lang = detect(text)
        # Chuyển đổi mã ngôn ngữ 2 ký tự thành mã đầy đủ
        lang_map = {
            'en': 'en-US',
            'vi': 'vi-VN',
            'fr': 'fr-FR',
            'de': 'de-DE',
            'ja': 'ja-JP',
            'ko': 'ko-KR',
            'zh': 'zh-CN',
            'es': 'es-ES',
            'it': 'it-IT',
            'ru': 'ru-RU'
        }
        detected_lang = lang_map.get(lang, DEFAULT_LANGUAGE_CODE)
        logger.info(f"Phát hiện ngôn ngữ: {detected_lang} (từ mã {lang})")
        return detected_lang
    except LangDetectException as e:
        logger.error(f"Lỗi khi phát hiện ngôn ngữ: {str(e)}")
        return DEFAULT_LANGUAGE_CODE

def convert_to_wav(audio_content: bytes, file_ext: str) -> bytes:
    """
    Chuyển đổi audio từ nhiều định dạng sang WAV sử dụng pydub
    """
    try:
        # Tạo file tạm để lưu audio gốc
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            temp_file.write(audio_content)
            temp_file_path = temp_file.name

        try:
            # Đọc audio file
            audio = AudioSegment.from_file(temp_file_path)
            
            # Chuyển đổi sang mono và 16kHz
            audio = audio.set_channels(1)
            audio = audio.set_frame_rate(16000)
            
            # Export sang WAV
            wav_buffer = io.BytesIO()
            audio.export(wav_buffer, format="wav")
            wav_content = wav_buffer.getvalue()
            
            logger.info(f"Đã chuyển đổi {file_ext} sang WAV thành công")
            return wav_content
            
        finally:
            # Xóa file tạm
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
                
    except Exception as e:
        logger.error(f"Lỗi khi chuyển đổi audio: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể chuyển đổi file {file_ext} sang WAV: {str(e)}"
        )

@app.post("/speech-to-text/")
async def speech_to_text(
    audio_file: UploadFile = File(...),
    request: SpeechToTextRequest = None
):
    """
    Chuyển đổi audio thành text sử dụng Google Cloud Speech-to-Text API
    Hỗ trợ phát hiện ngôn ngữ tự động và chỉ định ngôn ngữ cụ thể
    """
    try:
        # Kiểm tra định dạng file
        allowed_extensions = {'.wav', '.mp3', '.flac', '.ogg', '.m4a', '.aac'}
        file_ext = os.path.splitext(audio_file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Định dạng file không được hỗ trợ. Chỉ chấp nhận: {', '.join(allowed_extensions)}"
            )

        # Đọc nội dung file
        content = await audio_file.read()
        
        # Chuyển đổi sang WAV nếu không phải WAV
        if file_ext != '.wav':
            content = convert_to_wav(content, file_ext)
            logger.info("Đã chuyển đổi file sang WAV")

        # Cấu hình recognition
        audio = speech_v1.RecognitionAudio(content=content)
        
        # Cấu hình ngôn ngữ
        config = speech_v1.RecognitionConfig(
            encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            enable_automatic_punctuation=True,
            model="default"
        )

        # Xử lý cấu hình ngôn ngữ
        if request and request.auto_detect_language:
            # Sử dụng phát hiện ngôn ngữ tự động
            config.language_code = "auto"
            if request.alternative_language_codes:
                config.alternative_language_codes = request.alternative_language_codes
        else:
            # Sử dụng ngôn ngữ được chỉ định hoặc mặc định
            config.language_code = request.language_code if request and request.language_code else DEFAULT_LANGUAGE_CODE

        logger.info(f"Cấu hình recognition: {config}")

        # Thực hiện recognition
        response = speech_client.recognize(config=config, audio=audio)
        logger.info(f"Response từ speech to text: {response}")

        # Xử lý kết quả
        if not response.results:
            logger.warning("Không có kết quả nhận dạng")
            return {"text": "", "confidence": 0.0}

        result = response.results[0]
        logger.info(f"Kết quả nhận dạng: {result}")
        
        return {
            "text": result.alternatives[0].transcript,
            "confidence": result.alternatives[0].confidence,
            "language_code": result.language_code if hasattr(result, 'language_code') else config.language_code
        }

    except Exception as e:
        logger.error(f"Lỗi trong speech-to-text: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/text-to-speech/")
async def text_to_speech(request: TextToSpeechRequest):
    """
    Chuyển đổi text thành audio sử dụng Google Cloud Text-to-Speech API
    """
    try:
        # Phát hiện ngôn ngữ nếu không được chỉ định
        if not request.language_code or request.language_code == DEFAULT_LANGUAGE_CODE:
            detected_language = detect_language(request.text)
            request.language_code = detected_language
            logger.info(f"Đã phát hiện ngôn ngữ: {detected_language}")

        # Tự động chọn voice nếu không được chỉ định
        if not request.voice_name or request.voice_name == DEFAULT_VOICE_NAME:
            request.voice_name = get_default_voice_for_language(request.language_code)
            logger.info(f"Đã chọn voice: {request.voice_name}")

        # Cấu hình synthesis input
        synthesis_input = texttospeech.SynthesisInput(text=request.text)

        # Cấu hình voice
        voice = texttospeech.VoiceSelectionParams(
            language_code=request.language_code,
            name=request.voice_name
        )

        # Cấu hình audio
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        )

        # Thực hiện synthesis
        response = tts_client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )

        # Lưu file tạm
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
            temp_file.write(response.audio_content)
            temp_file_path = temp_file.name

        try:
            return FileResponse(
                temp_file_path,
                media_type="audio/mpeg",
                filename="output.mp3",
                background=lambda: cleanup_temp_file(temp_file_path)
            )
        except Exception as e:
            cleanup_temp_file(temp_file_path)
            raise e

    except Exception as e:
        logger.error(f"Lỗi trong text-to-speech: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/available-voices/")
async def list_available_voices(language_code: str = None):
    """
    API endpoint để lấy danh sách các voice có sẵn
    """
    return get_available_voices(language_code)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT) 