"""A timeout must stop the whole process tree, not just the shell."""
import sys
import time
import unittest

from test_scripts import SCRIPTS, TmpDirCase

sys.path.insert(0, str(SCRIPTS))

import verify  # noqa: E402


@unittest.skipUnless(sys.platform != "win32", "POSIX process groups")
class TimeoutTreeTests(TmpDirCase):
    def test_background_child_holding_the_pipe_does_not_hang_the_run(self):
        start = time.time()
        r = verify.run_step({"kind": "test", "stack": "x", "cwd": ".", "cmd": "echo started; sleep 30 & sleep 30"},
                            self.root, 1)
        self.assertEqual(r["status"], "timeout")
        self.assertLess(time.time() - start, 15, "timeout waited for grandchildren")
        self.assertIn("started", r["tail"])


if __name__ == "__main__":
    unittest.main()
