import tempfile
import unittest
from pathlib import Path
from local_index import connect, index
from source_graph import graph, to_dot


class GraphTest(unittest.TestCase):
    def test_imports_calls_refresh_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            (root / 'helper.py').write_text('def helper():\n    pass\n')
            caller = root / 'app.py'
            caller.write_text('from helper import helper\ndef run():\n    helper()\n')
            dbpath = Path(tmp) / 'index.sqlite3'
            with connect(dbpath) as db:
                index(db, [root], dbpath)
                imports = graph(db, str(root))
                calls = graph(db, str(root), kind='calls')
                self.assertEqual(len(imports['edges']), 1)
                self.assertEqual(len(calls['edges']), 1)
                self.assertIn('helper.py::helper', to_dot(calls))
                caller.write_text('def run():\n    pass\n')
                index(db, [root], dbpath)
                self.assertEqual(graph(db, str(root), kind='calls')['edges'], [])
                caller.unlink()
                index(db, [root], dbpath)
                self.assertEqual(graph(db, str(root))['edges'], [])


if __name__ == '__main__':
    unittest.main()
