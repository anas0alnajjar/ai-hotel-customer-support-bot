"""Strict inbound update and channel response models."""

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from hotel_bot.domain.conversation.models import SupportedLanguage

TelegramCommand = Literal["start", "help", "new", "language_ar", "language_en"]


class TelegramUser(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int = Field(gt=0)
    is_bot: bool
    language_code: str | None = Field(default=None, max_length=35)


class TelegramChat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    type: str = Field(min_length=1, max_length=32)


class TelegramMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    message_id: int = Field(gt=0)
    sender: TelegramUser | None = Field(
        default=None,
        validation_alias=AliasChoices("from", "sender"),
    )
    chat: TelegramChat
    date: int = Field(ge=0)
    text: str | None = Field(default=None, max_length=4096)


class TelegramUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    update_id: int = Field(ge=0)
    message: TelegramMessage | None = None


class TelegramInboundMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    update_id: str
    chat_id: int
    user_id: int = Field(gt=0)
    message_id: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=4096)
    language: SupportedLanguage
    command: TelegramCommand | None = None


class TelegramGuestReply(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1, max_length=4096)
    language: SupportedLanguage
    duplicate: bool = False


class TelegramWebhookResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["processed", "duplicate", "ignored"]
    update_id: str


class TelegramSentMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: int = Field(gt=0)
    chat_id: int
