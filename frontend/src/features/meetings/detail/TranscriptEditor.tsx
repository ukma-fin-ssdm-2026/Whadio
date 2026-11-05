import { zodResolver } from "@hookform/resolvers/zod";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import { Alert, Box, Button, ButtonBase, Chip, Stack, TextField, Typography } from "@mui/material";
import { memo, useEffect, useRef, useState } from "react";
import {
  type Control,
  type UseFormSetError,
  useController,
  useForm,
  useFormState,
  useWatch,
} from "react-hook-form";
import type { ApiError } from "@/shared/api/errors";
import type { RevisionInput, TranscriptRead } from "@/shared/api/types";
import { formatTimestamp } from "@/shared/lib/format";
import { countOf } from "@/shared/lib/plural";
import { FormTextField } from "@/shared/ui/FormTextField";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { useEditTranscript } from "../api/meetings";
import type { Meeting } from "../model";
import { SegmentRow } from "./SegmentRow";
import { type LabelledSegment, NO_MATCH } from "./segments";
import {
  countChanges,
  draftOf,
  revisionInput,
  type TranscriptDraft,
  transcriptDraft,
} from "./transcript-draft";

interface SegmentFieldProps {
  control: Control<TranscriptDraft>;
  index: number;
  label: string;
  onDone: () => void;
}

function SegmentField({ control, index, label, onDone }: SegmentFieldProps) {
  const {
    field: { ref, ...field },
  } = useController({ control, name: `segments.${index}.text` });
  const [opened] = useState(field.value);

  return (
    <TextField
      {...field}
      inputRef={ref}
      label={label}
      multiline
      fullWidth
      size="small"
      autoFocus
      onFocus={({ target }) => target.setSelectionRange(target.value.length, target.value.length)}
      onBlur={() => {
        field.onBlur();
        onDone();
      }}
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        field.onChange(opened);
        onDone();
      }}
    />
  );
}

interface EditableSegmentProps {
  control: Control<TranscriptDraft>;
  segment: LabelledSegment;
  speaker: string;
  active: boolean;
  onActive: (index: number | null) => void;
}

const EditableSegment = memo(function EditableSegment({
  control,
  segment,
  speaker,
  active,
  onActive,
}: EditableSegmentProps) {
  const text = useWatch({ control, name: `segments.${segment.index}.text` });
  const time = formatTimestamp(segment.start_seconds);
  const button = useRef<HTMLButtonElement>(null);
  const wasActive = useRef(active);

  useEffect(() => {
    // A field closed by Escape takes the focus with it; leaving it any other way moved it already.
    if (wasActive.current && !active && document.activeElement === document.body) {
      button.current?.focus();
    }
    wasActive.current = active;
  }, [active]);

  return (
    <SegmentRow
      speaker={speaker}
      startSeconds={segment.start_seconds}
      marker={text !== segment.text && <Chip label="Changed" size="small" variant="outlined" />}
    >
      {active ? (
        <SegmentField
          control={control}
          index={segment.index}
          label={`Text at ${time}`}
          onDone={() => onActive(null)}
        />
      ) : (
        <ButtonBase
          ref={button}
          aria-label={`Edit text at ${time}: ${text}`}
          onClick={() => onActive(segment.index)}
          sx={{
            justifyContent: "space-between",
            gap: 1,
            p: "0.35rem 0.5rem",
            m: "-0.35rem -0.5rem",
            borderRadius: "0.4rem",
            textAlign: "left",
            "&:hover, &.Mui-focusVisible": { bgcolor: "action.hover" },
          }}
        >
          <Typography color="textSecondary" sx={{ fontStyle: text ? undefined : "italic" }}>
            {text || "No text"}
          </Typography>
          <EditOutlinedIcon fontSize="small" color="action" />
        </ButtonBase>
      )}
    </SegmentRow>
  );
});

interface SpeakerFieldsProps {
  control: Control<TranscriptDraft>;
  base: TranscriptRead;
}

function SpeakerFields({ control, base }: SpeakerFieldsProps) {
  const segmentCounts = new Map<string | null, number>();
  for (const { speaker_id } of base.segments) {
    segmentCounts.set(speaker_id, (segmentCounts.get(speaker_id) ?? 0) + 1);
  }

  return (
    <Stack sx={{ gap: 1.5, pb: 2, borderBottom: 1, borderBottomColor: "divider" }}>
      <Typography variant="subtitle1" component="h3">
        Speakers
      </Typography>
      <Box
        sx={{
          display: "grid",
          gap: 1.5,
          gridTemplateColumns: { sm: "repeat(auto-fill, minmax(15rem, 1fr))" },
        }}
      >
        {base.speakers.map(({ id, display_name }, index) => (
          <FormTextField
            key={id}
            control={control}
            name={`speakers.${index}.name`}
            label={display_name}
            size="small"
            autoComplete="off"
            helperText={`Applies to ${countOf(segmentCounts.get(id) ?? 0, "segment")}`}
          />
        ))}
      </Box>
    </Stack>
  );
}

interface EditBarProps {
  control: Control<TranscriptDraft>;
  base: TranscriptRead;
  pending: boolean;
  onCancel: () => void;
}

function EditBar({ control, base, pending, onCancel }: EditBarProps) {
  const [speakers, segments] = useWatch({ control, name: ["speakers", "segments"] });
  const { errors } = useFormState({ control });
  const changes = countChanges(revisionInput(base, { speakers, segments }));
  const error = errors.root?.server?.message;

  return (
    <Stack
      sx={{
        position: "sticky",
        bottom: "0.75rem",
        zIndex: 4,
        gap: 1,
        p: 1.5,
        border: 1,
        borderColor: "divider",
        borderRadius: "0.55rem",
        bgcolor: "background.paper",
        boxShadow: 3,
      }}
    >
      {error && <Alert severity="error">{error}</Alert>}
      <Stack direction={{ xs: "column", sm: "row" }} sx={{ gap: 1, alignItems: { sm: "center" } }}>
        <Typography role="status" color="textSecondary" sx={{ flex: 1 }}>
          {changes ? `${countOf(changes, "unsaved change")}.` : "No changes yet."} Saving keeps the
          original transcript.
        </Typography>
        <Stack direction="row" sx={{ gap: 1, justifyContent: "flex-end" }}>
          <Button onClick={onCancel} disabled={pending}>
            {changes ? "Discard changes" : "Cancel"}
          </Button>
          <Button type="submit" variant="contained" disabled={!changes} loading={pending}>
            Save
          </Button>
        </Stack>
      </Stack>
    </Stack>
  );
}

const notSaved = (changes: number) =>
  `Your ${countOf(changes, "change")} ${changes === 1 ? "was" : "were"} not saved.`;

// The server names a speaker by its place in the request, which lists only the renamed ones.
const SENT_SPEAKER_NAME = /^speakers\.(\d+)\.display_name$/;

function showServerError(
  error: ApiError,
  input: RevisionInput,
  base: TranscriptRead,
  setError: UseFormSetError<TranscriptDraft>,
) {
  let onField = false;
  for (const { field, message } of error.details) {
    const sent = SENT_SPEAKER_NAME.exec(field ?? "")?.[1];
    const id = sent === undefined ? undefined : input.speakers?.[Number(sent)]?.id;
    const index = base.speakers.findIndex((speaker) => speaker.id === id);
    if (index < 0) continue;
    setError(`speakers.${index}.name`, { type: "server", message });
    onField = true;
  }
  if (!onField) setError("root.server", { type: "server", message: error.message });
}

interface TranscriptEditorProps {
  meeting: Pick<Meeting, "id" | "state">;
  base: TranscriptRead;
  segments: LabelledSegment[];
  onClose: () => void;
  onSaved: () => void;
}

export function TranscriptEditor({
  meeting,
  base,
  segments,
  onClose,
  onSaved,
}: TranscriptEditorProps) {
  const notify = useNotify();
  const edit = useEditTranscript(meeting);
  const [active, setActive] = useState<number | null>(null);
  const { control, handleSubmit, setError } = useForm({
    resolver: zodResolver(transcriptDraft),
    defaultValues: draftOf(base),
  });
  const names = useWatch({ control, name: "speakers" });
  const speakerIndex = new Map(base.speakers.map(({ id }, index) => [id, index]));
  const speakerOf = ({ speaker_id, speaker }: LabelledSegment) => {
    const index = speaker_id === null ? undefined : speakerIndex.get(speaker_id);
    return (index === undefined ? "" : names[index]?.name.trim()) || speaker;
  };

  const submit = handleSubmit((draft) => {
    const input = revisionInput(base, draft);
    if (!input || edit.isPending) return;
    edit.mutate(input, {
      onSuccess: () => {
        notify("Transcript saved. The original stays available.");
        onClose();
        onSaved();
      },
      onError: (error) => {
        if (error.code !== "STALE_REVISION") {
          showServerError(error, input, base, setError);
          return;
        }
        notify(
          `Someone else edited this transcript, so it was reloaded. ${notSaved(countChanges(input))}`,
          "warning",
        );
        onClose();
      },
    });
  });

  return (
    <Stack component="form" noValidate onSubmit={submit} sx={{ gap: 1.5 }}>
      {base.speakers.length > 0 && <SpeakerFields control={control} base={base} />}
      {segments.map((segment) => (
        <EditableSegment
          key={segment.id}
          control={control}
          segment={segment}
          speaker={speakerOf(segment)}
          active={active === segment.index}
          onActive={setActive}
        />
      ))}
      {segments.length === 0 && <Typography color="textSecondary">{NO_MATCH}</Typography>}
      <EditBar control={control} base={base} pending={edit.isPending} onCancel={onClose} />
    </Stack>
  );
}
