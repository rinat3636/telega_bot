# Changelog v3.4.0 (2026-02-12)

## 🐛 Critical Bug Fixes

### 1. Webhook JSON Parsing + Fail-Closed Validation

**Проблема:** `json.loads(payload)` падал, так как `payload` — bytes. Валидация была "fail-open" — при неинициализированном валидаторе webhook обрабатывался без проверки.

**Исправление:**
- Изменено на `json.loads(payload.decode('utf-8'))` для корректного парсинга
- Изменено поведение при `RuntimeError`: теперь возвращается 503 (fail-closed) вместо продолжения обработки
- Webhook validation стала обязательной в production

**Файлы:** `handlers/webhook.py`

---

### 2. Triggers для UPDATE/DELETE в ledger

**Проблема:** `user_balance_cache` обновлялся только при INSERT в ledger. UPDATE (например, в `charge_reserved_balance()`) и DELETE оставляли кэш stale.

**Исправление:**
- Добавлен trigger `update_balance_cache_on_ledger_update` для UPDATE
- Добавлен trigger `update_balance_cache_on_ledger_delete` для DELETE
- Кэш теперь синхронизируется при всех операциях с ledger

**Файлы:** `database/models.py`

---

### 3. Идемпотентность charge_reserved_balance

**Проблема:** Повторный вызов `charge_reserved_balance()` падал с "Reservation not found", так как reservation уже был преобразован в job.

**Исправление:**
- Добавлена проверка: если reservation не найдена, проверяется наличие job с `new_ref_id`
- Если job уже создана, функция возвращает успех без ошибок (идемпотентность)
- Reconciliation записи защищены от дублирования через обработку UNIQUE constraint

**Файлы:** `database/models.py`

---

## 🧪 Tests

- Добавлен `tests/test_v3.4_fixes.py` с unit-тестами для всех 3 исправлений:
  - `test_balance_cache_updates_on_ledger_update()`
  - `test_balance_cache_updates_on_ledger_delete()`
  - `test_charge_reserved_balance_idempotent()`
  - `test_charge_reserved_balance_reconciliation_idempotent()`

---

## 📚 Documentation

- Обновлен `README_v3.4.md`
- Создан `V3.4_FIXES.md` с детальным описанием всех исправлений

---

**Версия:** 3.4.0  
**Дата:** 2026-02-12  
**Статус:** ✅ Production Ready
