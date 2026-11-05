# Data dictionary — кейс 1 «Платёжный сервис»

## Как заполнять

1. Открой `payments.csv` — в нём 12 колонок, все нужно описать.
2. Для каждой колонки заполни 7 полей: Тип, Обяз., Ограничение, Пример,
Код ошибки, Комментарий.
3. Пример — реальное значение из `payments.csv`, не выдуманное.
4. Код ошибки — только для полей, которые валидируются
(смотри `02\\\_validation\\\_rules.md`). Для серверных полей — «—».
5. Комментарий — одна фраза «зачем это поле».

## Образец заполнения (не трогать, это пример)

|Поле|Тип|Обяз.|Ограничение|Пример|Код ошибки|Комментарий|
|-|-|-|-|-|-|-|
|payment\_id|string|да (сервер)|UUID v4 или `pay\\\_NNNN`|pay\_0001|—|генерируется сервисом, от клиента не приходит|

## Ваша таблица — заполните 11 оставшихся колонок

|Поле|Тип|Обяз.|Ограничение|Пример|Код ошибки|Комментарий|
|-|-|-|-|-|-|-|
|order_id|string|да|`^[A-Za-z0-9_\-]{1,64}$`, 1–64 символа|ord_1001|INVALID_FORMAT|номер заказа клиники; вместе с recipient защищает от дублей|
|recipient|string|да|ID из recipients.csv со статусом ACTIVE|clinic_medservice|RECIPIENT_NOT_FOUND|кому уходят деньги|
|purpose|string|да|1–200 символов, без номера карты (13–19 цифр подряд)|Приём терапевта|INVALID_PURPOSE|услуга за которую платит пациент|
|amount|decimal|да|> 0 и ≤ 1 000 000, не более 2 знаков после точки|2500.00|AMOUNT_OUT_OF_RANGE / INVALID_AMOUNT_PRECISION|сумма платежа|
|currency|string|да|код ISO 4217, сейчас только RUB|RUB|UNSUPPORTED_CURRENCY|в какой валюте произведён платёж|
|status|enum|да (сервер)|CREATED / PENDING / SUCCESS / DECLINED / ERROR / CANCELED|SUCCESS|—|на каком этапе платёж|
|error_code|string|нет (сервер)|пусто, если ошибки нет; иначе один из: INSUFFICIENT_FUNDS, CARD_DECLINED, VALIDATION_ERROR, RECIPIENT_NOT_FOUND, UNSUPPORTED_CURRENCY, AMOUNT_OUT_OF_RANGE, DUPLICATE_ORDER|INSUFFICIENT_FUNDS|—|почему платёж не прошёл|
|idempotency_key|string|да|8–64 символа, уникален 24 часа|idem_0001|DUPLICATE_REQUEST|уникальный ключ запроса, чтобы повторная отправка не создала второй платёж|
|created_at|datetime|да (сервер)|ISO 8601, UTC|2025-11-01T08:00:00Z|—|дата и время создания платежа|
|confirmed_at|datetime|нет (сервер)|ISO 8601, UTC; пусто, пока платёж не подтверждён успешно|2025-11-01T08:00:03Z|—|дата и время когда платёж прошёл|
|correlation_id|string|да (сервер)|уникальный ID запроса для логов|corr_0001|—|метка запроса, по которой в логах находится вся история платежа|

## Критерий приёмки (что проверяет жюри)

* \[ ] Все 12 колонок из `payments.csv` описаны
* \[ ] Тип указан для каждой колонки
* \[ ] Ограничение конкретное (не «строка», а «1–64, regex»)
* \[ ] Пример взят из реального `payments.csv`
* \[ ] Код ошибки совпадает с `08\\\_errors.md`
* \[ ] Для серверных полей (payment\_id, created\_at) стоит «—»
* \[ ] Комментарий объясняет «зачем поле»

## Подсказки, на что смотреть

* order\_id — regex `^\\\[A-Za-z0-9\\\_\\\\-]{1,64}$`
* recipient — ID из `recipients.csv`, статус ACTIVE
* purpose — 1–200 символов, без PAN/CVV
* amount — > 0, ≤ 1 000 000, 2 знака после точки
* currency — ISO 4217, сейчас только RUB
* status — enum из 6 значений (CREATED/PENDING/SUCCESS/DECLINED/ERROR/CANCELED)
* error\_code — только из каталога в `08\\\_errors.md`
* idempotency\_key — 8–64 символа, уникален 24 часа
* created\_at / confirmed\_at — ISO 8601
* correlation\_id — для трассировки в логах

