from typing import Final, Literal

import anthropic
from anthropic.types.beta import BetaTextBlock

from ...contracts.notes import NotesFailure, NotesProvider
from .errors import NotesError
from .llm import Completion
from .prompt import Prompt

type Effort = Literal["low", "medium", "high"]

# `fallbacks: "default"` re-runs a request the model's safety classifiers decline on the model
# Anthropic recommends for that kind of decline, inside the same call.
_FALLBACK_BETA: Final = "server-side-fallback-2026-07-01"
_FIRST_SERVER_ERROR: Final = 500


class ClaudeChatModel:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        *,
        model: str,
        max_output_tokens: int,
        effort: Effort,
    ) -> None:
        self._client: anthropic.AsyncAnthropic = client
        self._model: str = model
        self._max_output_tokens: int = max_output_tokens
        self._effort: Effort = effort

    @property
    def provider(self) -> NotesProvider:
        return NotesProvider.ANTHROPIC

    async def complete(self, prompt: Prompt) -> Completion:
        try:
            response = await self._client.beta.messages.create(
                model=self._model,
                max_tokens=self._max_output_tokens,
                system=prompt.system,
                messages=[{"role": "user", "content": prompt.user}],
                output_config={"effort": self._effort},
                betas=[_FALLBACK_BETA],
                fallbacks="default",
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as error:
            raise NotesError(NotesFailure.PROVIDER_AUTH_FAILED) from error
        except anthropic.RequestTooLargeError as error:
            raise NotesError(NotesFailure.TRANSCRIPT_TOO_LONG) from error
        except anthropic.RateLimitError as error:
            raise NotesError(NotesFailure.PROVIDER_RATE_LIMITED) from error
        except anthropic.APIConnectionError as error:
            raise NotesError(NotesFailure.PROVIDER_UNAVAILABLE) from error
        except anthropic.APIStatusError as error:
            reason = (
                NotesFailure.PROVIDER_UNAVAILABLE
                if error.status_code >= _FIRST_SERVER_ERROR
                else NotesFailure.PROVIDER_REJECTED_REQUEST
            )
            raise NotesError(reason) from error
        if response.stop_reason == "refusal":
            raise NotesError(NotesFailure.PROVIDER_REFUSED)
        # A cut-off answer can already hold every heading, so parse_notes would accept it.
        if response.stop_reason == "max_tokens":
            raise NotesError(NotesFailure.INVALID_OUTPUT)
        if response.stop_reason == "model_context_window_exceeded":
            raise NotesError(NotesFailure.TRANSCRIPT_TOO_LONG)
        text = "".join(block.text for block in response.content if isinstance(block, BetaTextBlock))
        return Completion(text=text, model_name=response.model)
