import ContentCopyOutlinedIcon from "@mui/icons-material/ContentCopyOutlined";
import { IconButton, InputAdornment, TextField, Tooltip } from "@mui/material";
import type { FocusEvent } from "react";
import { useNotify } from "./NotifyProvider";

interface CopyFieldProps {
  value: string;
  label: string;
  copyLabel: string;
}

export function CopyField({ value, label, copyLabel }: CopyFieldProps) {
  const notify = useNotify();

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      notify("Copied");
    } catch {
      notify("Could not copy. Select the text and copy it yourself.", "error");
    }
  };

  return (
    <TextField
      value={value}
      fullWidth
      slotProps={{
        htmlInput: {
          readOnly: true,
          "aria-label": label,
          onFocus: (event: FocusEvent<HTMLInputElement>) => event.currentTarget.select(),
        },
        input: {
          endAdornment: (
            <InputAdornment position="end">
              <Tooltip title={copyLabel} arrow>
                <IconButton aria-label={copyLabel} edge="end" onClick={copy}>
                  <ContentCopyOutlinedIcon />
                </IconButton>
              </Tooltip>
            </InputAdornment>
          ),
        },
      }}
    />
  );
}
