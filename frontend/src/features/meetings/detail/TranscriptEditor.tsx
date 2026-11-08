import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import { Alert, Button, ButtonBase, Chip, Stack, TextField, Typography } from "@mui/material";
import { memo, useEffect, useRef, useState } from "react";
import { type Control, useController, useForm, useWatch } from "react-hook-form";
import type { TranscriptRead } from "@/shared/api/types";
import { formatTimestamp } from "@/shared/lib/format";
import { countOf } from "@/shared/lib/plural";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { useEditTranscript } from "../api/meetings";
import type { Meeting } from "../model";
import { SegmentRow } from "./SegmentRow";
import { type LabelledSegment, NO_MATCH } from "./segments";
import { countChanges, draftOf, revisionInput, type TranscriptDraft } from "./transcript-draft";

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
  active: boolean;
  onActive: (index: number | null) => void;
}

const EditableSegment = memo(function EditableSegment({
  control,
  segment,
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
      speaker={segment.speaker}
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

interface EditBarProps {
  control: Control<TranscriptDraft>;
  base: TranscriptRead;
  pending: boolean;
  error: string | undefined;
  onCancel: () => void;
}

function EditBar({ control, base, pending, error, onCancel }: EditBarProps) {
  const segments = useWatch({ control, name: "segments" });
  const changes = countChanges(revisionInput(base, { segments }));

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

interface TranscriptEditorProps {
  meeting: Pick<Meeting, "id" | "state">;
  base: TranscriptRead;
  segments: LabelledSegment[];
  onClose: () => void;
  onShowCurrent: () => void;
}

export function TranscriptEditor({
  meeting,
  base,
  segments,
  onClose,
  onShowCurrent,
}: TranscriptEditorProps) {
  const notify = useNotify();
  const edit = useEditTranscript(meeting);
  const [active, setActive] = useState<number | null>(null);
  const { control, handleSubmit } = useForm({ defaultValues: draftOf(base) });

  const submit = handleSubmit((draft) => {
    const input = revisionInput(base, draft);
    if (!input || edit.isPending) return;
    edit.mutate(input, {
      onSuccess: () => {
        notify("Transcript saved. The original stays available.");
        onClose();
        onShowCurrent();
      },
      onError: (error) => {
        if (error.code !== "STALE_REVISION") return;
        notify(
          `Someone else edited this transcript, so it was reloaded. ${notSaved(countChanges(input))}`,
          "warning",
        );
        onClose();
        onShowCurrent();
      },
    });
  });

  return (
    <Stack component="form" noValidate onSubmit={submit} sx={{ gap: 1.5 }}>
      {segments.map((segment) => (
        <EditableSegment
          key={segment.id}
          control={control}
          segment={segment}
          active={active === segment.index}
          onActive={setActive}
        />
      ))}
      {segments.length === 0 && <Typography color="textSecondary">{NO_MATCH}</Typography>}
      <EditBar
        control={control}
        base={base}
        pending={edit.isPending}
        error={edit.error?.message}
        onCancel={onClose}
      />
    </Stack>
  );
}
