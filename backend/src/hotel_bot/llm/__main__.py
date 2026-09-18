"""Run a minimal live Gemini structured-output and function-call smoke test."""

import asyncio

from hotel_bot.application.hotel_tools import AvailabilityInput
from hotel_bot.application.prompts import SYSTEM_INSTRUCTION
from hotel_bot.core.config import load_settings
from hotel_bot.domain.llm.enums import AnswerBasis, LLMRequestKind
from hotel_bot.domain.llm.models import GroundedAnswer, LLMRequest
from hotel_bot.infrastructure.gemini import GeminiAdapter


async def main() -> None:
    settings = load_settings()
    if settings.gemini_api_key is None:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    key = settings.gemini_api_key.get_secret_value()
    if key in {"", "****", "replace_with_your_gemini_api_key"}:
        raise RuntimeError("GEMINI_API_KEY contains a placeholder")
    adapter = GeminiAdapter(
        api_key=key,
        model=settings.gemini_model,
        timeout_ms=settings.gemini_timeout_ms,
        retry_attempts=settings.gemini_retry_attempts,
    )
    try:
        structured = await adapter.generate(
            LLMRequest(
                kind=LLMRequestKind.FINAL_ANSWER,
                system_instruction=SYSTEM_INSTRUCTION,
                prompt=(
                    "Return a short Arabic welcome. Use basis=controlled, no evidence_ids, "
                    "no tool_names, uncertainty=false, escalation=false."
                ),
                response_schema=GroundedAnswer.model_json_schema(mode="validation"),
                max_output_tokens=256,
                estimated_input_tokens=250,
            )
        )
        if not structured.text:
            raise RuntimeError("Gemini structured-output smoke returned no text")
        answer = GroundedAnswer.model_validate_json(structured.text)
        if answer.basis is not AnswerBasis.CONTROLLED:
            raise RuntimeError("Gemini structured-output smoke returned the wrong basis")
        function = await adapter.generate(
            LLMRequest(
                kind=LLMRequestKind.TOOL_PROPOSAL,
                system_instruction=SYSTEM_INSTRUCTION,
                prompt=(
                    "Call check_room_availability exactly once for two adults from "
                    "2027-01-10 to 2027-01-12. Do not answer."
                ),
                tools=(
                    {
                        "name": "check_room_availability",
                        "description": "Check validated simulated room inventory.",
                        "parameters": AvailabilityInput.model_json_schema(mode="validation"),
                    },
                ),
                max_output_tokens=128,
                estimated_input_tokens=200,
            )
        )
        if (
            len(function.tool_calls) != 1
            or function.tool_calls[0].name != "check_room_availability"
        ):
            raise RuntimeError("Gemini function-call smoke returned an invalid proposal")
        total_tokens = structured.usage.total_tokens + function.usage.total_tokens
        print(
            f"Gemini live smoke passed: provider={adapter.provider_name} "
            f"model={adapter.model_name} calls=2 total_tokens={total_tokens}"
        )
    finally:
        await adapter.close()


if __name__ == "__main__":
    asyncio.run(main())
