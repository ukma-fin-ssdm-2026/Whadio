import { zodResolver } from "@hookform/resolvers/zod";
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle } from "@mui/material";
import { type UseFormSetError, useForm } from "react-hook-form";
import { z } from "zod";
import type { ApiError } from "@/shared/api/errors";
import { FormTextField } from "@/shared/ui/FormTextField";
import { useNotify } from "@/shared/ui/NotifyProvider";
import { useUpdateMeeting } from "../api/meetings";
import type { Meeting } from "../model";

const meetingName = z.object({
  name: z.string().trim().min(1, "Enter a meeting name").max(200, "Use 200 characters or fewer"),
});

type MeetingNameValues = z.infer<typeof meetingName>;

function showServerError(error: ApiError, setError: UseFormSetError<MeetingNameValues>) {
  const nameError = error.details.find(({ field }) => field === "name");
  if (nameError) setError("name", { type: "server", message: nameError.message });
  else setError("root.server", { type: "server", message: error.message });
}

interface RenameMeetingDialogProps {
  meeting: Meeting;
  onClose: () => void;
}

export function RenameMeetingDialog({ meeting, onClose }: RenameMeetingDialogProps) {
  const notify = useNotify();
  const updateMeeting = useUpdateMeeting(meeting.id, meeting.workspaceId);
  const { control, handleSubmit, setError, formState } = useForm({
    resolver: zodResolver(meetingName),
    defaultValues: { name: meeting.title },
  });

  const close = () => {
    if (!updateMeeting.isPending) onClose();
  };
  const submit = handleSubmit(({ name }) => {
    if (updateMeeting.isPending) return;
    updateMeeting.mutate(
      { name },
      {
        onSuccess: () => {
          notify("Meeting renamed.");
          onClose();
        },
        onError: (error) => showServerError(error, setError),
      },
    );
  });

  return (
    <Dialog open onClose={close} maxWidth="xs" fullWidth>
      <DialogTitle>Rename meeting</DialogTitle>
      <DialogContent>
        <form id="rename-meeting-form" noValidate onSubmit={submit}>
          <FormTextField
            control={control}
            name="name"
            label="Meeting name"
            autoComplete="off"
            autoFocus
            fullWidth
            sx={{ mt: 1 }}
          />
        </form>
        {formState.errors.root?.server?.message && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {formState.errors.root.server.message}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={close} disabled={updateMeeting.isPending}>
          Cancel
        </Button>
        <Button
          type="submit"
          form="rename-meeting-form"
          variant="contained"
          loading={updateMeeting.isPending}
        >
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}
