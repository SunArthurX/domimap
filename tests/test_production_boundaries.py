"""Production invariants exercised through the real storage and transport boundaries."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from domimap.graph import Graph
from domimap.mcp import Server
from domimap.store import EvidenceStore
from domimap.ui import make_server

ROOT = Path(__file__).resolve().parents[1]


class Workspace(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-boundaries-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / "store.db"
        self.store = EvidenceStore(str(self.path))
        self.addCleanup(self.store.close)
        self.source = self.root / "input.md"
        self.g = Graph()
        self.g.add_node("doc:fixture", "Doc", "fixture", "input.md", {"text": "version"})
        self.g.save(str(self.root / "graph.json"))

    def capture(self, text, sid="a|input.md", rel="input.md"):
        self.source.write_text(text, encoding="utf-8")
        return self.store.capture_source(sid.split("|", 1)[0], sid, str(self.source), rel)


class TestEvidenceIdentity(Workspace):
    def test_recapture_keeps_each_id_and_source_version(self):
        first = self.capture("version one")
        second = self.capture("version two")
        self.source.unlink()
        for captured, text in [(first, "version one"), (second, "version two")]:
            read = self.store.read_evidence(captured["ev_id"])
            self.assertTrue(read["available"])
            self.assertEqual(read["text"], text)
            self.assertEqual(read["ev_id"], captured["ev_id"])
            self.assertEqual(read["sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(self.store.evidence_for_source(first["sid"])["ev_id"], second["ev_id"])
        with contextlib.closing(EvidenceStore(str(self.path))) as reopened:
            self.assertEqual(reopened.read_evidence(first["ev_id"])["text"], "version one")

    def test_copies_share_bytes_but_never_overwrite_provenance(self):
        first = self.capture("same text", "a|input.md")
        second = self.capture("same text", "b|input.md")
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertNotEqual(first["ev_id"], second["ev_id"])
        for rec in (first, second):
            self.assertEqual(self.store.read_evidence(rec["ev_id"])["sid"], rec["sid"])
        self.assertNotIn("input.md", self.store.evidence_map(), "ambiguous paths must not guess a source")

    def test_same_capture_is_idempotent_and_old_format_remains_readable(self):
        first = self.capture("stable")
        second = self.capture("stable")
        self.assertEqual(first, second)
        old_id = "ev:" + first["sha256"][:20]
        self.store.db.execute(
            "INSERT INTO evidence SELECT ?,sid,locator,blob_sha,captured_at FROM evidence WHERE ev_id=?",
            (old_id, first["ev_id"]))
        self.store.db.commit()
        self.assertEqual(self.store.read_evidence(old_id)["text"], "stable")

    def test_recapture_back_to_an_old_version_updates_source_lookup(self):
        first = self.capture("version one")
        self.capture("version two")
        self.capture("version one")
        self.assertEqual(self.store.evidence_for_source(first["sid"])["ev_id"], first["ev_id"])
        self.assertEqual(self.store.evidence_map()["input.md"], first["ev_id"])

    def test_corrupt_existing_blob_cannot_be_published_as_a_new_source(self):
        first = self.capture("stable")
        (self.root / "blobs" / first["sha256"]).write_text("corrupted")
        with self.assertRaises(ValueError):
            self.capture("stable", "b|input.md")
        self.assertEqual(len(self.store.list_sources()), 1)

    def test_truncated_excerpt_has_a_distinct_identity_and_visible_limit(self):
        from domimap.store import BLOB_LIMIT
        first = self.capture("x" * BLOB_LIMIT)
        second = self.capture("x" * (BLOB_LIMIT + 10))
        self.assertNotEqual(first["ev_id"], second["ev_id"])
        self.assertFalse(self.store.read_evidence(first["ev_id"])["locator"]["truncated"])
        self.assertTrue(self.store.read_evidence(second["ev_id"])["locator"]["truncated"])
        self.capture("x" * BLOB_LIMIT)
        self.assertEqual(self.store.evidence_for_source(first["sid"])["ev_id"], first["ev_id"])

    def test_missing_or_corrupted_blob_is_unavailable(self):
        rec = self.capture("original")
        blob = self.root / "blobs" / rec["sha256"]
        for data in (b"tampered", b"x" * ((1 << 20) + 1)):
            blob.write_bytes(data)
            ev = self.store.read_evidence(rec["ev_id"])
            self.assertFalse(ev["available"])
            self.assertNotIn("text", ev)
        blob.unlink()
        self.assertFalse(self.store.read_evidence(rec["ev_id"])["available"])
        blob.symlink_to(self.source)
        self.assertFalse(self.store.read_evidence(rec["ev_id"])["available"])
        self.assertIsNone(self.store.read_evidence("ev:unknown"))

    def test_shared_instance_capture_and_publish_are_serialized(self):
        self.source.write_text("shared bytes", encoding="utf-8")
        barrier = threading.Barrier(8)

        def capture(i):
            barrier.wait(timeout=10)
            rec = self.store.capture_source("repo", "repo|%d" % i, str(self.source), str(i))
            self.store.publish_graph(self.g)
            return rec

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(capture, range(8)))
        self.assertEqual(len({r["ev_id"] for r in results}), 8)
        self.assertEqual(len(self.store.list_sources()), 8)
        self.assertEqual(self.store.active_generation()["gen_id"], 8)

    def test_parallel_connections_can_capture_same_blob(self):
        self.source.write_text("same blob", encoding="utf-8")
        stores = [EvidenceStore(str(self.path)) for _ in range(6)]
        for store in stores:
            self.addCleanup(store.close)
        barrier = threading.Barrier(6)

        def capture(i):
            barrier.wait(timeout=10)
            return stores[i].capture_source("repo", "repo|%d" % i, str(self.source), str(i))

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(capture, range(6)))
        self.assertEqual(len({r["ev_id"] for r in results}), 6)
        self.assertTrue(all(self.store.read_evidence(r["ev_id"])["available"] for r in results))

    def test_active_generation_rejects_valid_json_with_wrong_hash(self):
        rec = self.store.publish_graph(self.g)
        path = Path(rec["path"])
        data = json.loads(path.read_text())
        data["nodes"][0]["name"] = "tampered"
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertIsNone(self.store.active_generation())


class TestEvidenceAdapters(Workspace):
    def test_cli_mcp_and_ui_read_exact_old_id_after_recapture(self):
        first = self.capture("old excerpt")
        latest = self.capture("new excerpt")
        self.source.unlink()
        srv = Server(str(self.root / "graph.json"))
        mcp = srv.handle("kg_read", {"ev_id": first["ev_id"]})
        self.assertIn("old excerpt", mcp)
        self.assertNotIn("new excerpt", mcp)
        cli = subprocess.run([sys.executable, "-B", "-m", "domimap", "read", first["ev_id"],
                              "--store", str(self.path)], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertIn("old excerpt", cli.stdout)
        self.assertNotIn("new excerpt", cli.stdout)
        ui = make_server(str(self.root / "graph.json"), port=0)
        thread = threading.Thread(target=ui.serve_forever, daemon=True)
        thread.start()
        try:
            for captured, text in ((first, "old excerpt"), (latest, "new excerpt")):
                with urllib.request.urlopen("http://127.0.0.1:%d/api/read?ev=%s" %
                                            (ui.server_port, captured["ev_id"]), timeout=10) as response:
                    ev = json.load(response)
                self.assertEqual(ev["ev_id"], captured["ev_id"])
                self.assertEqual(ev["text"], text)
        finally:
            ui.shutdown()
            ui.server_close()
            thread.join(timeout=10)


class TestProtocolBoundary(Workspace):
    def exchange(self, lines):
        process = subprocess.run([sys.executable, "-B", "-m", "domimap", "serve", "-g",
                                  str(self.root / "graph.json")], input="\n".join(lines) + "\n",
                                 cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertNotIn("Traceback", process.stderr)
        return [json.loads(line) for line in process.stdout.splitlines()]

    def test_invalid_envelopes_never_kill_following_request(self):
        bad = ["null", "[]", "42", '"text"', '{"method":"ping","id":1}',
               '{"jsonrpc":"2.0","method":1,"id":[]}',
               '{"jsonrpc":"2.0","method":"ping","id":true}',
               '{"jsonrpc":"2.0","method":"ping","id":2,"params":[]}', "{broken"]
        ping = json.dumps({"jsonrpc": "2.0", "id": "alive", "method": "ping"})
        result = self.exchange(bad + [ping])
        self.assertEqual(len(result), len(bad) + 1)
        self.assertTrue(all("error" in r for r in result[:-1]))
        self.assertEqual(result[-1], {"jsonrpc": "2.0", "id": "alive", "result": {}})

    def test_oversized_frame_is_drained_and_notifications_have_no_response(self):
        result = self.exchange(["x" * ((2 << 20) + 3),
                                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                                json.dumps({"jsonrpc": "2.0", "method": "ping"}),
                                json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/list"})])
        self.assertEqual(len(result), 2)
        self.assertIn("error", result[0])
        self.assertEqual(result[1]["id"], 7)
        # 默认 stdio 服务只公布 6 个只读工具；kg_feedback 须 --enable-write（roadmap M3 写能力分离）
        self.assertEqual(len(result[1]["result"]["tools"]), 6)

    def test_tool_errors_are_marked_and_integer_budgets_are_enforced(self):
        cases = [("kg_explore", {"query": "version", "top_k": True}),
                 ("kg_explore", {"query": "version", "top_k": 1000000}),
                 ("kg_explore", {"query": "x" * 4097}),
                 ("kg_impact", {"symbol": "x", "depth": -1}),
                 ("kg_impact", {"symbol": "x", "max_nodes": 0}),
                 ("kg_read", {"ev_id": ["bad"]}),
                 ("kg_explore", []), ("no_such_tool", {})]
        lines = [json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call",
                             "params": {"name": name, "arguments": args}})
                 for i, (name, args) in enumerate(cases)]
        lines.append(json.dumps({"jsonrpc": "2.0", "id": "last", "method": "tools/list"}))
        result = self.exchange(lines)
        self.assertEqual(len(result), len(cases) + 1)
        for reply in result[:-1]:
            self.assertTrue(reply["result"]["isError"], reply)
            self.assertLess(len(json.dumps(reply)), 512)
        self.assertEqual(result[-1]["id"], "last")

    def test_frame_reader_never_requests_an_unbounded_read(self):
        from domimap.mcp import _request_lines, MAX_REQUEST_CHARS

        class BoundedStream(io.StringIO):
            def readline(self, size=-1):
                if not 0 < size <= MAX_REQUEST_CHARS + 1:
                    raise AssertionError("unbounded frame allocation")
                return super().readline(size)

        stream = BoundedStream("x" * (3 * MAX_REQUEST_CHARS) + "\n{}\n")
        self.assertEqual(list(_request_lines(stream)), [None, "{}\n"])


if __name__ == "__main__":
    unittest.main()
