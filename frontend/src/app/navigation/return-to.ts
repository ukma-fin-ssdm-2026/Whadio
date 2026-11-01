const HOME = "/";

// Never navigated to: it only tells a path of this app from anything a browser would resolve to
// another origin, tabs, backslashes and all.
const PROBE_ORIGIN = "https://whadio.invalid";

export function safeReturnPath(target: string | undefined): string {
  if (!target?.startsWith("/") || !URL.canParse(target, PROBE_ORIGIN)) return HOME;
  const { origin, pathname, search } = new URL(target, PROBE_ORIGIN);
  return origin === PROBE_ORIGIN ? pathname + search : HOME;
}

interface PageLocation {
  pathname: string;
  searchStr: string;
}

// Leaves out the hash: an emailed link carries its token there, and this value lands in a URL.
export function returnSearch({ pathname, searchStr }: PageLocation): { redirect?: string } {
  return pathname === HOME && !searchStr ? {} : { redirect: pathname + searchStr };
}
