import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useDebouncedValue } from "./useDebouncedValue";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function renderDebounced() {
  return renderHook(({ value }) => useDebouncedValue(value, 300), {
    initialProps: { value: "first" },
  });
}

test("keeps the old value until the delay passes", () => {
  // Arrange
  const { result, rerender } = renderDebounced();

  // Act
  rerender({ value: "second" });
  act(() => vi.advanceTimersByTime(299));

  // Assert
  expect(result.current).toBe("first");
});

test("takes the new value once the delay passes", () => {
  // Arrange
  const { result, rerender } = renderDebounced();

  // Act
  rerender({ value: "second" });
  act(() => vi.advanceTimersByTime(300));

  // Assert
  expect(result.current).toBe("second");
});

test("a newer value restarts the delay", () => {
  // Arrange
  const { result, rerender } = renderDebounced();
  rerender({ value: "second" });
  act(() => vi.advanceTimersByTime(200));

  // Act
  rerender({ value: "third" });
  act(() => vi.advanceTimersByTime(200));

  // Assert
  expect(result.current).toBe("first");
});
