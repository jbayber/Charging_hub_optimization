"""A dummy test to check that the test suite is collected and runs."""

import unittest


class TestDummy(unittest.TestCase):
    def test_dummy(self) -> None:
        """Always passes; checks that the test suite is collected and runs."""
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
