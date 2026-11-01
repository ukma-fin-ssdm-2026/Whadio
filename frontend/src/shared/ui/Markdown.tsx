import {
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
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
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
};

type HtmlElement = NonNullable<ExtraProps["node"]>;

function visibleText(node: HtmlElement | HtmlElement["children"][number]): string {
  if (node.type === "text") return node.value;
  if (node.type !== "element") return "";
  if (node.tagName === "img") return String(node.properties.alt ?? "");
  return node.children.map(visibleText).join("");
}

function NoteLink({ node, href, children }: ComponentProps<"a"> & ExtraProps) {
  if (!href) return children;
  const label = node ? visibleText(node).trim() : "";
  if (!label) return null;
  return (
    <Link href={href} target="_blank" rel="noopener noreferrer">
      {children}
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

function httpUrlOnly(url: string): string | null {
  const protocol = URL.canParse(url) ? new URL(url).protocol : "";
  return protocol === "http:" || protocol === "https:" ? url : null;
}

const plugins = [remarkGfm];

export function Markdown({ children }: { children: string }) {
  return (
    <Typography component="div" sx={prose}>
      <ReactMarkdown remarkPlugins={plugins} components={components} urlTransform={httpUrlOnly}>
        {children}
      </ReactMarkdown>
    </Typography>
  );
}
