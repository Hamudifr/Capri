"""Tests for the number theory and cryptography training module."""

import unittest

from research.training.crypto.numbers import (
    mod_pow, modular_inverse, euler_phi,
    fermat_little_theorem, euler_theorem,
    gcd, extended_gcd,
    is_prime_trial, miller_rabin, find_prime,
    tonelli_shanks, RSA, baby_step_giant_step,
    diffie_hellman_shared, fnv1a_32, fnv1a_64,
    sha256_hex, sha256_int,
)


class TestModularArithmetic(unittest.TestCase):

    def test_mod_pow(self):
        self.assertEqual(mod_pow(2, 10, 1000), 24)

    def test_mod_pow_large(self):
        # 3^5 = 243, mod 10 = 3
        self.assertEqual(mod_pow(3, 5, 10), 3)

    def test_mod_pow_modulus_one(self):
        self.assertEqual(mod_pow(5, 10, 1), 0)

    def test_modular_inverse(self):
        # 3 * 7 = 21 ≡ 1 (mod 10)
        self.assertEqual(modular_inverse(3, 10), 7)

    def test_modular_inverse_check(self):
        inv = modular_inverse(7, 26)
        self.assertEqual((7 * inv) % 26, 1)

    def test_modular_inverse_no_inverse(self):
        with self.assertRaises(ValueError):
            modular_inverse(2, 4)

    def test_euler_phi(self):
        self.assertEqual(euler_phi(1), 0)
        self.assertEqual(euler_phi(2), 1)
        self.assertEqual(euler_phi(7), 6)  # prime
        self.assertEqual(euler_phi(10), 4)  # 1,3,7,9

    def test_fermat_little_theorem(self):
        # 2^(7-1) = 64 ≡ 1 (mod 7)
        self.assertTrue(fermat_little_theorem(2, 7))

    def test_fermat_little_theorem_composite(self):
        # 2^(4-1) = 8 ≡ 0 (mod 4), not 1
        self.assertFalse(fermat_little_theorem(2, 4))

    def test_euler_theorem(self):
        # 3^φ(10) = 3^4 = 81 ≡ 1 (mod 10)
        self.assertTrue(euler_theorem(3, 10))


class TestGCD(unittest.TestCase):

    def test_gcd(self):
        self.assertEqual(gcd(12, 8), 4)
        self.assertEqual(gcd(7, 13), 1)
        self.assertEqual(gcd(0, 5), 5)

    def test_extended_gcd(self):
        g, x, y = extended_gcd(30, 12)
        self.assertEqual(g, 6)
        self.assertEqual(30 * x + 12 * y, 6)

    def test_extended_gcd_coprime(self):
        g, x, y = extended_gcd(7, 5)
        self.assertEqual(g, 1)
        self.assertEqual(7 * x + 5 * y, 1)


class TestPrimality(unittest.TestCase):

    def test_is_prime_trial(self):
        self.assertTrue(is_prime_trial(7))
        self.assertTrue(is_prime_trial(2))
        self.assertTrue(is_prime_trial(3))
        self.assertFalse(is_prime_trial(1))
        self.assertFalse(is_prime_trial(0))
        self.assertFalse(is_prime_trial(9))
        self.assertFalse(is_prime_trial(4))

    def test_miller_rabin(self):
        self.assertTrue(miller_rabin(7))
        self.assertTrue(miller_rabin(2))
        self.assertTrue(miller_rabin(97))
        self.assertFalse(miller_rabin(9))
        self.assertFalse(miller_rabin(4))
        self.assertFalse(miller_rabin(1))

    def test_find_prime(self):
        p = find_prime(8)
        self.assertTrue(miller_rabin(p))
        self.assertGreater(p, 2 ** 7)

    def test_find_prime_reproducible(self):
        p1 = find_prime(8)
        p2 = find_prime(8)
        self.assertEqual(p1, p2)


class TestTonelliShanks(unittest.TestCase):

    def test_tonelli_shanks(self):
        # 4 ≡ 2^2 (mod 7), so sqrt(4) mod 7 should be 2 and 5
        result = tonelli_shanks(4, 7)
        self.assertIsNotNone(result)
        r, other = result
        self.assertAlmostEqual((r * r) % 7, 4, places=8)
        self.assertAlmostEqual((other * other) % 7, 4, places=8)

    def test_tonelli_shanks_non_residue(self):
        # 3 is a quadratic non-residue mod 7
        result = tonelli_shanks(3, 7)
        self.assertIsNone(result)


class TestRSA(unittest.TestCase):

    def test_rsa_encrypt_decrypt(self):
        rsa = RSA().generate_keys(bits=16)
        message = 42
        ciphertext = rsa.encrypt(message)
        decrypted = rsa.decrypt(ciphertext)
        self.assertEqual(decrypted, message)

    def test_rsa_encrypt_decrypt_multiple(self):
        rsa = RSA().generate_keys(bits=16)
        for msg in [1, 5, 10, 100, 1000]:
            ct = rsa.encrypt(msg)
            self.assertEqual(rsa.decrypt(ct), msg)

    def test_rsa_key_properties(self):
        rsa = RSA().generate_keys(bits=16)
        self.assertGreater(rsa.n, 1)
        self.assertGreater(rsa.e, 1)
        self.assertGreater(rsa.d, 0)
        # e * d ≡ 1 (mod phi)
        self.assertEqual((rsa.e * rsa.d) % rsa.phi, 1)

    def test_rsa_bytes(self):
        rsa = RSA().generate_keys(bits=64)
        data = b"hello"
        ciphertexts = rsa.encrypt_bytes(data)
        decrypted = rsa.decrypt_bytes(ciphertexts)
        # The decrypted bytes may have leading zeros due to padding
        self.assertTrue(decrypted.endswith(b"hello"))


class TestDiscreteLog(unittest.TestCase):

    def test_baby_step_giant_step(self):
        # 3^x ≡ 27 (mod 31) → x = 3 since 3^3 = 27
        result = baby_step_giant_step(3, 27, 31)
        self.assertIsNotNone(result)
        self.assertEqual(mod_pow(3, result, 31), 27)


class TestDiffieHellman(unittest.TestCase):

    def test_shared_secret(self):
        g, p = 2, 23
        secret = diffie_hellman_shared(g, p, private_a=5, private_b=7)
        # g^(ab) mod p = 2^35 mod 23
        expected = mod_pow(g, 5 * 7, p)
        self.assertEqual(secret, expected)


class TestHash(unittest.TestCase):

    def test_fnv1a_32(self):
        h = fnv1a_32(b"hello")
        self.assertIsInstance(h, int)
        self.assertGreater(h, 0)

    def test_fnv1a_64(self):
        h = fnv1a_64(b"hello")
        self.assertIsInstance(h, int)
        self.assertGreater(h, 0)

    def test_fnv_deterministic(self):
        self.assertEqual(fnv1a_32(b"test"), fnv1a_32(b"test"))

    def test_fnv_different_inputs(self):
        self.assertNotEqual(fnv1a_32(b"test"), fnv1a_32(b"other"))

    def test_sha256_hex(self):
        h = sha256_hex(b"hello")
        self.assertEqual(len(h), 64)
        self.assertIsInstance(h, str)

    def test_sha256_deterministic(self):
        self.assertEqual(sha256_hex(b"test"), sha256_hex(b"test"))

    def test_sha256_int(self):
        h = sha256_int(b"hello")
        self.assertIsInstance(h, int)
        self.assertGreater(h, 0)


if __name__ == "__main__":
    unittest.main()
