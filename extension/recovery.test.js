import { RecordingRecovery } from "./recovery.js";

const owner = { server: "https://whadio.example", userId: "original" };
const recording = { id: "one", startedAt: 1, slices: ["YWI="], owner };
const currentOwner = async () => owner;

async function visibleRecordings(recovery) {
  return (await recovery.list(currentOwner)).recordings;
}

function setup() {
  const saved = new Map();
  const store = {
    put: vi.fn(async (value) => saved.set(value.id, structuredClone(value))),
    get: vi.fn(async (id) => saved.get(id)),
    remove: vi.fn(async (id, authorize) => {
      await authorize?.();
      saved.delete(id);
    }),
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
  const error = await recovery
    .retry(recording.id, currentOwner)
    .catch((failure) => failure.message);

  // Assert
  expect({ error, remaining: await visibleRecordings(recovery) }).toEqual({
    error: "Disk unavailable",
    remaining: [{ id: "one", startedAt: 1, busy: false }],
  });
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
  const pending = recovery.retain(recording, async () => {}).catch(() => {});

  // Act
  const hidden = await visibleRecordings(recovery);
  const earlyDiscard = await recovery
    .discard(recording.id, currentOwner)
    .catch((failure) => failure.message);
  const downloadsBeforeCommit = download.mock.calls.length;
  allowCommit();
  await vi.waitFor(() => expect(download).toHaveBeenCalledOnce());
  const discardDuringSave = await recovery
    .discard(recording.id, currentOwner)
    .catch((failure) => failure.message);
  failSave(new Error("Disk unavailable"));
  await pending;
  await recovery.discard(recording.id, currentOwner);
  const restarted = new RecordingRecovery(store, download, async () => {});

  // Assert
  expect({
    hidden,
    earlyDiscard,
    downloadsBeforeCommit,
    discardDuringSave,
    afterRestart: await visibleRecordings(restarted),
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
  const listed = await visibleRecordings(restarted);
  await restarted.retry(recording.id, currentOwner);

  // Assert
  expect({
    listed,
    audio: download.mock.calls,
    remaining: await visibleRecordings(restarted),
  }).toEqual({
    listed: [{ id: "one", startedAt: 1, busy: false }],
    audio: [[1, { id: "one" }, expect.any(Function)]],
    remaining: [],
  });
});

test("saving one recording leaves the other pending recording available", async () => {
  // Arrange
  const { recovery } = setup();
  await recovery.retain(recording);
  await recovery.retain({ ...recording, id: "two" });

  // Act
  await recovery.retry("one", currentOwner);

  // Assert
  expect(await visibleRecordings(recovery)).toEqual([{ id: "two", startedAt: 1, busy: false }]);
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
  const first = recovery.retry(recording.id, currentOwner);
  await Promise.resolve();

  // Act
  const retry = await recovery
    .retry(recording.id, currentOwner)
    .catch((failure) => failure.message);
  const discard = await recovery
    .discard(recording.id, currentOwner)
    .catch((failure) => failure.message);
  finish();
  await first;

  // Assert
  expect({ retry, discard, downloads: download.mock.calls.length }).toEqual({
    retry: "This recording is already being saved.",
    discard: "This recording is already being saved.",
    downloads: 1,
  });
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
  expect(await visibleRecordings(recovery)).toEqual([
    { id: "one", startedAt: 1, temporary: true, busy: false },
  ]);
});

test("a failed deletion keeps the backup available rather than claiming it was discarded", async () => {
  // Arrange
  const { recovery, store } = setup();
  await recovery.retain(recording);
  store.remove.mockRejectedValue(new Error("Database unavailable"));

  // Act
  const error = await recovery
    .discard(recording.id, currentOwner)
    .catch((failure) => failure.message);

  // Assert
  expect({ error, remaining: await visibleRecordings(recovery) }).toEqual({
    error: "Database unavailable",
    remaining: [{ id: "one", startedAt: 1, busy: false }],
  });
});

test.for([null, { ...owner, userId: "other" }, { ...owner, server: "https://other.example" }])(
  "refuses a different account or server and an absent session: %j",
  async (stranger) => {
    // Arrange
    const { recovery, download } = setup();
    await recovery.retain(recording);
    const otherOwner = async () => stranger;

    // Act
    const listed = await recovery.list(otherOwner);
    const retry = await recovery
      .retry(recording.id, otherOwner)
      .catch((failure) => failure.message);
    const discard = await recovery
      .discard(recording.id, otherOwner)
      .catch((failure) => failure.message);

    // Assert
    expect({
      listed,
      retry,
      discard,
      downloads: download.mock.calls.length,
      retained: await visibleRecordings(recovery),
    }).toEqual({
      listed: { recordings: [], hasLockedRecordings: true },
      retry: "Sign in to the original account to recover this recording.",
      discard: "Sign in to the original account to recover this recording.",
      downloads: 0,
      retained: [{ id: "one", startedAt: 1, busy: false }],
    });
  },
);
