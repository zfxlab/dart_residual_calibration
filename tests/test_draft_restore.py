import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage import load_draft, load_project, new_project, project_bytes, save_draft


class DraftRestoreTests(unittest.TestCase):
    def test_repeated_restore_updates_same_file(self):
        with tempfile.TemporaryDirectory() as directory:
            project = new_project("原草稿")
            save_draft(project, directory)
            path = Path(directory) / f"{project['project_id']}.json"
            for index in range(3):
                restored = load_draft(path)
                self.assertEqual(restored["project_id"], project["project_id"])
                restored["name"] = f"修改 {index}"
                save_draft(restored, directory)
            self.assertEqual(list(Path(directory).glob("*.json")), [path])
            self.assertEqual(load_draft(path)["name"], "修改 2")

    def test_external_import_still_creates_copy(self):
        project = new_project("外部项目")
        imported = load_project(project_bytes(project))
        self.assertNotEqual(imported["project_id"], project["project_id"])
        self.assertEqual(imported["name"], project["name"])
