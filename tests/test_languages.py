import unittest
from call_parser import calls_in_file

SAMPLES = {
    'cpp': 'void helper(){} void run(){helper(); obj.other();}',
    'java': 'class A { void helper(){} void run(){helper(); obj.other();} }',
    'js': 'function helper(){} function run(){helper(); obj.other()}',
    'ts': 'function helper():void{} const run = ():void => {helper(); obj.other()}',
    'sh': 'helper() { :; }\nrun() { helper; echo hi; }',
    'rs': 'fn helper(){} fn run(){helper(); obj.other();}',
    'go': 'package main\nfunc helper(){}\nfunc run(){helper(); obj.other()}',
    'py': 'def helper(): pass\ndef run():\n    helper()\n    obj.other()',
    'php': '<?php function helper() {} function run(){helper(); $obj->other();}',
}


class CallLanguagesTest(unittest.TestCase):
    def test_direct_and_unresolved(self):
        for extension, source in SAMPLES.items():
            with self.subTest(extension=extension):
                edges = calls_in_file('/repo/test.' + extension, source)
                self.assertTrue(any('local call' in e[2] and 'helper@' in e[1] for e in edges), edges)
                self.assertTrue(any('unresolved call' in e[2] for e in edges), edges)


if __name__ == '__main__':
    unittest.main()
