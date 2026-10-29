import { Alert, type AlertColor, Portal, Snackbar, type SnackbarCloseReason } from "@mui/material";
import { createContext, type ReactNode, useCallback, useContext, useState } from "react";

type Notify = (message: string, severity?: AlertColor) => void;

interface Notification {
  id: number;
  message: string;
  severity: AlertColor;
}

const NotifyContext = createContext<Notify | null>(null);

export function NotifyProvider({ children }: { children: ReactNode }) {
  const [notification, setNotification] = useState<Notification | null>(null);
  const [open, setOpen] = useState(false);

  const notify = useCallback<Notify>((message, severity = "success") => {
    setNotification((current) => ({ id: (current?.id ?? 0) + 1, message, severity }));
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
            autoHideDuration={4000}
            onClose={close}
            anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
          >
            <Alert severity={notification.severity} variant="filled" onClose={close}>
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
