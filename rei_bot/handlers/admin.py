"""
Обработчики для администраторов (расширенный контур F-306)
"""
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
import logging

from database.models import db
import config


router = Router()
logger = logging.getLogger(__name__)


# ==================== ADMIN DECORATOR ====================

def admin_required(func):
    """
    Декоратор для проверки админ-доступа
    
    Использование:
        @admin_required
        async def my_admin_handler(message: Message):
            ...
    """
    async def wrapper(event, *args, **kwargs):
        # Поддержка Message и CallbackQuery
        user_id = event.from_user.id if hasattr(event, 'from_user') else None
        
        if not user_id or not is_admin(user_id):
            logger.warning(f"Unauthorized admin access attempt from user {user_id}")
            
            # Ответить в зависимости от типа события
            if hasattr(event, 'answer'):  # CallbackQuery
                await event.answer("⚠️ Доступ запрещен", show_alert=True)
            else:  # Message
                await event.answer("⚠️ Эта команда доступна только администраторам")
            return
        
        return await func(event, *args, **kwargs)
    
    return wrapper


# ==================== AUDIT LOG ====================

async def log_admin_action(admin_id: int, action: str, details: str):
    """
    Логировать действие администратора
    
    Args:
        admin_id: ID администратора
        action: Действие (add_balance, refund, cancel_job, etc.)
        details: Детали действия
    """
    logger.info(f"🛠 ADMIN ACTION: admin={admin_id}, action={action}, details={details}")
    
    # TODO: Сохранять в отдельную таблицу audit_log для постоянного хранения


# ==================== HELPERS ====================

def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором"""
    return user_id in config.ADMIN_IDS


# ==================== COMMANDS ====================

@router.message(Command("admin"))
async def admin_menu(message: Message):
    """Меню администратора"""
    if not is_admin(message.from_user.id):
        return
    
    text = (
        "🛠 <b>Админ-панель v3.1</b>\n\n"
        "<b>Баланс:</b>\n"
        "/add &lt;tg_id&gt; &lt;₽&gt; — начислить баланс\n"
        "/sub &lt;tg_id&gt; &lt;₽&gt; — списать баланс\n"
        "/admin_refund &lt;tg_id&gt; &lt;₽&gt; &lt;причина&gt; — возврат средств\n"
        "/admin_adjust &lt;tg_id&gt; &lt;±₽&gt; &lt;причина&gt; — корректировка баланса\n\n"
        "<b>Задачи:</b>\n"
        "/admin_cancel_job &lt;job_id&gt; &lt;причина&gt; — отменить задачу\n"
        "/admin_jobs &lt;tg_id&gt; — список задач пользователя\n\n"
        "<b>Пользователи:</b>\n"
        "/ban &lt;tg_id&gt; — заблокировать\n"
        "/unban &lt;tg_id&gt; — разблокировать\n"
        "/admin_user &lt;tg_id&gt; — информация о пользователе\n\n"
        "<b>Цены:</b>\n"
        "/prices — показать все цены\n"
        "/price_nanobanana &lt;₽&gt; [action] — установить цену NanoBanana\n"
        "/price_kling [model] &lt;₽&gt; — установить цену Kling\n\n"
        "Пример:\n"
        "/add 123456789 1000\n"
        "/price_nanobanana 60 generation"
    )
    
    await message.answer(text, parse_mode="HTML")


@router.message(Command("add"))
async def add_balance_admin(message: Message):
    """Начислить баланс пользователю"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer(
                "⚠️ Неверный формат\n\n"
                "Использование: /add &lt;tg_id&gt; &lt;₽&gt;\n"
                "Пример: /add 123456789 1000",
                parse_mode="HTML"
            )
            return
        
        tg_id = int(parts[1])
        amount = float(parts[2])
        
        if amount <= 0:
            await message.answer("⚠️ Сумма должна быть положительной")
            return
        
        # Создать пользователя если не существует
        await db.get_or_create_user(tg_id)
        
        # Начислить через ledger
        await db.add_ledger_entry(
            user_id=tg_id,
            entry_type='credit',
            amount=amount,
            ref_type='admin_add',
            ref_id=f"admin_{message.from_user.id}_{message.message_id}",
            description=f"Начислено администратором {message.from_user.id}"
        )
        
        balance = await db.get_balance(tg_id)
        
        await log_admin_action(
            message.from_user.id,
            "add_balance",
            f"user={tg_id}, amount={amount}, new_balance={balance}"
        )
        
        await message.answer(
            f"✅ Баланс начислен\n\n"
            f"Пользователь: <code>{tg_id}</code>\n"
            f"Начислено: {amount} ₽\n"
            f"Новый баланс: {balance} ₽",
            parse_mode="HTML"
        )
    
    except ValueError:
        await message.answer("⚠️ Неверный формат: tg_id и сумма должны быть числами")
    except Exception as e:
        logger.error(f"Error in add_balance_admin: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)}")


@router.message(Command("sub"))
async def subtract_balance_admin(message: Message):
    """Списать баланс у пользователя"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer(
                "⚠️ Неверный формат\n\n"
                "Использование: /sub &lt;tg_id&gt; &lt;₽&gt;\n"
                "Пример: /sub 123456789 500",
                parse_mode="HTML"
            )
            return
        
        tg_id = int(parts[1])
        amount = float(parts[2])
        
        if amount <= 0:
            await message.answer("⚠️ Сумма должна быть положительной")
            return
        
        # Списать через ledger
        await db.add_ledger_entry(
            user_id=tg_id,
            entry_type='debit',
            amount=-amount,
            ref_type='admin_sub',
            ref_id=f"admin_{message.from_user.id}_{message.message_id}",
            description=f"Списано администратором {message.from_user.id}"
        )
        
        balance = await db.get_balance(tg_id)
        
        await log_admin_action(
            message.from_user.id,
            "subtract_balance",
            f"user={tg_id}, amount={amount}, new_balance={balance}"
        )
        
        await message.answer(
            f"✅ Баланс списан\n\n"
            f"Пользователь: <code>{tg_id}</code>\n"
            f"Списано: {amount} ₽\n"
            f"Новый баланс: {balance} ₽",
            parse_mode="HTML"
        )
    
    except ValueError:
        await message.answer("⚠️ Неверный формат: tg_id и сумма должны быть числами")
    except Exception as e:
        logger.error(f"Error in subtract_balance_admin: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)}")


@router.message(Command("admin_refund"))
async def admin_refund(message: Message):
    """Возврат средств пользователю"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split(maxsplit=3)
        if len(parts) < 4:
            await message.answer(
                "⚠️ Неверный формат\n\n"
                "Использование: /admin_refund &lt;tg_id&gt; &lt;₽&gt; &lt;причина&gt;\n"
                "Пример: /admin_refund 123456789 50 Ошибка генерации",
                parse_mode="HTML"
            )
            return
        
        tg_id = int(parts[1])
        amount = float(parts[2])
        reason = parts[3]
        
        if amount <= 0:
            await message.answer("⚠️ Сумма должна быть положительной")
            return
        
        # Возврат через ledger
        await db.add_ledger_entry(
            user_id=tg_id,
            entry_type='refund',
            amount=amount,
            ref_type='admin_refund',
            ref_id=f"admin_{message.from_user.id}_{message.message_id}",
            description=f"Возврат: {reason}"
        )
        
        balance = await db.get_balance(tg_id)
        
        await log_admin_action(
            message.from_user.id,
            "refund",
            f"user={tg_id}, amount={amount}, reason={reason}, new_balance={balance}"
        )
        
        await message.answer(
            f"✅ Возврат выполнен\n\n"
            f"Пользователь: <code>{tg_id}</code>\n"
            f"Сумма: {amount} ₽\n"
            f"Причина: {reason}\n"
            f"Новый баланс: {balance} ₽",
            parse_mode="HTML"
        )
    
    except ValueError:
        await message.answer("⚠️ Неверный формат: tg_id и сумма должны быть числами")
    except Exception as e:
        logger.error(f"Error in admin_refund: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)}")


@router.message(Command("admin_adjust"))
async def admin_adjust(message: Message):
    """Корректировка баланса (может быть ± )"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split(maxsplit=3)
        if len(parts) < 4:
            await message.answer(
                "⚠️ Неверный формат\n\n"
                "Использование: /admin_adjust &lt;tg_id&gt; &lt;±₽&gt; &lt;причина&gt;\n"
                "Пример: /admin_adjust 123456789 -100 Корректировка ошибки",
                parse_mode="HTML"
            )
            return
        
        tg_id = int(parts[1])
        amount = float(parts[2])
        reason = parts[3]
        
        if amount == 0:
            await message.answer("⚠️ Сумма не может быть нулевой")
            return
        
        # Определить тип операции
        entry_type = 'credit' if amount > 0 else 'debit'
        
        # Корректировка через ledger
        await db.add_ledger_entry(
            user_id=tg_id,
            entry_type=entry_type,
            amount=amount,
            ref_type='admin_adjust',
            ref_id=f"admin_{message.from_user.id}_{message.message_id}",
            description=f"Корректировка: {reason}"
        )
        
        balance = await db.get_balance(tg_id)
        
        await log_admin_action(
            message.from_user.id,
            "adjust_balance",
            f"user={tg_id}, amount={amount}, reason={reason}, new_balance={balance}"
        )
        
        await message.answer(
            f"✅ Корректировка выполнена\n\n"
            f"Пользователь: <code>{tg_id}</code>\n"
            f"Изменение: {amount:+.2f} ₽\n"
            f"Причина: {reason}\n"
            f"Новый баланс: {balance} ₽",
            parse_mode="HTML"
        )
    
    except ValueError:
        await message.answer("⚠️ Неверный формат: tg_id и сумма должны быть числами")
    except Exception as e:
        logger.error(f"Error in admin_adjust: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)}")


@router.message(Command("admin_cancel_job"))
async def admin_cancel_job(message: Message):
    """Отменить задачу пользователя"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            await message.answer(
                "⚠️ Неверный формат\n\n"
                "Использование: /admin_cancel_job &lt;job_id&gt; &lt;причина&gt;\n"
                "Пример: /admin_cancel_job 123 Нарушение правил",
                parse_mode="HTML"
            )
            return
        
        job_id = int(parts[1])
        reason = parts[2]
        
        # Получить job
        job = await db.get_job(job_id)
        if not job:
            await message.answer(f"⚠️ Задача {job_id} не найдена")
            return
        
        # Отменить job
        success = await db.cancel_job(
            job_id=job_id,
            cancelled_by=message.from_user.id,
            cancel_reason=f"Admin: {reason}"
        )
        
        if not success:
            await message.answer(f"⚠️ Не удалось отменить задачу {job_id}")
            return
        
        # Возврат средств если job был оплачен
        if job.get('cost_actual') and job['cost_actual'] > 0:
            await db.add_ledger_entry(
                user_id=job['user_id'],
                entry_type='refund',
                amount=job['cost_actual'],
                ref_type='job_cancelled',
                ref_id=f"job_{job_id}",
                description=f"Возврат за отмененную задачу: {reason}"
            )
        
        await log_admin_action(
            message.from_user.id,
            "cancel_job",
            f"job_id={job_id}, user={job['user_id']}, reason={reason}"
        )
        
        await message.answer(
            f"✅ Задача отменена\n\n"
            f"Job ID: {job_id}\n"
            f"Пользователь: <code>{job['user_id']}</code>\n"
            f"Причина: {reason}\n"
            f"Возврат: {job.get('cost_actual', 0)} ₽",
            parse_mode="HTML"
        )
    
    except ValueError:
        await message.answer("⚠️ Неверный формат: job_id должен быть числом")
    except Exception as e:
        logger.error(f"Error in admin_cancel_job: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)}")


@router.message(Command("admin_user"))
async def admin_user_info(message: Message):
    """Информация о пользователе"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer(
                "⚠️ Неверный формат\n\n"
                "Использование: /admin_user &lt;tg_id&gt;\n"
                "Пример: /admin_user 123456789",
                parse_mode="HTML"
            )
            return
        
        tg_id = int(parts[1])
        
        # Получить информацию
        user = await db.get_user(tg_id)
        if not user:
            await message.answer(f"⚠️ Пользователь {tg_id} не найден")
            return
        
        balance = await db.get_balance(tg_id)
        jobs = await db.get_user_jobs(tg_id, limit=5)
        
        text = (
            f"👤 <b>Информация о пользователе</b>\n\n"
            f"ID: <code>{tg_id}</code>\n"
            f"Username: @{user.get('username', 'N/A')}\n"
            f"Имя: {user.get('first_name', 'N/A')}\n"
            f"Баланс: {balance} ₽\n"
            f"Заблокирован: {'Да' if user.get('is_banned') else 'Нет'}\n"
            f"Зарегистрирован: {user.get('created_at', 'N/A')}\n\n"
            f"<b>Последние задачи:</b>\n"
        )
        
        for job in jobs[:5]:
            text += f"• Job #{job['id']} — {job['type']} — {job['status']}\n"
        
        await message.answer(text, parse_mode="HTML")
    
    except ValueError:
        await message.answer("⚠️ Неверный формат: tg_id должен быть числом")
    except Exception as e:
        logger.error(f"Error in admin_user_info: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)}")


@router.message(Command("admin_jobs"))
async def admin_user_jobs(message: Message):
    """Список задач пользователя"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer(
                "⚠️ Неверный формат\n\n"
                "Использование: /admin_jobs &lt;tg_id&gt;\n"
                "Пример: /admin_jobs 123456789",
                parse_mode="HTML"
            )
            return
        
        tg_id = int(parts[1])
        jobs = await db.get_user_jobs(tg_id, limit=20)
        
        if not jobs:
            await message.answer(f"⚠️ У пользователя {tg_id} нет задач")
            return
        
        text = f"📋 <b>Задачи пользователя {tg_id}</b>\n\n"
        
        for job in jobs:
            text += (
                f"Job #{job['id']}\n"
                f"Тип: {job['type']}\n"
                f"Статус: {job['status']}\n"
                f"Стоимость: {job.get('cost_actual', 0)} ₽\n"
                f"Создан: {job['created_at']}\n\n"
            )
        
        await message.answer(text, parse_mode="HTML")
    
    except ValueError:
        await message.answer("⚠️ Неверный формат: tg_id должен быть числом")
    except Exception as e:
        logger.error(f"Error in admin_user_jobs: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)}")


@router.message(Command("ban"))
async def ban_user(message: Message):
    """Заблокировать пользователя"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer(
                "⚠️ Неверный формат\n\n"
                "Использование: /ban &lt;tg_id&gt;\n"
                "Пример: /ban 123456789",
                parse_mode="HTML"
            )
            return
        
        tg_id = int(parts[1])
        
        await db.ban_user(tg_id)
        
        await log_admin_action(
            message.from_user.id,
            "ban_user",
            f"user={tg_id}"
        )
        
        await message.answer(
            f"✅ Пользователь заблокирован\n\n"
            f"ID: <code>{tg_id}</code>",
            parse_mode="HTML"
        )
    
    except ValueError:
        await message.answer("⚠️ Неверный формат: tg_id должен быть числом")
    except Exception as e:
        logger.error(f"Error in ban_user: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)}")


@router.message(Command("unban"))
async def unban_user(message: Message):
    """Разблокировать пользователя"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer(
                "⚠️ Неверный формат\n\n"
                "Использование: /unban &lt;tg_id&gt;\n"
                "Пример: /unban 123456789",
                parse_mode="HTML"
            )
            return
        
        tg_id = int(parts[1])
        
        await db.unban_user(tg_id)
        
        await log_admin_action(
            message.from_user.id,
            "unban_user",
            f"user={tg_id}"
        )
        
        await message.answer(
            f"✅ Пользователь разблокирован\n\n"
            f"ID: <code>{tg_id}</code>",
            parse_mode="HTML"
        )
    
    except ValueError:
        await message.answer("⚠️ Неверный формат: tg_id должен быть числом")
    except Exception as e:
        logger.error(f"Error in unban_user: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)}")


# ==================== PRICING MANAGEMENT ====================

@router.message(Command("price_nanobanana"))
async def set_nanobanana_price(message: Message):
    """Установить цену для NanoBanana"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) not in (2, 3):
            await message.answer(
                "⚠️ Неверный формат\n\n"
                "Использование:\n"
                "/price_nanobanana <₽> — общая цена\n"
                "/price_nanobanana <₽> edit — для редактирования\n"
                "/price_nanobanana <₽> generation — для генерации\n\n"
                "Пример: /price_nanobanana 50",
                parse_mode="HTML"
            )
            return
        
        price = float(parts[1])
        action = parts[2] if len(parts) == 3 else None
        
        if price < 0:
            await message.answer("⚠️ Цена не может быть отрицательной")
            return
        
        # Установить цену
        success = await db.set_price(
            provider="nano_banana",
            price_rub=price,
            action=action,
            updated_by=message.from_user.id
        )
        
        if success:
            action_text = f" ({action})" if action else ""
            await log_admin_action(
                message.from_user.id,
                "set_price",
                f"provider=nano_banana, action={action}, price={price}"
            )
            
            await message.answer(
                f"✅ Цена установлена\n\n"
                f"Провайдер: NanoBanana{action_text}\n"
                f"Цена: {price} ₽",
                parse_mode="HTML"
            )
        else:
            await message.answer("⚠️ Ошибка установки цены")
    
    except ValueError:
        await message.answer("⚠️ Неверный формат: цена должна быть числом")
    except Exception as e:
        logger.error(f"Error in set_nanobanana_price: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)}")


@router.message(Command("price_kling"))
async def set_kling_price(message: Message):
    """Установить цену для Kling (по моделям)"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) not in (2, 3):
            await message.answer(
                "⚠️ Неверный формат\n\n"
                "Использование:\n"
                "/price_kling <₽> — общая цена для всех моделей\n"
                "/price_kling <model_id> <₽> — для конкретной модели\n\n"
                "Доступные модели:\n" + 
                "\n".join(f"• {model_id}" for model_id in config.KLING_MODELS.keys()) +
                "\n\nПример: /price_kling kling-3.0 150",
                parse_mode="HTML"
            )
            return
        
        if len(parts) == 2:
            # Общая цена
            model = None
            price = float(parts[1])
        else:
            # Цена для модели
            model = parts[1]
            price = float(parts[2])
            
            if model not in config.KLING_MODELS:
                await message.answer(
                    f"⚠️ Неизвестная модель: {model}\n\n"
                    f"Доступные модели:\n" +
                    "\n".join(f"• {model_id}" for model_id in config.KLING_MODELS.keys())
                )
                return
        
        if price < 0:
            await message.answer("⚠️ Цена не может быть отрицательной")
            return
        
        # Установить цену
        success = await db.set_price(
            provider="kling",
            price_rub=price,
            model=model,
            updated_by=message.from_user.id
        )
        
        if success:
            model_text = f" ({model})" if model else " (все модели)"
            await log_admin_action(
                message.from_user.id,
                "set_price",
                f"provider=kling, model={model}, price={price}"
            )
            
            await message.answer(
                f"✅ Цена установлена\n\n"
                f"Провайдер: Kling{model_text}\n"
                f"Цена: {price} ₽",
                parse_mode="HTML"
            )
        else:
            await message.answer("⚠️ Ошибка установки цены")
    
    except ValueError:
        await message.answer("⚠️ Неверный формат: цена должна быть числом")
    except Exception as e:
        logger.error(f"Error in set_kling_price: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)}")


@router.message(Command("prices"))
async def show_prices(message: Message):
    """Показать все установленные цены"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        # Получить цены из БД
        prices_db = await db.get_all_prices()
        
        # Получить цены из config
        config_prices = {
            "NanoBanana (generation)": config.IMAGE_GENERATION_PRICE,
            "NanoBanana (edit)": config.IMAGE_EDIT_PRICE,
            "Kling (5 sec)": config.VIDEO_5SEC_PRICE,
            "Kling (10 sec)": config.VIDEO_10SEC_PRICE,
        }
        
        text = "💰 <b>Текущие цены</b>\n\n"
        
        # Цены из БД (приоритет)
        if prices_db:
            text += "<b>📊 Установленные в БД:</b>\n"
            for price in prices_db:
                provider = price['provider']
                model = price['model'] or "все"
                action = price['action'] or "все"
                price_rub = price['price_rub']
                text += f"• {provider} ({model}/{action}): {price_rub} ₽\n"
            text += "\n"
        
        # Цены из config (fallback)
        text += "<b>⚙️ Из конфига (fallback):</b>\n"
        for name, price in config_prices.items():
            text += f"• {name}: {price} ₽\n"
        
        text += "\n<b>Команды:</b>\n"
        text += "/price_nanobanana &lt;₽&gt; [action]\n"
        text += "/price_kling [model] &lt;₽&gt;"
        
        await message.answer(text, parse_mode="HTML")
    
    except Exception as e:
        logger.error(f"Error in show_prices: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)}")


# ==================== СТАТИСТИКА ====================

@router.message(Command("stats"))
async def show_statistics(message: Message):
    """
    Показать статистику бота
    
    Доступно только администраторам
    """
    if not is_admin(message.from_user.id):
        await message.answer("⚠️ Эта команда доступна только администраторам")
        return
    
    try:
        # Получить статистику из БД
        conn = await db._get_connection()
        cursor = await conn.execute("""
            SELECT 
                COUNT(DISTINCT user_id) as total_users,
                COUNT(DISTINCT CASE WHEN balance > 0 THEN user_id END) as users_with_balance,
                SUM(balance) as total_balance
            FROM users
        """)
        user_stats = await cursor.fetchone()
        
        cursor = await conn.execute("""
            SELECT 
                COUNT(*) as total_payments,
                COUNT(CASE WHEN status = 'paid' THEN 1 END) as paid_payments,
                SUM(CASE WHEN status = 'paid' THEN amount ELSE 0 END) as total_revenue
            FROM payments
        """)
        payment_stats = await cursor.fetchone()
        
        cursor = await conn.execute("""
            SELECT 
                COUNT(DISTINCT user_id) as paying_users
            FROM payments
            WHERE status = 'paid'
        """)
        paying_stats = await cursor.fetchone()
        
        # Статистика за сегодня
        cursor = await conn.execute("""
            SELECT 
                COUNT(CASE WHEN status = 'paid' THEN 1 END) as today_payments,
                SUM(CASE WHEN status = 'paid' THEN amount ELSE 0 END) as today_revenue
            FROM payments
            WHERE DATE(created_at) = DATE('now')
        """)
        today_stats = await cursor.fetchone()
        
        await conn.close()
        
        # Формирование сообщения
        text = (
            f"📊 <b>Статистика бота</b>\n\n"
            f"👥 <b>Пользователи:</b>\n"
            f"• Всего: {user_stats[0]}\n"
            f"• С балансом: {user_stats[1]}\n"
            f"• Платящие: {paying_stats[0]}\n\n"
            f"💰 <b>Платежи:</b>\n"
            f"• Всего создано: {payment_stats[0]}\n"
            f"• Оплачено: {payment_stats[1]}\n"
            f"• Общий доход: {payment_stats[2] or 0} ₽\n\n"
            f"📈 <b>Сегодня:</b>\n"
            f"• Платежей: {today_stats[0]}\n"
            f"• Доход: {today_stats[1] or 0} ₽\n\n"
            f"💎 <b>Метрики:</b>\n"
        )
        
        # Конверсия
        if user_stats[0] > 0:
            conversion = (paying_stats[0] / user_stats[0]) * 100
            text += f"• Конверсия: {conversion:.1f}%\n"
        
        # ARPU
        if user_stats[0] > 0:
            arpu = (payment_stats[2] or 0) / user_stats[0]
            text += f"• ARPU: {arpu:.2f} ₽\n"
        
        # Средний чек
        if payment_stats[1] > 0:
            avg_check = (payment_stats[2] or 0) / payment_stats[1]
            text += f"• Средний чек: {avg_check:.2f} ₽\n"
        
        await message.answer(text, parse_mode="HTML")
        
        await log_admin_action(message.from_user.id, "stats", "Просмотр статистики")
    
    except Exception as e:
        logger.error(f"Error in show_statistics: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)}")
