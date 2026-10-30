import { act, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { errorBody, meetingSummary, page } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { POLL_INTERVAL_MS } from "../api/meetings";
import { WorkspaceMeetings } from "./WorkspaceMeetings";

const FIRST = meetingSummary({ id: "first", name: "Newest sync" });
const SECOND = meetingSummary({ id: "second", name: "Oldest sync" });

afterEach(() => {
  vi.useRealTimers();
});

type MeetingList = (search: URLSearchParams) => ReturnType<typeof page<Schemas["MeetingSummary"]>>;

function serveMeetings(list: MeetingList) {
  const searches: string[] = [];
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/meetings", ({ request, response }) => {
      const url = new URL(request.url);
      searches.push(url.search);
      return response(200).json(list(url.searchParams));
    }),
  );
  return searches;
}

const twoPages: MeetingList = (search) =>
  search.get("cursor") ? page([SECOND]) : page([FIRST], "next-page");

function renderMeetings() {
  return renderWithProviders(
    <WorkspaceMeetings workspaceId="workspace" selectedMeetingId="" onMeeting={() => {}} />,
  );
}

const rowTitles = () =>
  screen.getAllByRole("listitem").map((row) => row.querySelector(".MuiListItemText-primary"));

async function loadSecondPage() {
  const { user } = renderMeetings();
  await user.click(await screen.findByRole("button", { name: "Load more" }));
  await screen.findByText("Oldest sync");
}

test("Load more appends the next page", async () => {
  // Arrange
  serveMeetings(twoPages);

  // Act
  await loadSecondPage();

  // Assert
  expect(rowTitles().map((title) => title?.textContent)).toEqual(["Newest sync", "Oldest sync"]);
});

test("Load more asks for the page after the cursor", async () => {
  // Arrange
  const searches = serveMeetings(twoPages);

  // Act
  await loadSecondPage();

  // Assert
  expect(searches).toEqual(["?limit=100", "?limit=100&cursor=next-page"]);
});

test("Load more disappears on the last page", async () => {
  // Arrange
  serveMeetings(twoPages);

  // Act
  await loadSecondPage();

  // Assert
  expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
});

test("a single page offers no Load more", async () => {
  // Arrange
  serveMeetings(() => page([FIRST]));

  // Act
  renderMeetings();
  await screen.findByText("Newest sync");

  // Assert
  expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
});

test("the name filter reaches the server once typing settles", async () => {
  // Arrange
  const searches = serveMeetings((search) => page(search.get("name") ? [SECOND] : [FIRST]));
  const { user } = renderMeetings();
  await screen.findByText("Newest sync");

  // Act
  await user.type(screen.getByPlaceholderText("Filter by name"), " retro ");
  await screen.findByText("Oldest sync");

  // Assert
  expect(searches).toEqual(["?limit=100", "?limit=100&name=retro"]);
});

test("the old rows stay while a new filter loads", async () => {
  // Arrange
  serveMeetings((search) => page(search.get("name") ? [SECOND] : [FIRST]));
  const { user } = renderMeetings();
  await screen.findByText("Newest sync");

  // Act
  await user.type(screen.getByPlaceholderText("Filter by name"), "r");

  // Assert
  expect(screen.getByText("Newest sync")).toBeInTheDocument();
});

test("a filter the server matches nothing for says so", async () => {
  // Arrange
  serveMeetings((search) => page(search.get("name") ? [] : [FIRST]));
  const { user } = renderMeetings();
  await screen.findByText("Newest sync");

  // Act
  await user.type(screen.getByPlaceholderText("Filter by name"), "retro");

  // Assert
  expect(await screen.findByText("No meetings match these filters")).toBeInTheDocument();
});

test("a workspace with no meetings says so", async () => {
  // Arrange
  serveMeetings(() => page([]));

  // Act
  renderMeetings();

  // Assert
  expect(await screen.findByText("No meetings yet")).toBeInTheDocument();
});

test("a failed load shows the server's message", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/meetings", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "No such workspace")),
    ),
  );

  // Act
  renderMeetings();

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("No such workspace");
});

function serveStatesInTurn(...states: Schemas["ProcessingState"][]) {
  return serveMeetings(() => {
    const processing_state = states.length > 1 ? states.shift() : states[0];
    return page([meetingSummary({ processing_state })]);
  });
}

async function advancePolls(count: number) {
  for (let poll = 0; poll < count; poll += 1) {
    await act(() => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
  }
}

test("meetings in progress are polled", async () => {
  // Arrange
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const searches = serveStatesInTurn("queued");
  renderMeetings();
  await waitFor(() => expect(searches).toHaveLength(1));

  // Act
  await advancePolls(2);

  // Assert
  expect(searches).toHaveLength(3);
});

test("polling stops once nothing is in progress", async () => {
  // Arrange
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const searches = serveStatesInTurn("processing", "processed");
  renderMeetings();
  await waitFor(() => expect(searches).toHaveLength(1));
  await advancePolls(1);

  // Act
  await advancePolls(3);

  // Assert
  expect(searches).toHaveLength(2);
});

test("settled meetings are not polled", async () => {
  // Arrange
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const searches = serveStatesInTurn("processed");
  renderMeetings();
  await waitFor(() => expect(searches).toHaveLength(1));

  // Act
  await advancePolls(2);

  // Assert
  expect(searches).toHaveLength(1);
});

test("choosing a row opens its meeting", async () => {
  // Arrange
  serveMeetings(() => page([FIRST]));
  const onMeeting = vi.fn();
  renderWithProviders(
    <WorkspaceMeetings workspaceId="workspace" selectedMeetingId="" onMeeting={onMeeting} />,
  );

  // Act
  await userEvent.click(await screen.findByRole("button", { name: /Newest sync/ }));

  // Assert
  expect(onMeeting).toHaveBeenCalledExactlyOnceWith("first");
});
