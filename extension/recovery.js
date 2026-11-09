function ownedBy(recording, owner) {
  return (
    owner && recording?.owner?.server === owner.server && recording?.owner?.userId === owner.userId
  );
}

export class RecordingRecovery {
  constructor(store, download, changed) {
    this.store = store;
    this.download = download;
    this.changed = changed;
    this.temporary = new Map();
    this.busy = new Set();
  }

  async list(owner) {
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
    return [...recordings.values()]
      .filter((item) => owner === undefined || ownedBy(item, owner))
      .map(({ owner: _owner, ...item }) => ({ ...item, busy: this.busy.has(item.id) }));
  }

  async retain(recording, currentOwner) {
    await this.withLock(recording.id, async () => {
      try {
        await this.store.put(recording);
      } catch {
        this.temporary.set(recording.id, recording);
        console.warn("Whadio could not persist a recording for recovery.");
      }
      if (currentOwner) {
        await this.save(recording, await currentOwner());
      }
    });
  }

  async retry(id, owner) {
    await this.withLock(id, async () => {
      const recording = this.temporary.get(id) ?? (await this.store.get(id));
      if (!recording) {
        throw new Error("This recording is no longer available.");
      }
      await this.save(recording, owner);
    });
  }

  async discard(id, owner) {
    await this.withLock(id, async () => {
      const recording = this.temporary.get(id) ?? (await this.store.get(id));
      if (!ownedBy(recording, owner)) {
        throw new Error("Sign in to the original account to discard this recording.");
      }
      await this.remove(id);
    });
  }

  async save(recording, owner) {
    if (!ownedBy(recording, owner)) {
      throw new Error("Sign in to the original account to recover this recording.");
    }
    await this.download(recording.startedAt, recording.slices);
    await this.remove(recording.id);
  }

  async remove(id) {
    if (!this.temporary.delete(id)) {
      await this.store.remove(id);
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
