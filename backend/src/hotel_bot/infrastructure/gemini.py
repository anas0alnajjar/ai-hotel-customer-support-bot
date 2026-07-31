"""Google Gemini adapter behind provider-neutral application contracts."""

import asyncio
from typing import Any, cast

from google import genai
from google.genai import errors, types

from hotel_bot.domain.llm.enums import LLMRequestKind
from hotel_bot.domain.llm.errors import LLMContractError, LLMTimeoutError, LLMUnavailableError
from hotel_bot.domain.llm.models import LLMRequest, LLMResponse, LLMUsage, ProposedToolCall


class GeminiAdapter:
    provider_name = "google_gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_ms: int = 20_000,
        retry_attempts: int = 2,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Gemini API key is required")
        self.model_name = model
        self._timeout_seconds = timeout_ms / 1000
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=timeout_ms,
                retry_options=types.HttpRetryOptions(
                    attempts=retry_attempts,
                    initial_delay=0.5,
                    max_delay=2.0,
                    jitter=0.2,
                ),
            ),
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        declarations = [
            types.FunctionDeclaration(
                name=str(item["name"]),
                description=str(item["description"]),
                parameters_json_schema=cast(dict[str, Any], item["parameters"]),
            )
            for item in request.tools
        ]
        config = types.GenerateContentConfig(
            http_options=(
                types.HttpOptions(
                    retry_options=types.HttpRetryOptions(attempts=1)
                )
                if request.kind is LLMRequestKind.HYBRID_INTENT_ANALYSIS
                else None
            ),
            system_instruction=request.system_instruction,
            max_output_tokens=request.max_output_tokens,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tools=[types.Tool(function_declarations=declarations)] if declarations else None,
            response_mime_type="application/json" if request.response_schema else None,
            response_json_schema=request.response_schema,
        )
        try:
            async with asyncio.timeout(self._timeout_seconds):
                response = await self._client.aio.models.generate_content(
                    model=self.model_name,
                    contents=request.prompt,
                    config=config,
                )
        except TimeoutError as exc:
            raise LLMTimeoutError("Gemini request timed out") from exc
        except errors.APIError as exc:
            raise LLMUnavailableError("Gemini request failed") from exc
        except Exception as exc:
            raise LLMUnavailableError("Gemini transport unavailable") from exc

        usage = response.usage_metadata
        parsed_usage = LLMUsage(
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=(usage.candidates_token_count or 0) if usage else 0,
            thought_tokens=(usage.thoughts_token_count or 0) if usage else 0,
            total_tokens=(usage.total_token_count or 0) if usage else 0,
        )
        calls: list[ProposedToolCall] = []
        texts: list[str] = []
        candidates = response.candidates or []
        for candidate in candidates[:1]:
            if candidate.content is None:
                continue
            for index, part in enumerate(candidate.content.parts or [], start=1):
                if part.text:
                    texts.append(part.text)
                function_call = part.function_call
                if function_call is not None:
                    if not function_call.name:
                        raise LLMContractError("Gemini returned a nameless function call")
                    calls.append(
                        ProposedToolCall(
                            call_id=function_call.id or f"call-{index}",
                            name=function_call.name,
                            arguments=dict(function_call.args or {}),
                        )
                    )
        finish_reason: str | None = None
        if candidates and candidates[0].finish_reason is not None:
            finish_reason = str(candidates[0].finish_reason.value)
        return LLMResponse(
            text="".join(texts).strip() or None,
            tool_calls=tuple(calls),
            usage=parsed_usage,
            provider_request_id=response.response_id,
            finish_reason=finish_reason,
        )

    async def close(self) -> None:
        await self._client.aio.aclose()
