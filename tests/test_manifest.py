"""Offline smoke tests for path handling and safety checks."""
from pathlib import Path
import importlib.util
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'drive_to_seafile_all_v6.py'
spec = importlib.util.spec_from_file_location('migrator_v6', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ManifestTests(unittest.TestCase):
    def test_duplicate_names_are_distinct(self):
        used = {'photo.jpg'}
        result = module.hashed_name('photo.jpg', 'a-drive-id', used)
        self.assertNotEqual(result.casefold(), 'photo.jpg')
        self.assertTrue(result.endswith('.jpg'))

    def test_safe_name_replaces_slash(self):
        self.assertEqual(module.safe_name('a/b'), 'a／b')

    def test_manifest_rejects_path_traversal(self):
        base = {'root_id': module.ROOT_DEFAULT, 'source': 'gdrive:',
                'target_dir': 'GoogleDrive-Import', 'folders': [],
                'files': [{'id': 'id1', 'path': 'GoogleDrive-Import/../bad.txt'}]}
        with self.assertRaises(RuntimeError):
            module.validate_manifest(base)

    def test_manifest_rejects_colliding_paths(self):
        base = {'root_id': module.ROOT_DEFAULT, 'source': 'gdrive:',
                'target_dir': 'GoogleDrive-Import', 'folders': [],
                'files': [{'id': 'id1', 'path': 'GoogleDrive-Import/X.txt'},
                          {'id': 'id2', 'path': 'GoogleDrive-Import/x.txt'}]}
        with self.assertRaises(RuntimeError):
            module.validate_manifest(base)

    def test_size_match(self):
        self.assertTrue(module.matches_size({'size': '100'}, {'Size': 100, 'IsDir': False}))
        self.assertFalse(module.matches_size({'size': '100'}, {'Size': 99, 'IsDir': False}))


if __name__ == '__main__':
    unittest.main()
