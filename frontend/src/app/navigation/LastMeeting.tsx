import { useParams, useRouter } from "@tanstack/react-router";
import { createContext, type ReactNode, useContext, useEffect, useRef, useState } from "react";

const LastMeetingContext = createContext("");

export const useLastMeetingId = () => useContext(LastMeetingContext);

// A list marks the meeting that history stepped back from, until a new navigation moves on.
export function LastMeetingProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const openId = useParams({ strict: false }).meetingId ?? "";
  const shownId = useRef(openId);
  const [lastId, setLastId] = useState("");

  useEffect(() => {
    shownId.current = openId;
  }, [openId]);

  useEffect(
    () =>
      router.history.subscribe(({ action }) => {
        if (action.type === "PUSH") setLastId("");
        else if (action.type !== "REPLACE") setLastId(shownId.current);
      }),
    [router],
  );

  return <LastMeetingContext.Provider value={lastId}>{children}</LastMeetingContext.Provider>;
}
