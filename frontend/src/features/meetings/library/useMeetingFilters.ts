import { useState } from "react";
import { useDebouncedValue } from "@/shared/hooks/useDebouncedValue";
import type { StateFilter } from "../model";

const NAME_DEBOUNCE_MS = 300;

export function useMeetingFilters() {
  const [query, setQuery] = useState("");
  const [stateFilter, setStateFilter] = useState<StateFilter>("all");
  const name = useDebouncedValue(query.trim(), NAME_DEBOUNCE_MS);
  return {
    name,
    filters: { query, stateFilter, onQuery: setQuery, onStateFilter: setStateFilter },
  };
}
