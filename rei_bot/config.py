"""
Конфигурация бота с валидацией
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Admin IDs - с валидацией
def parse_admin_ids():
    """Парсинг ADMIN_IDS с валидацией"""
    admin_ids_raw = os.getenv("ADMIN_IDS", "").strip()
    if not admin_ids_raw:
        return []
    
    admin_ids = []
    for id_str in admin_ids_raw.split(","):
        id_str = id_str.strip()
        if not id_str:
            continue
        try:
            admin_id = int(id_str)
            if admin_id <= 0:
                print(f"⚠️ WARNING: Invalid ADMIN_ID '{id_str}' (must be positive integer), skipping", file=sys.stderr)
                continue
            admin_ids.append(admin_id)
        except ValueError:
            print(f"⚠️ WARNING: Invalid ADMIN_ID '{id_str}' (not an integer), skipping", file=sys.stderr)
    
    return admin_ids

ADMIN_IDS = parse_admin_ids()

# Feature Flags
ENABLE_IMAGES = int(os.getenv("ENABLE_IMAGES", "1"))
ENABLE_VIDEOS = int(os.getenv("ENABLE_VIDEOS", "1"))
ENABLE_PAYMENTS = int(os.getenv("ENABLE_PAYMENTS", "1"))
ENABLE_WEBHOOKS = int(os.getenv("ENABLE_WEBHOOKS", "0"))  # По умолчанию выключено для polling mode

# API Keys
NANO_BANANA_API_KEY = os.getenv("NANO_BANANA_API_KEY")
KLING_API_KEY = os.getenv("KLING_API_KEY")

# Pricing (in rubles)
IMAGE_GENERATION_PRICE = int(os.getenv("IMAGE_GENERATION_PRICE", "50"))
IMAGE_EDIT_PRICE = int(os.getenv("IMAGE_EDIT_PRICE", "50"))
VIDEO_5SEC_PRICE = int(os.getenv("VIDEO_5SEC_PRICE", "100"))
# 10 секунд всегда = x2 от 5 секунд (по ТЗ). Можно переопределить множитель.
VIDEO_10SEC_MULTIPLIER = int(os.getenv("VIDEO_10SEC_MULTIPLIER", "2"))
VIDEO_10SEC_PRICE = VIDEO_5SEC_PRICE * VIDEO_10SEC_MULTIPLIER

# Kling Models
KLING_MODELS_RAW = os.getenv("KLING_MODELS", "kling-3.0:Kling 3.0,kling-2.6:Kling 2.6,kling-1.5:Kling 1.5")
KLING_MODELS = {}
for model in KLING_MODELS_RAW.split(","):
    if ":" in model:
        model_id, display_name = model.split(":", 1)
        KLING_MODELS[model_id.strip()] = display_name.strip()

# YooKassa Payment Settings
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")
YOOKASSA_RETURN_URL = os.getenv("YOOKASSA_RETURN_URL", "https://t.me/your_bot")

# NanoBanana API Configuration
NANO_BANANA_BASE_URL = os.getenv("NANO_BANANA_BASE_URL", "https://api.nanobanana.ai/v1")
NANO_BANANA_ENDPOINT_GENERATE = os.getenv("NANO_BANANA_ENDPOINT_GENERATE", "/images/generate")
NANO_BANANA_ENDPOINT_EDIT = os.getenv("NANO_BANANA_ENDPOINT_EDIT", "/images/edit")
NANO_BANANA_TIMEOUT = int(os.getenv("NANO_BANANA_TIMEOUT", "300"))

# Kling API Configuration
KLING_BASE_URL = os.getenv("KLING_BASE_URL", "https://api.kling.ai/v1")
KLING_ENDPOINT_T2V = os.getenv("KLING_ENDPOINT_T2V", "/videos/text-to-video")
KLING_ENDPOINT_I2V = os.getenv("KLING_ENDPOINT_I2V", "/videos/image-to-video")
KLING_ENDPOINT_V2V = os.getenv("KLING_ENDPOINT_V2V", "/videos/video-to-video")
KLING_ENDPOINT_STATUS = os.getenv("KLING_ENDPOINT_STATUS", "/videos/status")
KLING_TIMEOUT = int(os.getenv("KLING_TIMEOUT", "300"))
KLING_POLL_INTERVAL = int(os.getenv("KLING_POLL_INTERVAL", "5"))  # seconds
KLING_MAX_POLL_ATTEMPTS = int(os.getenv("KLING_MAX_POLL_ATTEMPTS", "60"))  # 5 min total

# File Upload Configuration - с валидацией
FILE_UPLOAD_METHOD = os.getenv("FILE_UPLOAD_METHOD", "multipart").lower()
S3_BUCKET = os.getenv("S3_BUCKET")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_PRESIGNED_URL_EXPIRY = int(os.getenv("S3_PRESIGNED_URL_EXPIRY", "3600"))  # 1 hour

# Retry Configuration
API_RETRY_ATTEMPTS = int(os.getenv("API_RETRY_ATTEMPTS", "3"))
API_RETRY_BASE_DELAY = float(os.getenv("API_RETRY_BASE_DELAY", "1.0"))  # seconds
API_RETRY_MAX_DELAY = float(os.getenv("API_RETRY_MAX_DELAY", "10.0"))  # seconds

# Redis Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

# Database
DATABASE_PATH = os.getenv("DATABASE_PATH", "./bot.db")


def validate_config():
    """
    Валидация конфигурации при запуске бота.
    Выбрасывает исключение если критичные параметры отсутствуют или некорректны.
    """
    errors = []
    
    # Обязательные параметры
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN is required")
    
    # Условная проверка API ключей по флагам
    if ENABLE_IMAGES and not NANO_BANANA_API_KEY:
        errors.append("NANO_BANANA_API_KEY is required when ENABLE_IMAGES=1")
    
    if ENABLE_VIDEOS and not KLING_API_KEY:
        errors.append("KLING_API_KEY is required when ENABLE_VIDEOS=1")
    
    # Валидация FILE_UPLOAD_METHOD
    if FILE_UPLOAD_METHOD not in ("multipart", "s3"):
        errors.append(f"FILE_UPLOAD_METHOD must be 'multipart' or 's3', got '{FILE_UPLOAD_METHOD}'")
    
    # Если используется S3, проверяем наличие S3 credentials
    if FILE_UPLOAD_METHOD == "s3":
        if not S3_BUCKET:
            errors.append("S3_BUCKET is required when FILE_UPLOAD_METHOD='s3'")
        if not S3_ACCESS_KEY:
            errors.append("S3_ACCESS_KEY is required when FILE_UPLOAD_METHOD='s3'")
        if not S3_SECRET_KEY:
            errors.append("S3_SECRET_KEY is required when FILE_UPLOAD_METHOD='s3'")
    
    # Валидация YooKassa (только если платежи включены)
    if ENABLE_PAYMENTS:
        if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
            errors.append("YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY are required when ENABLE_PAYMENTS=1")
    elif YOOKASSA_SHOP_ID or YOOKASSA_SECRET_KEY:
        # Предупреждение, если креды есть, но платежи выключены
        print("⚠️ WARNING: YooKassa credentials are set but ENABLE_PAYMENTS=0", file=sys.stderr)
    
    # Валидация ADMIN_IDS (предупреждение, не ошибка)
    if not ADMIN_IDS:
        print("⚠️ WARNING: No ADMIN_IDS configured. Admin panel will not be accessible.", file=sys.stderr)
    
    # Если есть ошибки - выбросить исключение
    if errors:
        error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {err}" for err in errors)
        raise ValueError(error_msg)
    
    print("✅ Configuration validated successfully", file=sys.stderr)


# Автоматическая валидация при импорте (можно отключить для тестов)
if os.getenv("SKIP_CONFIG_VALIDATION") != "1":
    validate_config()
