"""MySQL adapter for mandatory redacted tool-attempt audit records."""

from sqlalchemy.ext.asyncio import AsyncSession

from hotel_bot.domain.tools.models import ToolAttemptRecord
from hotel_bot.persistence.models import ToolExecution


class SQLAlchemyToolAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_tool_attempt(self, attempt: ToolAttemptRecord) -> None:
        self._session.add(
            ToolExecution(
                message_id=attempt.message_id,
                tool_name=attempt.tool_name,
                arguments_redacted=attempt.arguments_redacted,
                result_status=attempt.result_status,
                result_redacted=attempt.result_redacted,
                latency_ms=attempt.latency_ms,
                correlation_id=attempt.correlation_id,
                error_code=attempt.error_code,
            )
        )
        await self._session.flush()
