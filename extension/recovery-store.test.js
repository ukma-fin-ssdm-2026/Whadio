import { recoveryStore } from "./recovery-store.js";

function fakeDatabase() {
  const store = { put: vi.fn(), delete: vi.fn() };
  const database = {
    close: vi.fn(),
    transaction: vi.fn(() => {
      const transaction = { objectStore: () => store };
      queueMicrotask(() => transaction.oncomplete());
      return transaction;
    }),
  };
  vi.stubGlobal("indexedDB", {
    open: () => {
      const request = { result: database };
      queueMicrotask(() => request.onsuccess());
      return request;
    },
  });
  return { database, store };
}

afterEach(() => vi.unstubAllGlobals());

test("commits a recovery backup in a strict-durability transaction", async () => {
  // Arrange
  const { database, store } = fakeDatabase();
  const recording = { id: "saved", slices: ["YWI="] };

  // Act
  await recoveryStore.put(recording);

  // Assert
  expect({ transactions: database.transaction.mock.calls, writes: store.put.mock.calls }).toEqual({
    transactions: [["recordings", "readwrite", { durability: "strict" }]],
    writes: [[recording]],
  });
});

test("a refused authorization prevents the deletion transaction from starting", async () => {
  // Arrange
  const { database, store } = fakeDatabase();
  const failure = new Error("Sign-in expired");
  const authorize = async () => {
    throw failure;
  };

  // Act
  const error = await recoveryStore.remove("saved", authorize).catch((reason) => reason);

  // Assert
  expect({
    error,
    transactions: database.transaction.mock.calls,
    deletions: store.delete.mock.calls,
    closed: database.close.mock.calls.length,
  }).toEqual({ error: failure, transactions: [], deletions: [], closed: 1 });
});
