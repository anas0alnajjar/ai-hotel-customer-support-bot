"""Controlled Telegram adapter failures."""


class TelegramError(RuntimeError):
    code = "telegram_error"


class TelegramPayloadError(TelegramError):
    code = "telegram_payload_invalid"


class TelegramDeliveryError(TelegramError):
    code = "telegram_delivery_failed"


class TelegramConfigurationError(TelegramError):
    code = "telegram_not_configured"
