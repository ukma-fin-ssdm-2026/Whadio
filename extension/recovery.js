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
        await this.save(recording, currentOwner);
      }
    });
  }

  async retry(id, currentOwner) {
    await this.withLock(id, async () => {
      const recording = this.temporary.get(id) ?? (await this.store.get(id));
      if (!recording) {
        throw new Error("This recording is no longer available.");
      }
      await this.save(recording, currentOwner);
    });
  }

  async discard(id, currentOwner) {
    await this.withLock(id, async () => {
      const recording = this.temporary.get(id) ?? (await this.store.get(id));
      await this.remove(id, () => requireOwner(recording, currentOwner));
    });
  }

  async save(recording, currentOwner) {
    const authorize = () => requireOwner(recording, currentOwner);
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
