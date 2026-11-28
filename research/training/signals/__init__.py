"""Signal processing study modules."""

from research.training.signals.processing import (
    dft, idft, fft, ifft, next_power_of_two,
    fft_magnitude, convolve, convolve_fft,
    circular_convolve, moving_average_filter, fir_filter,
    cross_correlation, auto_correlation,
    freq_bins, dominant_frequency,
)

__all__ = [
    "dft", "idft", "fft", "ifft", "next_power_of_two",
    "fft_magnitude", "convolve", "convolve_fft",
    "circular_convolve", "moving_average_filter", "fir_filter",
    "cross_correlation", "auto_correlation",
    "freq_bins", "dominant_frequency",
]
