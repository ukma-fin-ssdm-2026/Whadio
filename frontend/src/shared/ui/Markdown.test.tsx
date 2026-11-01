import { render, screen, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { Markdown } from "./Markdown";

const TABLE = `
| Owner | Due |
|:------|----:|
| Olena | Friday |
`;

const renderNotes = (notes: string) => render(<Markdown>{notes}</Markdown>);

describe("structure", () => {
  test("a stored note's sections continue straight from the page title", () => {
    // Act
    renderNotes("## Підсумок\n\nДомовились.\n\n## Рішення\n\n- Випустити в п'ятницю");

    // Assert
    expect(screen.getAllByRole("heading").map((heading) => heading.tagName)).toEqual(["H2", "H2"]);
  });

  test.for([
    ["# Title", 2],
    ["## Title", 2],
    ["### Title", 3],
    ["#### Title", 4],
    ["##### Title", 5],
    ["###### Title", 6],
  ] as const)("%s is a heading of level %i", ([notes, level]) => {
    // Act
    renderNotes(notes);

    // Assert
    expect(screen.getByRole("heading", { level })).toHaveTextContent("Title");
  });

  test.for([
    ["# Title", "h3"],
    ["## Title", "h4"],
    ["### Title", "subtitle1"],
    ["#### Title", "subtitle2"],
  ] as const)("%s looks like the %s variant whatever its level", ([notes, variant]) => {
    // Act
    renderNotes(notes);

    // Assert
    expect(screen.getByRole("heading")).toHaveClass(`MuiTypography-${variant}`);
  });

  test("a bullet list renders its items", () => {
    // Act
    renderNotes("- One\n- Two");

    // Assert
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual(["One", "Two"]);
  });

  test("a numbered list renders in order", () => {
    // Act
    const { container } = renderNotes("1. One\n2. Two");

    // Assert
    expect(container.querySelectorAll("ol > li")).toHaveLength(2);
  });

  test("a nested list stays nested", () => {
    // Act
    const { container } = renderNotes("- One\n  - Inner");

    // Assert
    expect(container.querySelector("ul ul li")).toHaveTextContent("Inner");
  });

  test.for(["- [ ] Olena ships", "- [x] Olena ships"])("%s has no checkbox", (notes) => {
    // Act
    const { container } = renderNotes(notes);

    // Assert
    expect(container.querySelector("input")).toBeNull();
  });

  test("a task item reads as a plain bullet", () => {
    // Act
    renderNotes("- [ ] Olena ships");

    // Assert
    expect(screen.getByRole("listitem")).toHaveTextContent(/^Olena ships$/);
  });

  test("a GFM table has column headers", () => {
    // Act
    renderNotes(TABLE);

    // Assert
    expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Owner",
      "Due",
    ]);
  });

  test("a GFM table has its cells", () => {
    // Act
    renderNotes(TABLE);

    // Assert
    expect(screen.getByRole("cell", { name: "Friday" })).toBeInTheDocument();
  });

  test("a table's column alignment reaches its cells", () => {
    // Act
    renderNotes(TABLE);

    // Assert
    expect(screen.getByRole("cell", { name: "Friday" })).toHaveStyle({ textAlign: "right" });
  });

  test("a wide table scrolls inside its own box", () => {
    // Act
    renderNotes(TABLE);

    // Assert
    expect(screen.getByRole("table").parentElement).toHaveStyle({ overflowX: "auto" });
  });

  test("a fenced block keeps its code", () => {
    // Act
    const { container } = renderNotes("```bash\nuv run task check\n```");

    // Assert
    expect(container.querySelector("pre code")).toHaveTextContent("uv run task check");
  });

  test("note text keeps its loose line spacing", () => {
    // Act
    const { container } = renderNotes("Domovylys");

    // Assert
    expect(container.firstElementChild).toHaveStyle({ lineHeight: "1.75" });
  });

  test("emphasis renders", () => {
    // Act
    renderNotes("Keep **this** one");

    // Assert
    expect(screen.getByText("this").tagName).toBe("STRONG");
  });
});

describe("raw HTML", () => {
  test.for([
    ["a script", "<script>globalThis.executedNotes = true</script>", "script"],
    ["an inline tag", "A <b>bold</b> word", "b"],
    ["an event handler", '<img src="x" onerror="globalThis.executedNotes = true">', "img"],
    ["a frame", '<iframe src="https://example.com"></iframe>', "iframe"],
    ["a form", '<form action="https://example.com"><input name="password"></form>', "form"],
  ] as const)("%s never reaches the DOM as an element", ([, notes, tag]) => {
    // Act
    const { container } = renderNotes(notes);

    // Assert
    expect(container.querySelector(tag)).toBeNull();
  });

  test("a script is shown as text", () => {
    // Act
    renderNotes("<script>alert(1)</script>");

    // Assert
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
  });

  test("a script never runs", () => {
    // Act
    renderNotes("<script>globalThis.executedNotes = true</script>");

    // Assert
    expect(Object.hasOwn(globalThis, "executedNotes")).toBe(false);
  });
});

describe("links", () => {
  test.for(["https://example.com/brief", "http://example.com/brief", "HTTPS://example.com/brief"])(
    "%s is a link",
    (url) => {
      // Act
      renderNotes(`[Brief](${url})`);

      // Assert
      expect(screen.getByRole("link", { name: "Brief" })).toHaveAttribute("href", url);
    },
  );

  test("a link opens in a new tab", () => {
    // Act
    renderNotes("[Brief](https://example.com)");

    // Assert
    expect(screen.getByRole("link", { name: "Brief" })).toHaveAttribute("target", "_blank");
  });

  test("a link leaks neither the opener nor the referrer", () => {
    // Act
    renderNotes("[Brief](https://example.com)");

    // Assert
    expect(screen.getByRole("link", { name: "Brief" })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
  });

  test("a bare address becomes a link", () => {
    // Act
    renderNotes("See https://example.com/brief today");

    // Assert
    expect(screen.getByRole("link")).toHaveAttribute("href", "https://example.com/brief");
  });

  test.for([
    ["javascript", "[Brief](javascript:alert(1))"],
    ["mixed-case javascript", "[Brief](JaVaScRiPt:alert(1))"],
    ["encoded javascript", "[Brief](java&#10;script:alert(1))"],
    ["data", "[Brief](data:text/html;base64,PHNjcmlwdD4=)"],
    ["vbscript", "[Brief](vbscript:msgbox(1))"],
    ["mailto", "[Brief](mailto:team@example.com)"],
    ["absolute path", "[Brief](/settings)"],
    ["relative path", "[Brief](../settings)"],
    ["fragment", "[Brief](#top)"],
    ["protocol-relative", "[Brief](//example.com/brief)"],
    ["reference", "[Brief][ref]\n\n[ref]: javascript:alert(1)"],
  ] as const)("a %s link is plain text", ([, notes]) => {
    // Act
    renderNotes(notes);

    // Assert
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  test("a refused link keeps its words", () => {
    // Act
    renderNotes("[Brief](javascript:alert(1))");

    // Assert
    expect(screen.getByText("Brief")).toBeInTheDocument();
  });

  test("a bare email address is plain text", () => {
    // Act
    renderNotes("Write to team@example.com");

    // Assert
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});

describe("images", () => {
  test("a remote image loads nothing", () => {
    // Act
    const { container } = renderNotes("![Whiteboard](https://example.com/board.png)");

    // Assert
    expect(container.querySelector("img")).toBeNull();
  });

  test("a remote image shows its alt text", () => {
    // Act
    renderNotes("![Whiteboard](https://example.com/board.png)");

    // Assert
    expect(screen.getByText("Whiteboard")).toBeInTheDocument();
  });

  test("an image without alt text leaves nothing", () => {
    // Act
    const { container } = renderNotes("![](https://example.com/board.png)");

    // Assert
    expect(container).toHaveTextContent("");
  });

  test("a linked image stays a link with its alt text", () => {
    // Act
    renderNotes("[![Board](https://example.com/board.png)](https://example.com)");

    // Assert
    expect(within(screen.getByRole("link")).getByText("Board")).toBeInTheDocument();
  });
});
