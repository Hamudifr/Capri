import unittest

from capri_core.validation import contains_surrogate


class UnicodeScalarValidationTests(unittest.TestCase):
    def test_accepts_unicode_scalar_values(self):
        for value in ("plain ASCII", "مرحبا", "😀", ""):
            with self.subTest(value=value):
                self.assertFalse(contains_surrogate(value))

    def test_rejects_lone_surrogate_code_points(self):
        for value in ("\ud800", "\udfff", "valid\ud800text"):
            with self.subTest(value=repr(value)):
                self.assertTrue(contains_surrogate(value))


if __name__ == "__main__":
    unittest.main()
