#!/usr/bin/env python3
"""CLI-прототип платёжного сервиса (кейс 1).

Запуск: python 05_app.py payment.json

Входной JSON содержит order_id, recipient, purpose, amount, currency,
idempotency_key. Результаты сохраняются в payments_out.csv.

Примечание: это консольная демонстрация обработки платежа, а не HTTP API.
Отдельный этап подтверждения по confirm_token здесь не реализован.
"""

import csv
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(BASE_DIR, "payments_out.csv")
GATEWAY_LOG = os.path.join(BASE_DIR, "gateway.log")

# Файл получателей всегда хранится в папке 01_данные.
RECIPIENTS_CSV = os.path.join(BASE_DIR, "01_данные", "recipients.csv")

FIELDS = [
    "payment_id", "order_id", "recipient", "purpose", "amount", "currency",
    "status", "error_code", "idempotency_key", "created_at", "confirmed_at",
    "correlation_id",
]
REQUIRED_FIELDS = ("order_id", "recipient", "purpose", "amount", "currency", "idempotency_key")
ORDER_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
PAN_PATTERN = re.compile(r"\d{13,19}")
IDEMPOTENCY_TTL = timedelta(hours=24)


# Возвращает текущее время UTC.
def utc_now():
    """Текущее время в ISO 8601, например 2026-11-07T12:00:00Z."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# Читает CSV получателей.
def read_recipients(path):
    """Открыть CSV в UTF-8 либо Windows-1251 (кодировка файла из архива)."""
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            with open(path, encoding=encoding, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise UnicodeError("Не удалось прочитать кодировку recipients.csv")


# Выбирает активных получателей.
def load_active_recipients():
    """Вернуть множество ID получателей со статусом ACTIVE."""
    rows = read_recipients(RECIPIENTS_CSV)
    if rows and not {"recipient_id", "status"}.issubset(rows[0]):
        raise ValueError("В recipients.csv нет столбцов recipient_id и status")
    return {row["recipient_id"] for row in rows if row.get("status") == "ACTIVE"}


# Преобразует сумму в Decimal.
def parse_amount(value):
    """Преобразовать сумму в Decimal без ошибок округления float."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() else None


# Проверяет данные платежа.
def validate(payload, active_recipients):
    """Проверить V-1…V-7 и формат idempotency_key; вернуть [(поле, код), ...].

    V-8 и V-9 выполняются отдельно: они ищут платежи в истории и должны
    возвращать существующую запись, а не просто ошибку валидации.
    """
    errors = []

    # V-1: обязательные поля не должны отсутствовать или быть пустыми.
    for field in REQUIRED_FIELDS:
        value = payload.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append((field, "VALIDATION_ERROR"))

    # V-2: 1–64 латинских буквы, цифры, '_' или '-'.
    order_id = payload.get("order_id")
    if order_id is not None and not (isinstance(order_id, str) and ORDER_ID_PATTERN.fullmatch(order_id)):
        errors.append(("order_id", "INVALID_FORMAT"))

    # V-3 и V-7: диапазон суммы и точность не более двух знаков.
    if payload.get("amount") is not None:
        amount = parse_amount(payload["amount"])
        if amount is None:
            errors.append(("amount", "VALIDATION_ERROR"))
        else:
            if amount <= 0 or amount > 1_000_000:
                errors.append(("amount", "AMOUNT_OUT_OF_RANGE"))
            if amount.as_tuple().exponent < -2:
                errors.append(("amount", "INVALID_AMOUNT_PRECISION"))

    # V-4: поддерживается только RUB.
    currency = payload.get("currency")
    if currency is not None and currency != "RUB":
        errors.append(("currency", "UNSUPPORTED_CURRENCY"))

    # V-5: получатель должен существовать и быть активным.
    recipient = payload.get("recipient")
    if recipient is not None and (not isinstance(recipient, str) or recipient not in active_recipients):
        errors.append(("recipient", "RECIPIENT_NOT_FOUND"))

    # V-6: 1–200 символов; номера карт не разрешены.
    purpose = payload.get("purpose")
    if purpose is not None:
        if not isinstance(purpose, str) or not (1 <= len(purpose) <= 200) or PAN_PATTERN.search(purpose):
            errors.append(("purpose", "INVALID_PURPOSE"))

    # По Data Dictionary ключ обязателен, его длина — 8–64 символа.
    key = payload.get("idempotency_key")
    if key is not None and (not isinstance(key, str) or not (8 <= len(key) <= 64)):
        errors.append(("idempotency_key", "INVALID_FORMAT"))

    return errors


# Имитирует ответ банка.
def emulate_gateway(order_id):
    """Детерминированно вернуть (result, error_code, bucket).

    Вариант выбран по TODO в 05_app.py и error_catalog.md:
    0–6 SUCCESS, 7 INSUFFICIENT_FUNDS, 8 CARD_DECLINED, 9 TIMEOUT.
    """
    bucket = int(hashlib.md5(order_id.encode("utf-8")).hexdigest(), 16) % 10
    if bucket <= 6:
        return "SUCCESS", None, bucket
    if bucket == 7:
        return "DECLINED", "INSUFFICIENT_FUNDS", bucket
    if bucket == 8:
        return "DECLINED", "CARD_DECLINED", bucket
    return "TIMEOUT", "TIMEOUT", bucket


# Загружает историю платежей.
def load_history():
    """Прочитать только результаты этого прототипа, не исходный payments.csv."""
    if not os.path.isfile(OUT_CSV):
        return []
    with open(OUT_CSV, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not set(FIELDS).issubset(reader.fieldnames):
            raise ValueError("payments_out.csv имеет неверный заголовок")
        return list(reader)


# Сохраняет платёж в CSV.
def save_payment(record):
    """Добавить один платёж в CSV, сохранив существующие записи."""
    is_new = not os.path.exists(OUT_CSV) or os.path.getsize(OUT_CSV) == 0
    with open(OUT_CSV, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(record)


# Записывает событие в журнал.
def log_gateway(record, result, error_code, bucket):
    """Добавить запись JSON Lines в журнал шлюза без чувствительных данных."""
    # latency_ms — смоделированная задержка, реального ожидания нет.
    event = {
        "timestamp": utc_now(),
        "request_id": record["correlation_id"],
        "order_id": record["order_id"],
        "amount": record["amount"],
        "currency": record["currency"],
        "bucket": bucket,
        "result": result,
        "error_code": error_code,
        "latency_ms": 30000 if result == "TIMEOUT" else 500,
    }
    with open(GATEWAY_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# Формирует ответ по платежу.
def response_for(record):
    """Представить сохранённый платёж так же, как новый."""
    return {
        "payment_id": record["payment_id"],
        "status": record["status"],
        "error_code": record["error_code"] or None,
    }


# Определяет код завершения.
def exit_code(status):
    """0 — успех, 1 — отказ, 3 — таймаут; 2 — невалидные данные."""
    return 0 if status == "SUCCESS" else (3 if status == "PENDING" else 1)


# Выводит JSON на экран.
def print_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


# Ищет повтор ключа за 24 часа.
def find_recent_idempotency(history, key):
    """Найти ответ по ключу, если с создания прошло не более 24 часов."""
    now = datetime.now(timezone.utc)
    for row in reversed(history):
        if row["idempotency_key"] != key:
            continue
        try:
            created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            age = now - created
            if timedelta(0) <= age <= IDEMPOTENCY_TTL:
                return row
        except ValueError:
            pass
    return None


# Генерирует уникальный UUID.
def generate_unique_id(prefix, existing_ids):
    """Создать полный UUID4 и исключить совпадения с сохранёнными ID."""
    while True:
        identifier = prefix + uuid.uuid4().hex
        if identifier not in existing_ids:
            return identifier


# Управляет обработкой платежа.
def main():
    if len(sys.argv) != 2:
        print("Использование: python 05_app.py payment.json", file=sys.stderr)
        return 2

    try:
        # Decimal сохраняет количество цифр после точки в исходном JSON.
        with open(sys.argv[1], encoding="utf-8") as f:
            payload = json.load(f, parse_float=Decimal)
        if not isinstance(payload, dict):
            raise ValueError("Корень JSON должен быть объектом")
        active = load_active_recipients()
        history = load_history()
    except (OSError, ValueError, UnicodeError, csv.Error) as exc:
        print_json({"status": "ERROR", "error_code": "VALIDATION_ERROR", "message": str(exc)})
        return 2

    # V-9: идемпотентность имеет приоритет перед проверкой V-8.
    # Возвращаем именно исходный ответ; журнал шлюза не пополняется.
    key = payload.get("idempotency_key")
    if isinstance(key, str) and 8 <= len(key) <= 64:
        previous = find_recent_idempotency(history, key)
        if previous:
            print("DUPLICATE_REQUEST: возвращён исходный ответ", file=sys.stderr)
            print_json(response_for(previous))
            return exit_code(previous["status"])

    errors = validate(payload, active)
    if errors:
        print_json({
            "status": "ERROR",
            "error_code": "VALIDATION_ERROR",
            "errors": [{"field": field, "code": code} for field, code in errors],
        })
        return 2

    # V-8: одна пара (order_id, recipient) — один платёж.
    for previous in history:
        if previous["order_id"] == payload["order_id"] and previous["recipient"] == payload["recipient"]:
            print_json({
                "status": "ERROR",
                "error_code": "DUPLICATE_ORDER",
                "payment_id": previous["payment_id"],
                "existing_status": previous["status"],
            })
            return 2  # Аналог HTTP 409 в консольной демонстрации.

    gateway_result, error_code, bucket = emulate_gateway(payload["order_id"])
    # После таймаута статус неизвестен: не считаем платёж окончательно отклонённым.
    status = "PENDING" if gateway_result == "TIMEOUT" else gateway_result
    # Не обрезаем UUID и дополнительно проверяем уникальность в истории.
    payment_id = generate_unique_id("pay_", {row["payment_id"] for row in history})
    correlation_id = generate_unique_id("corr_", {row["correlation_id"] for row in history})
    record = {
        "payment_id": payment_id,
        "order_id": payload["order_id"],
        "recipient": payload["recipient"],
        "purpose": payload["purpose"],
        "amount": format(parse_amount(payload["amount"]), ".2f"),
        "currency": payload["currency"],
        "status": status,
        "error_code": error_code or "",
        "idempotency_key": payload["idempotency_key"],
        "created_at": utc_now(),
        "confirmed_at": utc_now() if status == "SUCCESS" else "",
        "correlation_id": correlation_id,
    }
    try:
        # CSV — единственное хранилище в учебном прототипе.
        save_payment(record)
        log_gateway(record, gateway_result, error_code, bucket)
    except OSError as exc:
        print_json({"status": "ERROR", "error_code": "STORAGE_ERROR", "message": str(exc)})
        return 2

    print_json(response_for(record))
    return exit_code(status)


if __name__ == "__main__":
    sys.exit(main())
