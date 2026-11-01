import {
  Box,
  Link,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  type TypographyProps,
} from "@mui/material";
import type { SxProps, Theme } from "@mui/material/styles";
import type { ComponentProps } from "react";
import ReactMarkdown, {
  type Components,
  type ExtraProps,
  type Options,
  type UrlTransform,
} from "react-markdown";
import remarkGfm from "remark-gfm";

const MONOSPACE = 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace';

const prose: SxProps<Theme> = {
  lineHeight: 1.75,
  overflowWrap: "anywhere",
  "& > :last-child": { mb: 0 },
  "& * + :is(h2, h3, h4, h5, h6)": { mt: 3 },
  "& p": { mt: 0, mb: 1.5 },
  "& ul, & ol": { mt: 0, mb: 1.5, pl: 3 },
  "& li > p": { mb: 0.5 },
  "& li > ul, & li > ol": { mb: 0.5 },
  "& blockquote": {
    mx: 0,
    mt: 0,
    mb: 1.5,
    pl: 2,
    borderLeft: 3,
    borderColor: "divider",
    color: "text.secondary",
  },
  "& hr": { my: 3, border: 0, borderTop: 1, borderColor: "divider" },
  "& code": { fontFamily: MONOSPACE, fontSize: "0.875em" },
  "& :not(pre) > code": { px: 0.5, py: 0.25, borderRadius: 1, bgcolor: "action.hover" },
  "& pre": {
    mt: 0,
    mb: 1.5,
    p: 2,
    overflowX: "auto",
    overflowWrap: "normal",
    borderRadius: 1,
    bgcolor: "action.hover",
  },
  "& th, & td": { minWidth: "9rem", overflowWrap: "normal" },
  "& sup": { lineHeight: 0 },
  "& [data-footnotes]": { mt: 3, pt: 2, borderTop: 1, borderColor: "divider" },
};

type HtmlElement = NonNullable<ExtraProps["node"]>;

function visibleText(node: HtmlElement | HtmlElement["children"][number]): string {
  if (node.type === "text") return node.value;
  if (node.type !== "element") return "";
  if (node.tagName === "img") return String(node.properties.alt ?? "");
  return node.children.map(visibleText).join("");
}

// Not a browser fragment navigation: that leaves focus behind and adds a history entry per jump,
// so Back would walk the footnotes. Centring also clears the sticky meeting tabs.
function jumpTo(id: string) {
  const target = document.getElementById(id);
  if (!target) return;
  target.scrollIntoView({ block: "center" });
  if (target.tabIndex < 0) target.tabIndex = -1;
  target.focus({ preventScroll: true });
}

// A label may look like a URL, so only exact equality with the destination hides the host, and
// credentials never do: in https://google.com@evil.example the user name reads as the host.
function NoteLink({
  node,
  href,
  id,
  children,
  "aria-label": ariaLabel,
  "aria-describedby": ariaDescribedBy,
}: ComponentProps<"a"> & ExtraProps) {
  if (!href) return children;
  if (href.startsWith("#")) {
    return (
      <Link
        href={href}
        id={id}
        aria-label={ariaLabel}
        aria-describedby={ariaDescribedBy}
        onClick={(event) => {
          event.preventDefault();
          jumpTo(href.slice(1));
        }}
      >
        {children}
      </Link>
    );
  }
  const label = node ? visibleText(node).trim() : "";
  if (!label) return null;
  const { hostname, username, password } = new URL(href);
  const labelIsDestination = label === href && !username && !password;
  return (
    <Link href={href} target="_blank" rel="noopener noreferrer">
      {children}
      {!labelIsDestination && (
        <>
          {" "}
          <Box component="span" sx={{ color: "text.secondary" }}>
            ({hostname})
          </Box>
        </>
      )}
    </Link>
  );
}

const heading =
  (
    component: "h2" | "h3" | "h4" | "h5" | "h6",
    variant: TypographyProps["variant"],
  ): Components["h1"] =>
  ({ children }) => (
    <Typography component={component} variant={variant} sx={{ mb: 1 }}>
      {children}
    </Typography>
  );

// The page title is the h1 and a stored note holds only ## sections, because parse_notes strips
// its # title, so sections start at h2 while keeping a look that fits inside the page.
const components: Components = {
  h1: heading("h2", "h3"),
  h2: heading("h2", "h4"),
  h3: heading("h3", "subtitle1"),
  h4: heading("h4", "subtitle2"),
  h5: heading("h5", "subtitle2"),
  h6: heading("h6", "subtitle2"),
  a: NoteLink,
  // A remote image would make each reader's browser call a URL chosen by the note's author.
  img: ({ alt }) => alt,
  input: () => null,
  table: ({ children }) => (
    <TableContainer sx={{ mb: 1.5, border: 1, borderColor: "divider", borderRadius: 1 }}>
      <Table size="small">{children}</Table>
    </TableContainer>
  ),
  thead: ({ children }) => <TableHead>{children}</TableHead>,
  tbody: ({ children }) => <TableBody>{children}</TableBody>,
  tr: ({ children }) => <TableRow>{children}</TableRow>,
  th: ({ children, style }) => <TableCell style={style}>{children}</TableCell>,
  td: ({ children, style }) => <TableCell style={style}>{children}</TableCell>,
};

// Without //, a browser resolves http:settings against a page of the same scheme, so it is a
// relative link even though new URL() with no base reads it as the host "settings".
const ABSOLUTE_HTTP = /^https?:\/\//i;

const safeUrl: UrlTransform = (url, _key, node) => {
  if (url.startsWith("#")) {
    const { dataFootnoteRef, dataFootnoteBackref } = node.properties;
    return dataFootnoteRef === undefined && dataFootnoteBackref === undefined ? null : url;
  }
  const protocol = ABSOLUTE_HTTP.test(url) && URL.canParse(url) ? new URL(url).protocol : "";
  return protocol === "http:" || protocol === "https:" ? url : null;
};

const plugins = [remarkGfm];

// Hidden rather than dropped: each footnote reference points at this label through
// aria-describedby, which also reads hidden text.
const footnotes: Options["remarkRehypeOptions"] = {
  footnoteLabelTagName: "span",
  footnoteLabelProperties: { hidden: true },
};

export function Markdown({ children }: { children: string }) {
  return (
    <Typography component="div" sx={prose}>
      <ReactMarkdown
        remarkPlugins={plugins}
        remarkRehypeOptions={footnotes}
        components={components}
        urlTransform={safeUrl}
      >
        {children}
      </ReactMarkdown>
    </Typography>
  );
}
