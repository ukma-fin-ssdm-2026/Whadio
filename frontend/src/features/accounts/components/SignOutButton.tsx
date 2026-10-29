import LogoutOutlinedIcon from "@mui/icons-material/LogoutOutlined";
import { IconButton, Tooltip } from "@mui/material";
import { useSignOut } from "../api/session";

export function SignOutButton({ onSignedOut }: { onSignedOut: () => void }) {
  const signOut = useSignOut();
  return (
    <Tooltip title="Sign out" arrow>
      <IconButton
        size="small"
        aria-label="Sign out"
        onClick={() => signOut.mutate(undefined, { onSettled: onSignedOut })}
      >
        <LogoutOutlinedIcon fontSize="small" />
      </IconButton>
    </Tooltip>
  );
}
