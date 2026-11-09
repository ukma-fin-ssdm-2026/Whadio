const DATABASE = "whadio-recovery";
const STORE = "recordings";

function open() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => {
      const recordings = request.result.createObjectStore(STORE, { keyPath: "id" });
      recordings.createIndex("metadata", ["owner.server", "owner.userId", "startedAt"]);
    };
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
  });
}

async function transaction(mode, operation) {
  const database = await open();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(STORE, mode, { durability: "strict" });
    let result;
    transaction.oncomplete = () => {
      database.close();
      resolve(result);
    };
    transaction.onabort = () => {
      database.close();
      reject(transaction.error ?? new Error("Recovery storage transaction aborted."));
    };
    operation(transaction.objectStore(STORE), (value) => {
      result = value;
    });
  });
}

export const recoveryStore = {
  put: (recording) => transaction("readwrite", (store) => store.put(recording)),
  remove: (id) => transaction("readwrite", (store) => store.delete(id)),
  get: (id) =>
    transaction("readonly", (store, done) => {
      store.get(id).onsuccess = (event) => done(event.target.result);
    }),
  list: () =>
    transaction("readonly", (store, done) => {
      const recordings = [];
      store.index("metadata").openKeyCursor().onsuccess = (event) => {
        const cursor = event.target.result;
        if (cursor) {
          const [server, userId, startedAt] = cursor.key;
          recordings.push({ id: cursor.primaryKey, owner: { server, userId }, startedAt });
          cursor.continue();
        } else {
          done(recordings);
        }
      };
    }),
};
