"""Traceability and evidence checks must reject incomplete or stale completion claims."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_specs as specs  # noqa: E402


class TestSpecContracts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="domimap-specs-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copytree(ROOT / "specs", self.root / "specs")
        for name in ("AGENTS.md", "docs/roadmap.md", "benchmarks/protocol.json"):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False))
        return path

    def test_registry_accounts_for_every_explicit_requirement(self):
        req, cases, progress = specs.validate(self.root)
        self.assertEqual(set(req), specs.REQUIREMENTS)
        self.assertEqual(set(cases), set(progress["cases"]))

    def test_orphan_case_is_rejected(self):
        path = self.root / "specs/requirements.json"
        data = specs.load(path)
        data["requirements"][0]["cases"] = []
        self.write("specs/requirements.json", data)
        with self.assertRaisesRegex(ValueError, "Orphan"):
            specs.validate(self.root)

    def test_protocol_cannot_drop_a_competitor_or_weaken_sample_floor(self):
        protocol = specs.load(self.root / "benchmarks/protocol.json")
        protocol["baselines"].pop("graphify")
        with self.assertRaisesRegex(ValueError, "four competitors"):
            specs.validate_protocol(protocol)
        protocol = specs.load(self.root / "benchmarks/protocol.json")
        protocol["minimum_answerable"] = 8
        with self.assertRaisesRegex(ValueError, "weakened"):
            specs.validate_protocol(protocol)

    def test_verified_requires_current_evidence_and_real_artifacts(self):
        progress = specs.load(self.root / "specs/progress.json")
        cid = next(iter(progress["cases"]))
        progress["cases"][cid] = {"state": "verified", "evidence": []}
        self.write("specs/progress.json", progress)
        with self.assertRaisesRegex(ValueError, "without evidence"):
            specs.validate(self.root)
        artifact = self.write("out/result.json", {"assertion": "passed"})
        evidence = {"case_id": cid, "outcome": "pass", "exit_code": 0, "source_fingerprint": specs.source_fingerprint(self.root), "command": ["unit-test"], "environment": {"test": "fixture"}, "artifacts": [{"path": "out/result.json", "sha256": specs.digest(artifact)}]}
        self.write("out/evidence.json", evidence)
        progress["cases"][cid]["evidence"] = ["out/evidence.json"]
        self.write("specs/progress.json", progress)
        specs.validate(self.root)
        self.write("domimap/new_source.py", {"changed": True})
        with self.assertRaisesRegex(ValueError, "Stale"):
            specs.validate(self.root)

    def test_planned_stage_cannot_pass(self):
        _, cases, progress = specs.validate(self.root)
        with self.assertRaisesRegex(ValueError, "Incomplete M0"):
            specs.require_stage("M0", cases, progress)
        with self.assertRaisesRegex(ValueError, "Unverified dependency"):
            specs.require_stage("M5", cases, progress)

    def test_task_detects_actual_changes_outside_allowed_files(self):
        if not shutil.which("git"):
            self.skipTest("git unavailable")
        req, cases, _ = specs.validate(self.root)
        cid = next(iter(cases))
        task = {"id": "identity", "state": "implementing", "spec": "specs/tasks/identity.md", "requirements": [cases[cid]["requirement"]], "acceptance_cases": [cid], "files": ["allowed.py", "tests/test_allowed.py"], "test_files": ["tests/test_allowed.py"]}
        self.write("specs/tasks/identity.md", "Task contract fixture")
        self.write("specs/tasks/identity.json", task)
        def git(*args):
            return subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", *args], cwd=self.root, capture_output=True, text=True, check=True)
        git("init", "-q")
        git("add", ".")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
        self.write("allowed.py", "allowed")
        specs.check_task(self.root, "specs/tasks/identity.json", req, cases, "HEAD")
        self.write("unrelated.py", "outside scope")
        with self.assertRaisesRegex(ValueError, "outside task"):
            specs.check_task(self.root, "specs/tasks/identity.json", req, cases, "HEAD")

    def test_evidence_paths_cannot_escape(self):
        with self.assertRaises(ValueError):
            specs.local_path(self.root, "../private.json")

    def test_missing_document_link_is_rejected(self):
        (self.root / "README.md").write_text("[missing](absent.md)")
        with self.assertRaisesRegex(ValueError, "Broken document link"):
            specs.check_links(self.root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
