"""Acknowledged knowledge and existing databases must survive concurrent/failing operations."""
import contextlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from domimap.knowledge import KnowledgeStore


class KnowledgeSafety(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-knowledge-safety-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = KnowledgeStore(str(self.root / "source.db"))
        self.addCleanup(self.store.close)

    def populate(self):
        result = self.store.submit("first", [{"type": "decision", "statement": "keep history"}], "one")
        self.store.amend(result["note_id"], "second", 1)
        return result["note_id"]

    def test_shared_connection_never_rolls_back_another_acknowledged_write(self):
        entered = threading.Event()
        release = threading.Event()
        second_started = threading.Event()
        second_finished = threading.Event()
        snapshot = self.store._snapshot

        def paused_snapshot(*args):
            snapshot(*args)
            if args[1] == "first":
                entered.set()
                if not release.wait(timeout=10):
                    raise TimeoutError("test writer was never released")

        self.store._snapshot = paused_snapshot

        def second():
            second_started.set()
            try:
                return self.store.submit("second", idempotency_key="second")
            finally:
                second_finished.set()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.store.submit, "first", [], "first")
            self.assertTrue(entered.wait(timeout=10))
            later = pool.submit(second)
            self.assertTrue(second_started.wait(timeout=10))
            # Give the second operation a chance to enter the old shared transaction.
            second_finished.wait(timeout=0.2)
            release.set()
            results = [first.result(timeout=10), later.result(timeout=10)]
        self.assertEqual(self.store.count(), 2)
        for result in results:
            self.assertIsNotNone(self.store.get(result["note_id"]))

    def test_multi_statement_read_keeps_one_snapshot_across_connections(self):
        first_claims = [{"type": "decision", "statement": "version one"}]
        nid = self.store.submit("version one", first_claims)["note_id"]
        other = KnowledgeStore(str(self.root / "source.db"))
        self.addCleanup(other.close)
        claims_of = self.store._claims_of

        def update_between_reads(note_id):
            other.amend(nid, "version two", 1,
                        [{"type": "decision", "statement": "version two"}])
            return claims_of(note_id)

        self.store._claims_of = update_between_reads
        try:
            note = self.store.get(nid)
        finally:
            self.store._claims_of = claims_of
        self.assertEqual(note["body"], note["claims"][0]["statement"])
        self.assertEqual(self.store.get(nid)["revision"], 2)

    def test_cancelled_read_releases_its_transaction_for_the_next_write(self):
        nid = self.populate()
        claims_of = self.store._claims_of

        def cancelled(note_id):
            raise KeyboardInterrupt()

        self.store._claims_of = cancelled
        try:
            with self.assertRaises(KeyboardInterrupt):
                self.store.get(nid)
        finally:
            self.store._claims_of = claims_of
        self.assertFalse(self.store.db.in_transaction)
        self.assertEqual(self.store.submit("after cancellation")["revision"], 1)

    def test_backup_manifest_uses_backup_snapshot_not_live_counts(self):
        self.populate()
        real = self.store.db
        other = KnowledgeStore(str(self.root / "source.db"))
        self.addCleanup(other.close)

        class WritesAfterBackup:
            def __getattr__(self, name):
                return getattr(real, name)

            def __enter__(self):
                return real.__enter__()

            def __exit__(self, *args):
                return real.__exit__(*args)

            def backup(self, target):
                real.backup(target)
                other.submit("written after snapshot", idempotency_key="after")

        self.store.db = WritesAfterBackup()
        try:
            manifest = self.store.backup(str(self.root / "backup"))
        finally:
            self.store.db = real
        with contextlib.closing(sqlite3.connect(self.root / "backup" / "kb.db")) as backup:
            count = backup.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        self.assertEqual(manifest["notes"], count)
        self.assertEqual(self.store.count(), count + 1)

    def test_existing_database_and_link_target_are_never_overwritten(self):
        self.populate()
        self.store.backup(str(self.root / "backup"))
        target = self.root / "target.db"
        with contextlib.closing(KnowledgeStore(str(target))) as existing:
            note = existing.submit("do not overwrite")
        for path in (target, self.root / "link.db"):
            if path != target:
                path.symlink_to(target)
            with self.assertRaises(FileExistsError):
                KnowledgeStore.restore(str(self.root / "backup"), str(path))
        with contextlib.closing(KnowledgeStore(str(target))) as existing:
            self.assertEqual(existing.get(note["note_id"])["body"], "do not overwrite")

    def test_failed_validation_leaves_no_destination(self):
        self.populate()
        backup = self.root / "backup"
        original = self.store.backup(str(backup))
        for key in ("notes", "revisions", "claims"):
            manifest = dict(original)
            manifest[key] += 1
            (backup / "manifest.json").write_text(json.dumps(manifest))
            target = self.root / (key + ".db")
            with self.assertRaises(ValueError):
                KnowledgeStore.restore(str(backup), str(target))
            self.assertFalse(target.exists())

    def test_unknown_schema_and_corrupt_bytes_are_rejected(self):
        self.populate()
        backup = self.root / "backup"
        manifest = self.store.backup(str(backup))
        unknown = dict(manifest, schema="future.version")
        (backup / "manifest.json").write_text(json.dumps(unknown))
        with self.assertRaises(ValueError):
            KnowledgeStore.restore(str(backup), str(self.root / "future.db"))
        (backup / "manifest.json").write_text(json.dumps(manifest))
        with (backup / "kb.db").open("ab") as stream:
            stream.write(b"changed bytes")
        with self.assertRaises(ValueError):
            KnowledgeStore.restore(str(backup), str(self.root / "corrupt.db"))
        self.assertFalse((self.root / "corrupt.db").exists())

    def test_restore_validates_every_table_count_and_preserves_history(self):
        nid = self.populate()
        backup = self.root / "backup"
        manifest = self.store.backup(str(backup))
        self.assertEqual(manifest["schema"], "domimap.kbackup.v2")
        with contextlib.closing(KnowledgeStore.restore(str(backup), str(self.root / "restored.db"))) as restored:
            self.assertEqual(restored.get(nid), self.store.get(nid))
            self.assertEqual(restored.history(nid), self.store.history(nid))
        manifest["table_counts"]["idempotency"] += 1
        (backup / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            KnowledgeStore.restore(str(backup), str(self.root / "bad-count.db"))

    def test_legacy_v1_checks_all_declared_counts(self):
        self.populate()
        backup = self.root / "backup"
        manifest = self.store.backup(str(backup))
        legacy = {key: manifest[key] for key in ("notes", "revisions", "claims", "created")}
        legacy["schema"] = "domimap.kbackup.v1"
        (backup / "manifest.json").write_text(json.dumps(legacy))
        with contextlib.closing(KnowledgeStore.restore(str(backup), str(self.root / "legacy.db"))) as restored:
            self.assertEqual(restored.count(), 1)
        legacy["revisions"] += 1
        (backup / "manifest.json").write_text(json.dumps(legacy))
        with self.assertRaises(ValueError):
            KnowledgeStore.restore(str(backup), str(self.root / "bad-legacy.db"))

    def test_backup_does_not_overwrite_an_existing_archive(self):
        self.populate()
        backup = self.root / "backup"
        self.store.backup(str(backup))
        before = (backup / "kb.db").read_bytes()
        with self.assertRaises(FileExistsError):
            self.store.backup(str(backup))
        self.assertEqual((backup / "kb.db").read_bytes(), before)

    def test_orphan_wal_and_invalid_schema_are_rejected_before_publication(self):
        self.populate()
        backup = self.root / "backup"
        manifest = self.store.backup(str(backup))
        target = self.root / "orphan.db"
        Path(str(target) + "-wal").write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            KnowledgeStore.restore(str(backup), str(target))
        with contextlib.closing(sqlite3.connect(backup / "kb.db")) as db:
            db.execute("ALTER TABLE knowledge RENAME COLUMN body TO broken_body")
            db.commit()
        # A v1 archive has no content hash; it must still validate the table structure.
        manifest = {key: manifest[key] for key in ("notes", "claims", "revisions", "created")}
        manifest["schema"] = "domimap.kbackup.v1"
        (backup / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            KnowledgeStore.restore(str(backup), str(self.root / "bad-schema.db"))
        self.assertFalse((self.root / "bad-schema.db").exists())


if __name__ == "__main__":
    unittest.main()
