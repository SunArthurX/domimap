"""Safety checks for cleaning generated files."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "clean.py"


class TestProjectCleanup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="domimap-hygiene-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy2(SCRIPT, self.root / "scripts" / "clean.py")

    def write(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("keep", encoding="utf-8")
        return path

    def run_clean(self, *args):
        result = subprocess.run(
            [sys.executable, "-B", str(self.root / "scripts" / "clean.py"), *args],
            cwd=self.temp.name, capture_output=True, text=True, check=True,
        )
        return result.stdout

    def test_preview_and_default_preserve_sources_and_outputs(self):
        source = self.write("domimap/source.py")
        note = self.write("docs/note.md")
        graph = self.write("out/graph.json")
        generated = [self.write(name) for name in (
            "domimap/__pycache__/source.pyc", "domimap.egg-info/PKG-INFO",
            "benchmarks/__pycache__/evaluate.pyc",
            "dist/package.whl", "tests/out_multi/graph.json",
        )]
        self.run_clean("--dry-run")
        self.assertTrue(all(path.exists() for path in generated))
        self.run_clean()
        self.assertTrue(all(not path.exists() for path in generated))
        self.assertTrue(all(path.exists() for path in (source, note, graph)))
        self.assertIn("Project is clean.", self.run_clean())

    def test_outputs_require_explicit_option(self):
        graph = self.write("out/graph.json")
        self.run_clean("--outputs")
        self.assertFalse(graph.exists())

    def symlink(self, target, link):
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest("Directory symlinks unavailable: %s" % error)

    def test_generated_directory_symlink_does_not_delete_target(self):
        outside = Path(self.temp.name) / "external"
        outside.mkdir()
        sentinel = outside / "note.md"
        sentinel.write_text("keep", encoding="utf-8")
        self.symlink(outside, self.root / "dist")
        self.run_clean()
        self.assertTrue(sentinel.exists())
        self.assertFalse((self.root / "dist").is_symlink())

    def test_parent_symlink_cannot_redirect_cleanup(self):
        outside = Path(self.temp.name) / "external"
        (outside / "out_multi").mkdir(parents=True)
        sentinel = outside / "out_multi" / "graph.json"
        sentinel.write_text("keep", encoding="utf-8")
        self.symlink(outside, self.root / "tests")
        self.run_clean()
        self.assertTrue(sentinel.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
