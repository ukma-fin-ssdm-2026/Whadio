import {
  ListItemButton,
  type ListItemButtonProps,
  Link as MuiLink,
  type LinkProps as MuiLinkProps,
} from "@mui/material";
import { createLink } from "@tanstack/react-router";

function ListItemAnchor(props: ListItemButtonProps<"a">) {
  return <ListItemButton component="a" {...props} />;
}

export const ListItemLink = createLink(ListItemAnchor);

function TextAnchor(props: MuiLinkProps) {
  return <MuiLink variant="body2" underline="hover" {...props} />;
}

export const TextLink = createLink(TextAnchor);
