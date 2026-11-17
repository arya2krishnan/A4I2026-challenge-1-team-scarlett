"""Document storage behind one small interface, so the approval logic in store.py is written once.

    repo.run(fn)              run fn(tx) in a transaction; tx.get(collection, id) / tx.set(collection, id, doc)
    repo.find(collection, s)  every document whose `status` is s

SqliteRepo     local runs and tests (.data/dispatches.db). BEGIN IMMEDIATE serialises writers.
FirestoreRepo  Cloud Run. Instances share it, and Firestore transactions retry fn on contention, so two
               dispatchers approving the same proposal cannot both succeed. Reads happen before writes in fn,
               as Firestore requires.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Protocol, TypeVar

T = TypeVar("T")


class Tx(Protocol):
    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None: ...
    def set(self, collection: str, doc_id: str, doc: dict[str, Any]) -> None: ...


class Repo(Protocol):
    def run(self, fn: Callable[[Tx], T]) -> T: ...
    def find(self, collection: str, status: str) -> list[dict[str, Any]]: ...


# ---- SQLite ------------------------------------------------------------------------------------------------------
_SCHEMA = """CREATE TABLE IF NOT EXISTS docs (
  collection TEXT NOT NULL, id TEXT NOT NULL, status TEXT, body TEXT NOT NULL, PRIMARY KEY (collection, id));
CREATE INDEX IF NOT EXISTS docs_status ON docs (collection, status);"""


class _SqliteTx:
    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        row = self.con.execute("SELECT body FROM docs WHERE collection = ? AND id = ?", (collection, doc_id)).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, collection: str, doc_id: str, doc: dict[str, Any]) -> None:
        self.con.execute("INSERT OR REPLACE INTO docs VALUES (?,?,?,?)",
                         (collection, doc_id, doc.get("status"), json.dumps(doc)))


class SqliteRepo:
    def __init__(self, path: str | Path) -> None:
        self.path, self._ready = Path(path), False

    def _connect(self) -> sqlite3.Connection:
        if not self._ready:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        if not self._ready:
            con.executescript(_SCHEMA)
            self._ready = True
        return con

    def run(self, fn: Callable[[Tx], T]) -> T:
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                out = fn(_SqliteTx(con))
            except BaseException:
                con.execute("ROLLBACK")
                raise
            con.execute("COMMIT")
            return out
        finally:
            con.close()

    def find(self, collection: str, status: str) -> list[dict[str, Any]]:
        con = self._connect()
        try:
            rows = con.execute("SELECT body FROM docs WHERE collection = ? AND status = ?", (collection, status))
            return [json.loads(r[0]) for r in rows]
        finally:
            con.close()


# ---- Firestore ---------------------------------------------------------------------------------------------------
class _FirestoreTx:
    def __init__(self, db: Any, transaction: Any) -> None:
        self.db, self.t = db, transaction

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        snap = self.db.collection(collection).document(doc_id).get(transaction=self.t)
        return snap.to_dict() if snap.exists else None

    def set(self, collection: str, doc_id: str, doc: dict[str, Any]) -> None:
        self.t.set(self.db.collection(collection).document(doc_id), doc)


class FirestoreRepo:
    def __init__(self, project: str | None, database: str) -> None:
        from google.cloud import firestore   # imported here so local runs and tests do not need the package

        self._fs = firestore
        self.db = firestore.Client(project=project or None, database=database)

    def run(self, fn: Callable[[Tx], T]) -> T:
        @self._fs.transactional
        def _go(transaction: Any) -> T:
            return fn(_FirestoreTx(self.db, transaction))
        return _go(self.db.transaction())

    def find(self, collection: str, status: str) -> list[dict[str, Any]]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        q = self.db.collection(collection).where(filter=FieldFilter("status", "==", status))
        return [s.to_dict() for s in q.stream()]
