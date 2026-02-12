"""
Утилиты для работы с ценами
Централизованное получение цен с fallback на config
"""
import logging
from typing import Optional
import config


logger = logging.getLogger(__name__)


async def get_price(
    db,
    provider: str,
    action: Optional[str] = None,
    model: Optional[str] = None
) -> float:
    """
    Получить цену из БД с fallback на config
    
    Args:
        db: Database instance
        provider: Провайдер (nano_banana, kling)
        action: Действие (generation, edit, text2video, image2video)
        model: Модель (для kling: kling-v1, kling-v1-5)
    
    Returns:
        Цена в рублях
    """
    # Попытаться получить из БД
    db_price = await db.get_price(provider=provider, action=action, model=model)
    
    if db_price is not None:
        logger.debug(f"Price from DB: provider={provider}, action={action}, model={model}, price={db_price}")
        return db_price
    
    # Fallback на config
    fallback_price = _get_fallback_price(provider, action, model)
    logger.debug(f"Price from config (fallback): provider={provider}, action={action}, model={model}, price={fallback_price}")
    
    return fallback_price


def _get_fallback_price(provider: str, action: Optional[str], model: Optional[str]) -> float:
    """
    Получить цену из config (fallback)
    
    Маппинг:
    - nano_banana + generation -> IMAGE_GENERATION_PRICE
    - nano_banana + edit -> IMAGE_EDIT_PRICE
    - kling + 5sec -> VIDEO_5SEC_PRICE
    - kling + 10sec -> VIDEO_10SEC_PRICE
    """
    if provider == "nano_banana":
        if action == "generation":
            return config.IMAGE_GENERATION_PRICE
        elif action == "edit":
            return config.IMAGE_EDIT_PRICE
        else:
            # Дефолт для nano_banana
            return config.IMAGE_EDIT_PRICE
    
    elif provider == "kling":
        # Для Kling используем action как длительность
        if action == "5sec":
            return config.VIDEO_5SEC_PRICE
        elif action == "10sec":
            return config.VIDEO_10SEC_PRICE
        else:
            # Дефолт для kling
            return config.VIDEO_5SEC_PRICE
    
    else:
        logger.warning(f"Unknown provider: {provider}, returning 0")
        return 0.0


# Константы для action (для единообразия)
class PricingAction:
    """Константы для действий в pricing"""
    # NanoBanana
    IMAGE_GENERATION = "generation"
    IMAGE_EDIT = "edit"
    
    # Kling
    VIDEO_5SEC = "5sec"
    VIDEO_10SEC = "10sec"
