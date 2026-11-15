function ownedBy(recording, owner) {
  return (
    owner && recording?.owner?.server === owner.server && recording?.owner?.userId === owner.userId
  );
}

async function requireOwner(recording, currentOwner) {
  if (!ownedBy(recording, await currentOwner())) {
    throw new Error("Sign in to the original account to recover this recording.");
  }
}

export class RecordingRecovery {
  constructor(store, download, changed) {
    this.store = store;
    this.download = download;
    this.changed = changed;
    this.temporary = new Map();
    this.busy = new Set();
  }

  async list(currentOwner) {
    let saved;
    try {
      saved = await this.store.list();
    } catch (failure) {
      if (this.temporary.size === 0) {
        throw failure;
      }
      saved = [];
    }
    const recordings = new Map(saved.map((item) => [item.id, item]));
    for (const { id, startedAt, owner } of this.temporary.values()) {
      recordings.set(id, { id, startedAt, owner, temporary: true });
    }
    const owner = await currentOwner?.();
    const visible = [...recordings.values()]
      .filter((item) => ownedBy(item, owner))
      .map(({ owner: _owner, ...item }) => ({ ...item, busy: this.busy.has(item.id) }));
    return { recordings: visible, hasLockedRecordings: visible.length < recordings.size };
  }

  async retain(recording, authorizeInitialSave) {
    await this.withLock(recording.id, async () => {
      try {
        await this.store.put(recording);
      } catch {
        this.temporary.set(recording.id, recording);
        console.warn("Whadio could not persist a recording for recovery.");
      }
      if (authorizeInitialSave) {
        await this.save(recording, authorizeInitialSave);
      }
    });
  }

  async retry(id, currentOwner) {
    await this.withLock(id, async () => {
      const recording = this.temporary.get(id) ?? (await this.store.get(id));
      if (!recording) {
        throw new Error("This recording is no longer available.");
      }
      await this.save(recording, () => requireOwner(recording, currentOwner));
    });
  }

  async discard(id, currentOwner) {
    await this.withLock(id, async () => {
      const recording = this.temporary.get(id) ?? (await this.store.get(id));
      await this.remove(id, () => requireOwner(recording, currentOwner));
    });
  }

  async save(recording, authorize) {
    await authorize();
    const source = this.temporary.has(recording.id)
      ? { slices: recording.slices }
      : { id: recording.id };
    await this.download(recording.startedAt, source, authorize);
    await this.remove(recording.id);
  }

  async remove(id, authorize) {
    if (this.temporary.has(id)) {
      await authorize?.();
      this.temporary.delete(id);
    } else {
      await this.store.remove(id, authorize);
    }
  }

  async withLock(id, operation) {
    if (this.busy.has(id)) {
      throw new Error("This recording is already being saved.");
    }
    this.busy.add(id);
    try {
      await operation();
    } finally {
      this.busy.delete(id);
      await this.changed();
    }
  }
}
