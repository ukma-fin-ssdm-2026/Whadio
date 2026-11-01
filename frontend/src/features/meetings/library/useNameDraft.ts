import { useEffect, useRef, useState } from "react";

const NAME_DEBOUNCE_MS = 300;

// The typed text outruns `name`, which only moves when the debounce reports it, so another
// navigation changing `name` is told apart from this hook's own report.
export function useNameDraft(name: string, onName: (name: string) => void) {
  const [draft, setDraft] = useState(name);
  const reported = useRef(name);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => () => clearTimeout(timer.current), []);

  useEffect(() => {
    if (name === reported.current) return;
    reported.current = name;
    clearTimeout(timer.current);
    setDraft(name);
  }, [name]);

  const type = (value: string) => {
    setDraft(value);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      reported.current = value.trim();
      onName(value.trim());
    }, NAME_DEBOUNCE_MS);
  };

  return { draft, type };
}
