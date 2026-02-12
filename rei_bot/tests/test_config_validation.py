"""
Unit-тесты для валидации конфигурации
"""
import os
import sys
import pytest
from unittest.mock import patch


def test_parse_admin_ids_valid():
    """Тест парсинга валидных ADMIN_IDS"""
    with patch.dict(os.environ, {"ADMIN_IDS": "123,456,789"}):
        # Reload config to apply new env
        import importlib
        import config
        importlib.reload(config)
        
        assert config.ADMIN_IDS == [123, 456, 789]


def test_parse_admin_ids_with_spaces():
    """Тест парсинга ADMIN_IDS с пробелами"""
    with patch.dict(os.environ, {"ADMIN_IDS": " 123 , 456 , 789 "}):
        import importlib
        import config
        importlib.reload(config)
        
        assert config.ADMIN_IDS == [123, 456, 789]


def test_parse_admin_ids_empty():
    """Тест парсинга пустого ADMIN_IDS"""
    with patch.dict(os.environ, {"ADMIN_IDS": ""}, clear=True):
        import importlib
        import config
        importlib.reload(config)
        
        assert config.ADMIN_IDS == []


def test_parse_admin_ids_with_invalid():
    """Тест парсинга ADMIN_IDS с невалидными значениями"""
    with patch.dict(os.environ, {"ADMIN_IDS": "123,abc,456,xyz"}):
        import importlib
        import config
        importlib.reload(config)
        
        # Должны быть только валидные ID
        assert config.ADMIN_IDS == [123, 456]


def test_parse_admin_ids_negative():
    """Тест парсинга ADMIN_IDS с отрицательными значениями"""
    with patch.dict(os.environ, {"ADMIN_IDS": "123,-456,789"}):
        import importlib
        import config
        importlib.reload(config)
        
        # Отрицательные ID должны быть пропущены
        assert config.ADMIN_IDS == [123, 789]


def test_validate_config_missing_bot_token():
    """Тест валидации при отсутствии BOT_TOKEN"""
    with patch.dict(os.environ, {
        "SKIP_CONFIG_VALIDATION": "1",
        "BOT_TOKEN": "",
        "NANO_BANANA_API_KEY": "test",
        "KLING_API_KEY": "test"
    }, clear=True):
        import importlib
        import config
        importlib.reload(config)
        
        with pytest.raises(ValueError, match="BOT_TOKEN is required"):
            config.validate_config()


def test_validate_config_missing_nano_banana_key():
    """Тест валидации при отсутствии NANO_BANANA_API_KEY"""
    with patch.dict(os.environ, {
        "SKIP_CONFIG_VALIDATION": "1",
        "BOT_TOKEN": "test",
        "NANO_BANANA_API_KEY": "",
        "KLING_API_KEY": "test"
    }, clear=True):
        import importlib
        import config
        importlib.reload(config)
        
        with pytest.raises(ValueError, match="NANO_BANANA_API_KEY is required"):
            config.validate_config()


def test_validate_config_missing_kling_key():
    """Тест валидации при отсутствии KLING_API_KEY"""
    with patch.dict(os.environ, {
        "SKIP_CONFIG_VALIDATION": "1",
        "BOT_TOKEN": "test",
        "NANO_BANANA_API_KEY": "test",
        "KLING_API_KEY": ""
    }, clear=True):
        import importlib
        import config
        importlib.reload(config)
        
        with pytest.raises(ValueError, match="KLING_API_KEY is required"):
            config.validate_config()


def test_validate_config_invalid_file_upload_method():
    """Тест валидации при невалидном FILE_UPLOAD_METHOD"""
    with patch.dict(os.environ, {
        "SKIP_CONFIG_VALIDATION": "1",
        "BOT_TOKEN": "test",
        "NANO_BANANA_API_KEY": "test",
        "KLING_API_KEY": "test",
        "FILE_UPLOAD_METHOD": "invalid"
    }, clear=True):
        import importlib
        import config
        importlib.reload(config)
        
        with pytest.raises(ValueError, match="FILE_UPLOAD_METHOD must be 'multipart' or 's3'"):
            config.validate_config()


def test_validate_config_s3_missing_bucket():
    """Тест валидации S3 при отсутствии S3_BUCKET"""
    with patch.dict(os.environ, {
        "SKIP_CONFIG_VALIDATION": "1",
        "BOT_TOKEN": "test",
        "NANO_BANANA_API_KEY": "test",
        "KLING_API_KEY": "test",
        "FILE_UPLOAD_METHOD": "s3",
        "S3_BUCKET": "",
        "S3_ACCESS_KEY": "test",
        "S3_SECRET_KEY": "test"
    }, clear=True):
        import importlib
        import config
        importlib.reload(config)
        
        with pytest.raises(ValueError, match="S3_BUCKET is required"):
            config.validate_config()


def test_validate_config_s3_missing_credentials():
    """Тест валидации S3 при отсутствии credentials"""
    with patch.dict(os.environ, {
        "SKIP_CONFIG_VALIDATION": "1",
        "BOT_TOKEN": "test",
        "NANO_BANANA_API_KEY": "test",
        "KLING_API_KEY": "test",
        "FILE_UPLOAD_METHOD": "s3",
        "S3_BUCKET": "test-bucket",
        "S3_ACCESS_KEY": "",
        "S3_SECRET_KEY": ""
    }, clear=True):
        import importlib
        import config
        importlib.reload(config)
        
        with pytest.raises(ValueError, match="S3_ACCESS_KEY is required"):
            config.validate_config()


def test_validate_config_yookassa_incomplete():
    """Тест валидации YooKassa при неполных параметрах"""
    with patch.dict(os.environ, {
        "SKIP_CONFIG_VALIDATION": "1",
        "BOT_TOKEN": "test",
        "NANO_BANANA_API_KEY": "test",
        "KLING_API_KEY": "test",
        "YOOKASSA_SHOP_ID": "test",
        "YOOKASSA_SECRET_KEY": ""
    }, clear=True):
        import importlib
        import config
        importlib.reload(config)
        
        with pytest.raises(ValueError, match="YOOKASSA_SECRET_KEY is required"):
            config.validate_config()


def test_validate_config_success():
    """Тест успешной валидации конфигурации"""
    with patch.dict(os.environ, {
        "SKIP_CONFIG_VALIDATION": "1",
        "BOT_TOKEN": "test_token",
        "NANO_BANANA_API_KEY": "test_nano_key",
        "KLING_API_KEY": "test_kling_key",
        "FILE_UPLOAD_METHOD": "multipart"
    }, clear=True):
        import importlib
        import config
        importlib.reload(config)
        
        # Не должно быть исключений
        config.validate_config()


def test_file_upload_method_case_insensitive():
    """Тест что FILE_UPLOAD_METHOD case-insensitive"""
    with patch.dict(os.environ, {
        "SKIP_CONFIG_VALIDATION": "1",
        "FILE_UPLOAD_METHOD": "MULTIPART"
    }, clear=True):
        import importlib
        import config
        importlib.reload(config)
        
        assert config.FILE_UPLOAD_METHOD == "multipart"
    
    with patch.dict(os.environ, {
        "SKIP_CONFIG_VALIDATION": "1",
        "FILE_UPLOAD_METHOD": "S3"
    }, clear=True):
        importlib.reload(config)
        
        assert config.FILE_UPLOAD_METHOD == "s3"
