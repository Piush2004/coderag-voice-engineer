"""Regression test for a real bug found during manual testing: FastAPI runs sync
endpoints in a threadpool, and concurrent unguarded calls to get_chroma_collection()
raced to construct two chromadb.PersistentClient instances against the same on-disk
path, crashing chromadb's Rust bindings with
'RustBindingsAPI' object has no attribute 'bindings'.
Fixed with a lock around the lazy singleton in packages/rag/store.py.
"""
import threading

import packages.rag.store as store


def test_concurrent_first_access_does_not_crash(monkeypatch):
    # Force a cold singleton so every thread races the same lazy-init path.
    monkeypatch.setattr(store, "_chroma_collection", None)
    monkeypatch.setattr(store, "_chroma_client", None)

    errors = []
    collections = []

    def worker():
        try:
            collections.append(store.get_chroma_collection())
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent init raised: {errors}"
    assert len(collections) == 8
    assert len({id(c) for c in collections}) == 1  # all threads got the same singleton
