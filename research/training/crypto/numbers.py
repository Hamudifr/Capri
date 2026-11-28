"""Number theory and cryptography study modules.

Implements core concepts from number theory and their application
to cryptography: modular arithmetic, primality testing, the
extended Euclidean algorithm, RSA, and discrete logarithms.
Pure stdlib, no dependencies.

Topics covered:
- Modular arithmetic: pow with mod, modular inverse
- GCD and the extended Euclidean algorithm
- Euclid's algorithm for GCD
- Primality testing: trial division, Miller-Rabin
- Modular square roots (Tonelli-Shanks for odd primes)
- RSA public-key encryption (key generation, encrypt, decrypt)
- Discrete logarithm (baby-step giant-step)
- Diffie-Hellman key exchange
- Hash functions: FNV-1a and SHA-256 (via hashlib)
- Fermat's little theorem and Euler's theorem
"""

from __future__ import annotations

import hashlib
import math
import random


# ===========================================================================
# Modular arithmetic
# ===========================================================================

def mod_pow(base: int, exponent: int, modulus: int) -> int:
    """Modular exponentiation: (base^exponent) mod modulus.

    Efficient O(log exponent) using binary exponentiation.
    This is the fundamental operation in RSA and Diffie-Hellman.
    """
    if modulus == 1:
        return 0
    result = 1
    base = base % modulus
    while exponent > 0:
        if exponent & 1:
            result = (result * base) % modulus
        exponent >>= 1
        base = (base * base) % modulus
    return result


def modular_inverse(a: int, m: int) -> int:
    """Modular inverse of a mod m using the extended Euclidean algorithm.

    Returns x such that (a * x) % m == 1.
    Raises ValueError if no inverse exists (a and m not coprime).
    """
    g, x, _ = extended_gcd(a, m)
    if g != 1:
        raise ValueError(f"No modular inverse: gcd({a}, {m}) = {g} != 1")
    return (x % m + m) % m


def euler_phi(n: int) -> int:
    """Euler's totient function φ(n): count of integers < n coprime to n.

    Uses the prime factorization of n.
    """
    if n < 2:
        return 0
    result = n
    p = 2
    temp = n
    while p * p <= temp:
        if temp % p == 0:
            while temp % p == 0:
                temp //= p
            result -= result // p
        p += 1
    if temp > 1:
        result -= result // temp
    return result


def fermat_little_theorem(a: int, p: int) -> bool:
    """Check Fermat's little theorem: a^(p-1) ≡ 1 (mod p) for prime p.

    A quick primality test: if it fails, p is definitely composite.
    Note: passing this test does NOT prove p is prime (Carmichael numbers).
    """
    if p <= 1:
        return False
    if a % p == 0:
        return True  # 0^(p-1) ≡ 0 ≡ 1 only if p=1, but p>1 here
    return mod_pow(a, p - 1, p) == 1


def euler_theorem(a: int, n: int) -> bool:
    """Check Euler's theorem: a^φ(n) ≡ 1 (mod n) when gcd(a,n)=1."""
    if math.gcd(a, n) != 1:
        return False
    return mod_pow(a, euler_phi(n), n) == 1


# ===========================================================================
# GCD and extended Euclidean
# ===========================================================================

def gcd(a: int, b: int) -> int:
    """Greatest common divisor via Euclid's algorithm."""
    while b:
        a, b = b, a % b
    return abs(a)


def extended_gcd(a: int, b: int) -> tuple[int, int, int]:
    """Extended Euclidean algorithm.

    Returns (g, x, y) such that a*x + b*y = g = gcd(a, b).
    """
    if b == 0:
        return abs(a), (1 if a >= 0 else -1), 0
    g, x1, y1 = extended_gcd(b, a % b)
    x = y1
    y = x1 - (a // b) * y1
    return g, x, y


# ===========================================================================
# Primality testing
# ===========================================================================

def is_prime_trial(n: int) -> bool:
    """Trial division primality test. O(sqrt(n))."""
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0:
        return False
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True


def miller_rabin(n: int, k: int = 20) -> bool:
    """Miller-Rabin probabilistic primality test.

    Returns True if n is probably prime, False if definitely composite.
    With k=20 rounds, the error probability is < 10^-6.
    """
    if n < 2:
        return False
    if n == 2 or n == 3:
        return True
    if n % 2 == 0:
        return False

    # Write n-1 as d * 2^s
    s = 0
    d = n - 1
    while d % 2 == 0:
        d //= 2
        s += 1

    rng = random.Random(42)  # deterministic for reproducibility
    for _ in range(k):
        a = rng.randint(2, n - 2)
        x = mod_pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(s - 1):
            x = mod_pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def find_prime(bits: int, k: int = 20, seed: int | None = None) -> int:
    """Find a random prime number with the given number of bits.

    Uses a deterministic seed for reproducibility. Pass different
    seeds for different primes.
    """
    if seed is None:
        seed = 42
    rng = random.Random(seed)
    lower = 1 << (bits - 1)
    upper = 1 << bits
    while True:
        n = rng.randint(lower, upper - 1)
        if n % 2 == 1 and miller_rabin(n, k):
            return n


# ===========================================================================
# Modular square roots (Tonelli-Shanks)
# ===========================================================================

def tonelli_shanks(n: int, p: int) -> tuple[int, int] | None:
    """Tonelli-Shanks algorithm: find square roots of n mod prime p.

    Returns (r, p-r) where r^2 ≡ n (mod p), or None if n is a
    quadratic non-residue.
    """
    if n % p == 0:
        return (0, 0)
    if p == 2:
        return (n % p, n % p)

    # Check Euler's criterion: n^((p-1)/2) ≡ 1 (mod p)
    if mod_pow(n, (p - 1) // 2, p) != 1:
        return None

    # Factor p-1 = Q * 2^S
    s = 0
    q = p - 1
    while q % 2 == 0:
        q //= 2
        s += 1

    # Find a quadratic non-residue z
    z = 2
    while mod_pow(z, (p - 1) // 2, p) != p - 1:
        z += 1

    m = s
    c = mod_pow(z, q, p)
    t = mod_pow(n, q, p)
    r = mod_pow(n, (q + 1) // 2, p)

    while t != 1:
        # Find the smallest i such that t^(2^i) ≡ 1
        i = 0
        temp = t
        while temp != 1:
            temp = mod_pow(temp, 2, p)
            i += 1

        b = mod_pow(c, 1 << (m - i - 1), p)
        m = i
        c = mod_pow(b, 2, p)
        t = (t * c) % p
        r = (r * b) % p

    return (r, (p - r) % p)


# ===========================================================================
# RSA
# ===========================================================================

class RSA:
    """RSA public-key encryption (study implementation).

    Key generation:
        1. Choose two large primes p and q
        2. n = p * q
        3. φ = (p-1)(q-1)
        4. Choose e with 1 < e < φ, gcd(e, φ) = 1
        5. d = e^(-1) mod φ

    Encryption: c = m^e mod n
    Decryption: m = c^d mod n
    """

    def __init__(self):
        self.p: int = 0
        self.q: int = 0
        self.n: int = 0
        self.e: int = 0
        self.d: int = 0
        self.phi: int = 0

    def generate_keys(self, bits: int = 64, e: int = 65537) -> "RSA":
        """Generate RSA key pair with primes of the given bit size."""
        self.p = find_prime(bits, seed=42)
        self.q = find_prime(bits, seed=137)
        if self.p == self.q:
            self.q = find_prime(bits, seed=999)

        self.n = self.p * self.q
        self.phi = (self.p - 1) * (self.q - 1)
        self.e = e
        # Ensure gcd(e, phi) = 1
        if math.gcd(self.e, self.phi) != 1:
            # Find a suitable e
            for candidate in range(3, self.phi, 2):
                if math.gcd(candidate, self.phi) == 1:
                    self.e = candidate
                    break
        self.d = modular_inverse(self.e, self.phi)
        return self

    def encrypt(self, message: int) -> int:
        """Encrypt a message (integer < n)."""
        if message >= self.n:
            raise ValueError("Message too large for this key size")
        return mod_pow(message, self.e, self.n)

    def decrypt(self, ciphertext: int) -> int:
        """Decrypt a ciphertext."""
        return mod_pow(ciphertext, self.d, self.n)

    def encrypt_bytes(self, data: bytes) -> list[int]:
        """Encrypt a byte string by converting to an integer."""
        msg = int.from_bytes(data, "big")
        return [self.encrypt(msg)]

    def decrypt_bytes(self, ciphertexts: list[int]) -> bytes:
        """Decrypt a list of ciphertexts back to bytes."""
        msg = self.decrypt(ciphertexts[0])
        byte_length = (self.n.bit_length() + 7) // 8
        return msg.to_bytes(byte_length, "big")


# ===========================================================================
# Discrete logarithm (baby-step giant-step)
# ===========================================================================

def baby_step_giant_step(g: int, h: int, p: int) -> int | None:
    """Baby-step giant-step algorithm for discrete logarithm.

    Finds x such that g^x ≡ h (mod p).
    Returns None if no solution exists.
    O(sqrt(p)) time and space.
    """
    if p <= 1:
        return None

    m = int(math.isqrt(p)) + 1

    # Baby steps: g^j for j = 0, 1, ..., m-1
    baby: dict[int, int] = {}
    gj = 1
    for j in range(m):
        if gj not in baby:
            baby[gj] = j
        gj = (gj * g) % p

    # Giant step factor
    g_m = mod_pow(g, m * (p - 2), p)  # g^(-m) using Fermat
    # Actually g^(-m) mod p = g^(p-1-m) mod p
    g_m = mod_pow(g, (p - 1) - m, p)

    gamma = h
    for i in range(m):
        if gamma in baby:
            x = i * m + baby[gamma]
            if mod_pow(g, x, p) == h:
                return x
        gamma = (gamma * g_m) % p

    return None


# ===========================================================================
# Diffie-Hellman key exchange
# ===========================================================================

def diffie_hellman_shared(g: int, p: int, private_a: int, private_b: int) -> int:
    """Simulate Diffie-Hellman key exchange.

    Alice computes A = g^a mod p, Bob computes B = g^b mod p.
    Alice computes s = B^a mod p, Bob computes s = A^b mod p.
    Both get the same shared secret s = g^(ab) mod p.
    """
    a_public = mod_pow(g, private_a, p)
    b_public = mod_pow(g, private_b, p)

    alice_shared = mod_pow(b_public, private_a, p)
    bob_shared = mod_pow(a_public, private_b, p)

    if alice_shared != bob_shared:
        raise RuntimeError("Shared secrets don't match!")
    return alice_shared


# ===========================================================================
# Hash functions
# ===========================================================================

def fnv1a_32(data: bytes) -> int:
    """FNV-1a 32-bit hash. Simple, fast, used in many systems."""
    h = 0x811c9dc5
    for byte in data:
        h ^= byte
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def fnv1a_64(data: bytes) -> int:
    """FNV-1a 64-bit hash."""
    h = 0xcbf29ce484222325
    for byte in data:
        h ^= byte
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def sha256_hex(data: bytes) -> str:
    """SHA-256 hash (via hashlib). Returns hex digest."""
    return hashlib.sha256(data).hexdigest()


def sha256_int(data: bytes) -> int:
    """SHA-256 hash as an integer."""
    return int(hashlib.sha256(data).hexdigest(), 16)


def __all__() -> list[str]:
    return [
        "mod_pow", "modular_inverse", "euler_phi",
        "fermat_little_theorem", "euler_theorem",
        "gcd", "extended_gcd",
        "is_prime_trial", "miller_rabin", "find_prime",
        "tonelli_shanks", "RSA", "baby_step_giant_step",
        "diffie_hellman_shared", "fnv1a_32", "fnv1a_64",
        "sha256_hex", "sha256_int",
    ]
