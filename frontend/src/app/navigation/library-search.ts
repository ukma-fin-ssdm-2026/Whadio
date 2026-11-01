import { useNavigate, useSearch } from "@tanstack/react-router";
import { z } from "zod";
import { NAME_FILTER_MAX_LENGTH, STATE_FILTERS, type StateFilter } from "@/features/meetings/model";

// The router parses `?q=123` into a number before the schema sees it.
export const librarySearch = z.object({
  q: z.coerce.string().max(NAME_FILTER_MAX_LENGTH).optional().catch(undefined),
  state: z.enum(STATE_FILTERS).optional().catch(undefined),
});

type LibrarySearch = z.infer<typeof librarySearch>;

export function useLibraryFilters() {
  const navigate = useNavigate();
  const { q = "", state = "all" } = useSearch({ strict: false });
  const write = (changes: LibrarySearch) =>
    navigate({
      to: ".",
      search: (previous) => ({ ...previous, ...changes }),
      replace: true,
      resetScroll: false,
    });
  return {
    name: q,
    stateFilter: state,
    onName: (name: string) => write({ q: name || undefined }),
    onStateFilter: (filter: StateFilter) => write({ state: filter === "all" ? undefined : filter }),
  };
}
