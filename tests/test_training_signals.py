"""Tests for the signal processing training module."""

import unittest
import math

from research.training.signals.processing import (
    dft, idft, fft, ifft, next_power_of_two,
    fft_magnitude, convolve, convolve_fft,
    circular_convolve, moving_average_filter, fir_filter,
    cross_correlation, auto_correlation,
    freq_bins, dominant_frequency,
)


class TestFourierTransform(unittest.TestCase):

    def test_dft_basic(self):
        # DFT of [1, 0, 0, 0] is [1, 1, 1, 1]
        signal = [1, 0, 0, 0]
        spectrum = dft([complex(x, 0) for x in signal])
        for c in spectrum:
            self.assertAlmostEqual(abs(c), 1.0, places=6)

    def test_idft_roundtrip(self):
        signal = [1.0, 2.0, 3.0, 4.0]
        spectrum = dft([complex(x, 0) for x in signal])
        reconstructed = idft(spectrum)
        for i, x in enumerate(signal):
            self.assertAlmostEqual(reconstructed[i].real, x, places=6)
            self.assertAlmostEqual(reconstructed[i].imag, 0.0, places=6)

    def test_fft_matches_dft(self):
        # FFT should match DFT for power-of-2 inputs
        signal = [1.0, 2.0, 3.0, 4.0]
        dft_result = dft([complex(x, 0) for x in signal])
        fft_result = fft([complex(x, 0) for x in signal])
        for a, b in zip(dft_result, fft_result):
            self.assertAlmostEqual(abs(a), abs(b), places=4)
            self.assertAlmostEqual(a.real, b.real, places=4)
            self.assertAlmostEqual(a.imag, b.imag, places=4)

    def test_fft_zero_padded(self):
        # FFT with non-power-of-2 should zero-pad
        signal = [1.0, 2.0, 3.0]
        result = fft([complex(x, 0) for x in signal])
        self.assertEqual(len(result), 4)

    def test_ifft_roundtrip(self):
        signal = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        spectrum = fft([complex(x, 0) for x in signal])
        reconstructed = ifft(spectrum)
        for i, x in enumerate(signal):
            self.assertAlmostEqual(reconstructed[i].real, x, places=4)

    def test_next_power_of_two(self):
        self.assertEqual(next_power_of_two(1), 1)
        self.assertEqual(next_power_of_two(2), 2)
        self.assertEqual(next_power_of_two(3), 4)
        self.assertEqual(next_power_of_two(5), 8)
        self.assertEqual(next_power_of_two(16), 16)
        self.assertEqual(next_power_of_two(17), 32)

    def test_fft_magnitude(self):
        # FFT magnitude of [1, 1, 1, 1] has DC = 4, others = 0
        mag = fft_magnitude([1.0, 1.0, 1.0, 1.0])
        self.assertAlmostEqual(mag[0], 4.0, places=4)
        self.assertAlmostEqual(mag[1], 0.0, places=4)

    def test_dominant_frequency(self):
        # Signal with a sine wave at frequency 2 (in a 8-sample signal)
        n = 8
        signal = [math.sin(2 * math.pi * 2 * i / n) for i in range(n)]
        freq = dominant_frequency(signal, sample_rate=n)
        self.assertAlmostEqual(freq, 2.0, places=1)


class TestConvolution(unittest.TestCase):

    def test_convolve_basic(self):
        # [1, 2, 3] * [1, 1] = [1, 3, 5, 3]
        result = convolve([1, 2, 3], [1, 1])
        self.assertEqual(result, [1, 3, 5, 3])

    def test_convolve_length(self):
        result = convolve([1, 2, 3], [4, 5])
        self.assertEqual(len(result), 4)  # 3 + 2 - 1

    def test_convolve_empty(self):
        self.assertEqual(convolve([], [1, 2]), [])
        self.assertEqual(convolve([1, 2], []), [])

    def test_convolve_fft_matches(self):
        a = [1.0, 2.0, 3.0, 4.0]
        b = [1.0, 2.0, 1.0]
        direct = convolve(a, b)
        fft_conv = convolve_fft(a, b)
        for x, y in zip(direct, fft_conv):
            self.assertAlmostEqual(x, y, places=4)

    def test_circular_convolve(self):
        # Circular convolution of [1, 2] and [3, 4]:
        # result[0] = 1*3 + 2*4 = 11, result[1] = 1*4 + 2*3 = 10
        result = circular_convolve([1, 2], [3, 4])
        self.assertEqual(result, [11, 10])

    def test_circular_convolve_length_check(self):
        with self.assertRaises(ValueError):
            circular_convolve([1, 2], [3])


class TestFiltering(unittest.TestCase):

    def test_moving_average(self):
        signal = [1, 2, 3, 4, 5]
        result = moving_average_filter(signal, window=3)
        # [1, 1.5, 2, 3, 4] (causal, partial windows)
        self.assertEqual(len(result), 5)
        self.assertAlmostEqual(result[0], 1.0)
        self.assertAlmostEqual(result[2], 2.0)
        self.assertAlmostEqual(result[4], 4.0)

    def test_moving_average_invalid(self):
        with self.assertRaises(ValueError):
            moving_average_filter([1, 2, 3], window=0)

    def test_fir_filter(self):
        signal = [1, 2, 3, 4]
        kernel = [1, 0, -1]
        result = fir_filter(signal, kernel)
        # Same as convolution
        self.assertEqual(len(result), 6)

    def test_cross_correlation(self):
        # Cross-correlation of [1, 2, 3] with [1, 1]
        result = cross_correlation([1, 2, 3], [1, 1])
        self.assertEqual(len(result), 4)

    def test_auto_correlation(self):
        signal = [1, 2, 3]
        result = auto_correlation(signal)
        self.assertEqual(len(result), 5)
        # At lag 0, should be sum of squares = 14
        self.assertAlmostEqual(result[2], 14.0, places=6)


class TestFrequencyHelpers(unittest.TestCase):

    def test_freq_bins(self):
        bins = freq_bins(4, 4.0)
        self.assertEqual(bins, [0.0, 1.0, 2.0, 3.0])

    def test_dominant_frequency_constant(self):
        # A constant signal has only DC, so dominant = 0
        signal = [5.0] * 8
        freq = dominant_frequency(signal, sample_rate=8.0)
        self.assertEqual(freq, 0.0)


if __name__ == "__main__":
    unittest.main()
