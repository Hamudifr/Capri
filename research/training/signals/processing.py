"""Signal processing study modules.

Implements core concepts in digital signal processing: the discrete
Fourier transform, FFT, convolution, and filtering.
Pure stdlib, no dependencies.

Topics covered:
- Discrete Fourier Transform (DFT)
- Fast Fourier Transform (FFT, radix-2 Cooley-Tukey)
- Inverse FFT
- Convolution (linear and circular)
- FIR filtering
- Moving average filter
- Cross-correlation
- Zero-padding and frequency resolution
"""

from __future__ import annotations

import math


# ===========================================================================
# Discrete Fourier Transform
# ===========================================================================

def dft(signal: list[complex]) -> list[complex]:
    """Discrete Fourier Transform.

    X[k] = sum_{n=0}^{N-1} x[n] * exp(-2*pi*i*k*n/N)

    O(N^2) — used for study and small inputs.
    """
    n = len(signal)
    if n == 0:
        return []

    result = []
    for k in range(n):
        total = 0.0 + 0.0j
        for n_idx in range(n):
            angle = -2 * math.pi * k * n_idx / n
            w = complex(math.cos(angle), math.sin(angle))
            total += signal[n_idx] * w
        result.append(total)
    return result


def idft(spectrum: list[complex]) -> list[complex]:
    """Inverse Discrete Fourier Transform.

    x[n] = (1/N) * sum_{k=0}^{N-1} X[k] * exp(+2*pi*i*k*n/N)
    """
    n = len(spectrum)
    if n == 0:
        return []

    result = []
    for n_idx in range(n):
        total = 0.0 + 0.0j
        for k in range(n):
            angle = 2 * math.pi * k * n_idx / n
            w = complex(math.cos(angle), math.sin(angle))
            total += spectrum[k] * w
        result.append(total / n)
    return result


# ===========================================================================
# Fast Fourier Transform (radix-2 Cooley-Tukey)
# ===========================================================================

def next_power_of_two(n: int) -> int:
    """Smallest power of two >= n."""
    if n <= 1:
        return 1
    return 1 << (n - 1).bit_length()


def fft(signal: list[complex]) -> list[complex]:
    """Fast Fourier Transform using the radix-2 Cooley-Tukey algorithm.

    Requires the input length to be a power of two. If not, the
    signal is zero-padded to the next power of two.
    O(N log N).
    """
    n = len(signal)
    if n == 0:
        return []

    # Zero-pad to next power of two
    padded_n = next_power_of_two(n)
    if padded_n != n:
        signal = list(signal) + [0.0 + 0.0j] * (padded_n - n)

    # Bit-reversal permutation
    bits = padded_n.bit_length() - 1
    signal = [signal[_bit_reverse(i, bits)] for i in range(padded_n)]

    # Butterfly operations
    length = 2
    while length <= padded_n:
        half = length // 2
        angle = -2 * math.pi / length
        w_step = complex(math.cos(angle), math.sin(angle))

        for start in range(0, padded_n, length):
            w = 1.0 + 0.0j
            for k in range(half):
                u = signal[start + k]
                v = signal[start + k + half] * w
                signal[start + k] = u + v
                signal[start + k + half] = u - v
                w *= w_step
        length *= 2

    return signal


def ifft(spectrum: list[complex]) -> list[complex]:
    """Inverse Fast Fourier Transform.

    x = conj(fft(conj(X))) / N
    """
    n = len(spectrum)
    if n == 0:
        return []

    # Take conjugate, FFT, conjugate again, divide by N
    conjugated = [c.conjugate() for c in spectrum]
    result = fft(conjugated)
    result = [c.conjugate() / n for c in result]
    return result


def _bit_reverse(n: int, bit_length: int) -> int:
    """Reverse the bits of n within bit_length bits."""
    result = 0
    for i in range(bit_length):
        if n & (1 << i):
            result |= 1 << (bit_length - 1 - i)
    return result


def fft_magnitude(signal: list[float]) -> list[float]:
    """FFT of a real signal, returning the magnitude spectrum."""
    spectrum = fft([complex(x, 0) for x in signal])
    return [abs(c) for c in spectrum]


# ===========================================================================
# Convolution
# ===========================================================================

def convolve(signal_a: list[float], signal_b: list[float]) -> list[float]:
    """Linear convolution of two signals.

    result[n] = sum_{k} a[k] * b[n-k]

    Length of result is len(a) + len(b) - 1.
    """
    if not signal_a or not signal_b:
        return []

    n_a = len(signal_a)
    n_b = len(signal_b)
    result = [0.0] * (n_a + n_b - 1)

    for i in range(n_a):
        for j in range(n_b):
            result[i + j] += signal_a[i] * signal_b[j]

    return result


def convolve_fft(signal_a: list[float], signal_b: list[float]) -> list[float]:
    """Convolution via FFT (circular convolution with zero-padding).

    Zero-pads both signals to avoid circular convolution effects,
    then uses FFT: conv(a,b) = ifft(fft(a) * fft(b)).
    """
    n = next_power_of_two(len(signal_a) + len(signal_b) - 1)

    a_padded = list(signal_a) + [0.0] * (n - len(signal_a))
    b_padded = list(signal_b) + [0.0] * (n - len(signal_b))

    a_fft = fft([complex(x, 0) for x in a_padded])
    b_fft = fft([complex(x, 0) for x in b_padded])

    product = [a * b for a, b in zip(a_fft, b_fft)]
    result = ifft(product)

    return [r.real for r in result[:len(signal_a) + len(signal_b) - 1]]


def circular_convolve(signal_a: list[float], signal_b: list[float]) -> list[float]:
    """Circular convolution of two signals of equal length.

    result[n] = sum_{k=0}^{N-1} a[k] * b[(n-k) mod N]
    """
    n = len(signal_a)
    if n != len(signal_b):
        raise ValueError("Circular convolution requires equal-length signals")

    result = [0.0] * n
    for i in range(n):
        for j in range(n):
            result[i] += signal_a[j] * signal_b[(i - j) % n]
    return result


# ===========================================================================
# Filtering
# ===========================================================================

def moving_average_filter(signal: list[float], window: int) -> list[float]:
    """Moving average filter (boxcar filter).

    Smooths a signal by averaging over a sliding window.
    """
    if window <= 0:
        raise ValueError("Window must be positive")

    n = len(signal)
    result = []

    for i in range(n):
        start = max(0, i - window + 1)
        window_vals = signal[start:i + 1]
        result.append(sum(window_vals) / len(window_vals))

    return result


def fir_filter(signal: list[float],
               kernel: list[float]) -> list[float]:
    """FIR (Finite Impulse Response) filter via convolution.

    The kernel defines the filter coefficients. The output is the
    convolution of the signal with the kernel.
    """
    return convolve(signal, kernel)


def cross_correlation(signal_a: list[float], signal_b: list[float]) -> list[float]:
    """Cross-correlation of two signals.

    (a ⋆ b)[n] = sum_{k} a[k] * b[k+n]

    Result index 0 corresponds to lag = -(len(b)-1), and index
    len(a)-1 corresponds to lag = 0.
    """
    if not signal_a or not signal_b:
        return []

    n_a = len(signal_a)
    n_b = len(signal_b)
    result = [0.0] * (n_a + n_b - 1)
    offset = n_b - 1

    for lag in range(-(n_b - 1), n_a):
        idx = lag + offset
        total = 0.0
        for k in range(n_a):
            j = k + lag
            if 0 <= j < n_b:
                total += signal_a[k] * signal_b[j]
        result[idx] = total

    return result


def auto_correlation(signal: list[float]) -> list[float]:
    """Auto-correlation of a signal (cross-correlation with itself)."""
    return cross_correlation(signal, signal)


# ===========================================================================
# Frequency analysis helpers
# ===========================================================================

def freq_bins(num_bins: int, sample_rate: float) -> list[float]:
    """Generate frequency bin values for a spectrum.

    Returns the frequency (in Hz) for each bin index.
    """
    return [k * sample_rate / num_bins for k in range(num_bins)]


def dominant_frequency(signal: list[float], sample_rate: float = 1.0) -> float:
    """Find the dominant frequency in a signal using FFT.

    Returns the frequency (in Hz) of the bin with maximum magnitude
    (excluding DC component at bin 0).
    """
    spectrum = fft_magnitude(signal)
    n = len(spectrum)
    if n <= 1:
        return 0.0

    # Find the bin with max magnitude, skipping DC (bin 0)
    max_idx = 1
    max_mag = 0.0
    for i in range(1, n // 2):
        if spectrum[i] > max_mag:
            max_mag = spectrum[i]
            max_idx = i

    # If all non-DC bins are zero (constant signal), return 0
    if max_mag == 0.0:
        return 0.0

    return max_idx * sample_rate / n


def __all__() -> list[str]:
    return [
        "dft", "idft", "fft", "ifft", "next_power_of_two",
        "fft_magnitude", "convolve", "convolve_fft",
        "circular_convolve", "moving_average_filter", "fir_filter",
        "cross_correlation", "auto_correlation",
        "freq_bins", "dominant_frequency",
    ]
