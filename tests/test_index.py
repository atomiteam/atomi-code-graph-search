import tempfile
import unittest
from pathlib import Path
from local_index import connect, index, search


class IndexTest(unittest.TestCase):
    def test_progress_reports_indexing_and_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            (root / 'app.py').write_text('def run():\n    pass\n')
            db_path = Path(tmp) / 'index.sqlite3'
            events = []
            with connect(db_path) as db:
                index(db, [root], db_path, progress=lambda *event: events.append(event))
            self.assertTrue(any(stage == 'indexing' and done == total == 1
                                for stage, done, total, _ in events))
            self.assertTrue(any(stage == 'building graph' for stage, *_ in events))
            self.assertEqual(events[-1][0], 'complete')

    def test_update_delete_and_same_named_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            roots = [base / n / 'repo' for n in ('a', 'b')]
            for root in roots:
                root.mkdir(parents=True)
            (roots[0] / 'app.py').write_text('uniquealpha\n')
            (roots[1] / 'app.py').write_text('uniquebeta\n')
            db_path = base / 'index.sqlite3'
            with connect(db_path) as db:
                self.assertEqual(index(db, roots, db_path)['updated'], 2)
                self.assertEqual(len(search(db, 'uniquealpha')), 1)
                self.assertEqual(index(db, roots, db_path)['unchanged'], 2)
                (roots[0] / 'app.py').write_text('uniquegamma\n')
                index(db, [roots[0]], db_path)
                self.assertFalse(search(db, 'uniquealpha'))
                self.assertTrue(search(db, 'uniquegamma'))
                (roots[1] / 'app.py').unlink()
                self.assertEqual(index(db, [roots[1]], db_path)['removed'], 1)
                self.assertFalse(search(db, 'uniquebeta'))


if __name__ == '__main__':
    unittest.main()
