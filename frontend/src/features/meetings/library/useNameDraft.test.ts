import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useNameDraft } from "./useNameDraft";

const SETTLED_MS = 300;

function renderDraft(name = "") {
  const onName = vi.fn();
  const rendered = renderHook((current: string) => useNameDraft(current, onName), {
    initialProps: name,
  });
  const type = (value: string) => act(() => rendered.result.current.type(value));
  return { ...rendered, onName, type };
}

const settle = () => act(() => vi.advanceTimersByTime(SETTLED_MS));

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

test("shows what was typed at once", () => {
  // Arrange
  const { result, type } = renderDraft();

  // Act
  type("ret");

  // Assert
  expect(result.current.draft).toBe("ret");
});

test("reports nothing before typing settles", () => {
  // Arrange
  const { onName, type } = renderDraft();

  // Act
  type("ret");
  act(() => vi.advanceTimersByTime(SETTLED_MS - 1));

  // Assert
  expect(onName).not.toHaveBeenCalled();
});

test("reports a burst of typing once, trimmed", () => {
  // Arrange
  const { onName, type } = renderDraft();

  // Act
  type("re");
  type(" retro ");
  settle();

  // Assert
  expect(onName.mock.calls).toEqual([["retro"]]);
});

test("its own report leaves newer typing alone", () => {
  // Arrange
  const { result, rerender, type } = renderDraft();
  type("re");
  settle();
  type("retro");

  // Act
  rerender("re");

  // Assert
  expect(result.current.draft).toBe("retro");
});

test("a name changed elsewhere replaces the draft", () => {
  // Arrange
  const { result, rerender } = renderDraft("retro");

  // Act
  rerender("");

  // Assert
  expect(result.current.draft).toBe("");
});

test("a name changed elsewhere cancels the pending report", () => {
  // Arrange
  const { onName, rerender, type } = renderDraft("retro");
  type("retros");

  // Act
  rerender("");
  settle();

  // Assert
  expect(onName).not.toHaveBeenCalled();
});

test("leaving the page cancels the pending report", () => {
  // Arrange
  const { onName, type, unmount } = renderDraft();
  type("retro");

  // Act
  unmount();
  settle();

  // Assert
  expect(onName).not.toHaveBeenCalled();
});
