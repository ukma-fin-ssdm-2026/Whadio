import { ListItem, ListItemButton } from "@mui/material";
import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { ListPanel } from "./ListPanel";

test("renders its rows as the items of one list", () => {
  // Act
  render(
    <ListPanel>
      <ListItem disablePadding>
        <ListItemButton>First</ListItemButton>
      </ListItem>
      <ListItem disablePadding>
        <ListItemButton>Second</ListItemButton>
      </ListItem>
    </ListPanel>,
  );

  // Assert
  expect(screen.getByRole("list").children).toHaveLength(2);
});
