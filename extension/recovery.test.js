import { RecordingRecovery } from "./recovery.js";

const owner = { server: "https://whadio.example", userId: "original" };
const recording = { id: "one", startedAt: 1, slices: ["YWI="], owner };

function setup() {
  const saved = new Map();
  const store = {
    put: vi.fn(async (value) => saved.set(value.id, structuredClone(value))),
    get: vi.fn(async (id) => saved.get(id)),
    remove: vi.fn(async (id) => saved.delete(id)),
    list: vi.fn(async () =>
      [...saved.values()].map(({ id, startedAt, owner }) => ({ id, startedAt, owner })),
    ),
  };
  const download = vi.fn(async () => {});
  const changed = vi.fn(async () => {});
  return { store, download, changed, recovery: new RecordingRecovery(store, download, changed) };
}

afterEach(() => vi.restoreAllMocks());

test("a failed retry retains the saved copy for the next attempt", async () => {
  // Arrange
  const { recovery, download } = setup();
  await recovery.retain(recording);
  download.mockRejectedValue(new Error("Disk unavailable"));

  // Act
  await expect(recovery.retry(recording.id, owner)).rejects.toThrow("Disk unavailable");

  // Assert
  expect(await recovery.list()).toEqual([{ id: "one", startedAt: 1, busy: false }]);
});

test("a pending backup blocks discard and starts downloading only after commit", async () => {
  // Arrange
  const { recovery, store, download } = setup();
  const { promise: commit, resolve: allowCommit } = Promise.withResolvers();
  const { promise: saving, reject: failSave } = Promise.withResolvers();
  const put = store.put.getMockImplementation();
  store.put.mockImplementation(async (value) => {
    await commit;
    await put(value);
  });
  download.mockReturnValueOnce(saving);
  const pending = recovery.retain(recording, async () => owner).catch(() => {});

  // Act
  const hidden = await recovery.list(owner);
  const earlyDiscard = await recovery
    .discard(recording.id, owner)
    .catch((failure) => failure.message);
  const downloadsBeforeCommit = download.mock.calls.length;
  allowCommit();
  await vi.waitFor(() => expect(download).toHaveBeenCalledOnce());
  const discardDuringSave = await recovery
    .discard(recording.id, owner)
    .catch((failure) => failure.message);
  failSave(new Error("Disk unavailable"));
  await pending;
  await recovery.discard(recording.id, owner);
  const restarted = new RecordingRecovery(store, download, async () => {});

  // Assert
  expect({
    hidden,
    earlyDiscard,
    downloadsBeforeCommit,
    discardDuringSave,
    afterRestart: await restarted.list(owner),
  }).toEqual({
    hidden: [],
    earlyDiscard: "This recording is already being saved.",
    downloadsBeforeCommit: 0,
    discardDuringSave: "This recording is already being saved.",
    afterRestart: [],
  });
});

test("retaining a recording waits for its backup write", async () => {
  // Arrange
  const { recovery, store } = setup();
  let commit;
  store.put.mockImplementation(
    () =>
      new Promise((resolve) => {
        commit = resolve;
      }),
  );
  let retained = false;

  // Act
  const pending = recovery.retain(recording).then(() => {
    retained = true;
  });
  await Promise.resolve();
  const beforeCommit = retained;
  commit();
  await pending;

  // Assert
  expect([beforeCommit, retained]).toEqual([false, true]);
});

test("a restart exposes only metadata and can recover the complete stored recording", async () => {
  // Arrange
  const { recovery, store, download, changed } = setup();
  await recovery.retain(recording);
  const restarted = new RecordingRecovery(store, download, changed);

  // Act
  const listed = await restarted.list();
  await restarted.retry(recording.id, owner);

  // Assert
  expect({ listed, audio: download.mock.calls, remaining: await restarted.list() }).toEqual({
    listed: [{ id: "one", startedAt: 1, busy: false }],
    audio: [[1, ["YWI="]]],
    remaining: [],
  });
});

test("saving one recording leaves the other pending recording available", async () => {
  // Arrange
  const { recovery } = setup();
  await recovery.retain(recording);
  await recovery.retain({ ...recording, id: "two" });

  // Act
  await recovery.retry("one", owner);

  // Assert
  expect(await recovery.list()).toEqual([{ id: "two", startedAt: 1, busy: false }]);
});

test("concurrent retries cannot download the same recording twice or discard it while saving", async () => {
  // Arrange
  const { recovery, download } = setup();
  await recovery.retain(recording);
  let finish;
  download.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const first = recovery.retry(recording.id, owner);
  await Promise.resolve();

  // Act
  await expect(recovery.retry(recording.id, owner)).rejects.toThrow("already being saved");
  await expect(recovery.discard(recording.id, owner)).rejects.toThrow("already being saved");
  finish();
  await first;

  // Assert
  expect(download).toHaveBeenCalledOnce();
});

test("a storage failure exposes an explicitly temporary copy instead of losing it silently", async () => {
  // Arrange
  const { recovery, store } = setup();
  vi.spyOn(console, "warn").mockImplementation(() => {});
  store.put.mockRejectedValue(new Error("Quota exceeded"));
  store.list.mockRejectedValue(new Error("Database unavailable"));

  // Act
  await recovery.retain(recording);

  // Assert
  expect(await recovery.list()).toEqual([
    { id: "one", startedAt: 1, temporary: true, busy: false },
  ]);
});

test("a failed deletion keeps the backup available rather than claiming it was discarded", async () => {
  // Arrange
  const { recovery, store } = setup();
  await recovery.retain(recording);
  store.remove.mockRejectedValue(new Error("Database unavailable"));

  // Act
  await expect(recovery.discard(recording.id, owner)).rejects.toThrow("Database unavailable");

  // Assert
  expect(await recovery.list()).toHaveLength(1);
});

test.for([null, { ...owner, userId: "other" }, { ...owner, server: "https://other.example" }])(
  "refuses a different account or server and an absent session: %j",
  async (stranger) => {
    // Arrange
    const { recovery, download } = setup();
    await recovery.retain(recording);

    // Act
    const listed = await recovery.list(stranger);
    await expect(recovery.retry(recording.id, stranger)).rejects.toThrow("original account");
    await expect(recovery.discard(recording.id, stranger)).rejects.toThrow("original account");

    // Assert
    expect({
      listed,
      downloads: download.mock.calls.length,
      retained: await recovery.list(owner),
    }).toEqual({
      listed: [],
      downloads: 0,
      retained: [{ id: "one", startedAt: 1, busy: false }],
    });
  },
);
