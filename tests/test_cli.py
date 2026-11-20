import tempfile
import unittest
from pathlib import Path
from local_index import connect, search
from cli import register, repo_paths, resolve_repos, main


class CliTest(unittest.TestCase):
    def test_register_refresh_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            source = root / 'module.py'
            source.write_text('firstneedle\n')
            db_path = str(Path(tmp) / 'index.sqlite3')
            self.assertEqual(main(['--db', db_path, 'add', str(root)]), 0)
            with connect(db_path) as db:
                self.assertEqual(repo_paths(db), [str(root)])
                self.assertEqual(resolve_repos(db, ['repo']), [str(root)])
                self.assertTrue(search(db, 'firstneedle'))
            source.write_text('secondneedle\n')
            self.assertEqual(main(['--db', db_path, 'refresh', 'repo']), 0)
            with connect(db_path) as db:
                self.assertFalse(search(db, 'firstneedle'))
                self.assertTrue(search(db, 'secondneedle'))
            self.assertEqual(main(['--db', db_path, 'remove', 'repo']), 0)
            self.assertTrue(source.exists())
            with connect(db_path) as db:
                self.assertEqual(repo_paths(db), [])
                self.assertFalse(search(db, 'secondneedle'))


if __name__ == '__main__':
    unittest.main()
