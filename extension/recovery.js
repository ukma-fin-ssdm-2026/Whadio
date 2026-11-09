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

  async retain(recording) {
    this.temporary.set(recording.id, recording);
    try {
      await this.store.put(recording);
      this.temporary.delete(recording.id);
    } catch {
      console.warn("Whadio could not persist a recording for recovery.");
    }
    await this.changed();
  }

  async retry(id, owner) {
    if (this.busy.has(id)) {
      throw new Error("This recording is already being saved.");
    }
    this.busy.add(id);
    try {
      const recording = this.temporary.get(id) ?? (await this.store.get(id));
      if (!recording) {
        throw new Error("This recording is no longer available.");
      }
      if (!ownedBy(recording, owner)) {
        throw new Error("Sign in to the original account to recover this recording.");
      }
      await this.download(recording.startedAt, recording.slices);
      if (!this.temporary.has(id)) {
        await this.store.remove(id);
      }
      this.temporary.delete(id);
    } finally {
      this.busy.delete(id);
      await this.changed();
    }
  }

  async discard(id, owner) {
    if (this.busy.has(id)) {
      throw new Error("Wait for the download to finish before discarding this recording.");
    }
    this.busy.add(id);
    try {
      const recording = this.temporary.get(id) ?? (await this.store.get(id));
      if (!ownedBy(recording, owner)) {
        throw new Error("Sign in to the original account to discard this recording.");
      }
      if (!this.temporary.has(id)) {
        await this.store.remove(id);
      }
      this.temporary.delete(id);
    } finally {
      this.busy.delete(id);
      await this.changed();
    }
  }
}
