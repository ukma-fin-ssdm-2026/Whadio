from dataclasses import dataclass
from uuid import UUID

from ...contracts.notes import NotesFailure, NotesProvider, NotesRequested
from .errors import NotesError
from .llm import IChatModel
from .map_reduce import MapReducePrompts
from .output import ParsedNotes, parse_notes
from .prompt import Prompt, PromptBuilder


@dataclass(frozen=True, slots=True)
class WrittenNotes:
    notes: ParsedNotes
    provider: NotesProvider
    model_name: str
    context_meeting_ids: tuple[UUID, ...]
    transcript_parts: int


class NotesWriter:
    """Writes notes in one call when the prompt fits, and by map-reduce over parts otherwise.

    `write` raises `NotesError` with the reason the notes could not be written.
    """

    def __init__(
        self, builder: PromptBuilder, map_reduce: MapReducePrompts, model: IChatModel
    ) -> None:
        self._builder: PromptBuilder = builder
        self._map_reduce: MapReducePrompts = map_reduce
        self._model: IChatModel = model

    async def write(self, request: NotesRequested) -> WrittenNotes:
        prompt = self._single_pass(request)
        parts = 1
        if prompt is None:
            extracts = self._map_reduce.extract(request)
            partial_notes = [(await self._model.complete(extract)).text for extract in extracts]
            prompt = self._map_reduce.reduce(request, partial_notes)
            parts = len(extracts)
        completion = await self._model.complete(prompt)
        return WrittenNotes(
            notes=parse_notes(completion.text, prompt.headings),
            provider=self._model.provider,
            model_name=completion.model_name,
            context_meeting_ids=prompt.context_meeting_ids,
            transcript_parts=parts,
        )

    def _single_pass(self, request: NotesRequested) -> Prompt | None:
        try:
            return self._builder.build(request)
        except NotesError as error:
            if error.reason is NotesFailure.TRANSCRIPT_TOO_LONG:
                return None
            raise
