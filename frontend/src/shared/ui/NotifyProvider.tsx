import {
  Alert,
  type AlertColor,
  Button,
  Portal,
  Snackbar,
  type SnackbarCloseReason,
} from "@mui/material";
import { createContext, type ReactNode, useCallback, useContext, useState } from "react";

export interface NotifyAction {
  label: string;
  onClick: () => void;
}

type Notify = (message: string, severity?: AlertColor, action?: NotifyAction) => void;

interface Notification {
  id: number;
  message: string;
  severity: AlertColor;
  action?: NotifyAction;
}

const NotifyContext = createContext<Notify | null>(null);

export function NotifyProvider({ children }: { children: ReactNode }) {
  const [notification, setNotification] = useState<Notification | null>(null);
  const [open, setOpen] = useState(false);

  const notify = useCallback<Notify>((message, severity = "success", action) => {
    setNotification((current) => ({ id: (current?.id ?? 0) + 1, message, severity, action }));
    setOpen(true);
  }, []);

  const close = (_event: unknown, reason?: SnackbarCloseReason) => {
    if (reason !== "clickaway") setOpen(false);
  };

  return (
    <NotifyContext value={notify}>
      {children}
      {notification && (
        // Portalled so that an open dialog, which hides the app root from assistive technology,
        // does not hide the notification with it.
        <Portal>
          <Snackbar
            key={notification.id}
            open={open}
            autoHideDuration={notification.action ? 8000 : 4000}
            onClose={close}
            anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
          >
            <Alert
              severity={notification.severity}
              variant="filled"
              onClose={close}
              action={
                notification.action && (
                  <Button
                    color="inherit"
                    size="small"
                    onClick={() => {
                      setOpen(false);
                      notification.action?.onClick();
                    }}
                  >
                    {notification.action.label}
                  </Button>
                )
              }
            >
              {notification.message}
            </Alert>
          </Snackbar>
        </Portal>
      )}
    </NotifyContext>
  );
}

export function useNotify(): Notify {
  const notify = useContext(NotifyContext);
  if (!notify) throw new Error("useNotify needs a NotifyProvider above it.");
  return notify;
}
