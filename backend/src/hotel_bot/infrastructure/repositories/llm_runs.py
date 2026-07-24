"""MySQL adapter for LLM request telemetry without prompt content."""

from sqlalchemy.ext.asyncio import AsyncSession

from hotel_bot.domain.llm.models import LLMRunRecord
from hotel_bot.persistence.models import LLMRun


class SQLAlchemyLLMRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_llm_run(self, record: LLMRunRecord) -> None:
        usage = record.usage
        self._session.add(
            LLMRun(
                message_id=record.message_id,
                provider=record.provider,
                model=record.model,
                prompt_version=record.prompt_version,
                request_kind=record.request_kind.value,
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                thought_tokens=usage.thought_tokens if usage else None,
                total_tokens=usage.total_tokens if usage else None,
                estimated_cost_usd=record.estimated_cost_usd,
                provider_request_id=record.provider_request_id,
                latency_ms=record.latency_ms,
                status=record.status,
                error_code=record.error_code,
            )
        )
        await self._session.flush()
