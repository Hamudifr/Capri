"""Tests for the time series training module."""

from __future__ import annotations

import math
import unittest

from research.training.timeseries import (
    ARMAModel,
    adf_test,
    ar_predict,
    ar_yule_walker,
    autocorrelation,
    autocorrelation_function,
    exponential_moving_average,
    linear_detrend,
    ma_theoretical_acf,
    mean,
    partial_autocorrelation,
    seasonal_decompose,
    simple_moving_average,
    variance,
    weighted_moving_average,
)


class TestMovingAverages(unittest.TestCase):
    def test_simple_moving_average(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = simple_moving_average(data, window=3)
        self.assertTrue(math.isnan(result[0]))
        self.assertTrue(math.isnan(result[1]))
        self.assertAlmostEqual(result[2], 2.0)
        self.assertAlmostEqual(result[3], 3.0)
        self.assertAlmostEqual(result[4], 4.0)

    def test_exponential_moving_average(self):
        data = [1.0, 2.0, 3.0, 4.0]
        result = exponential_moving_average(data, alpha=0.5)
        self.assertEqual(len(result), 4)
        self.assertAlmostEqual(result[0], 1.0)
        # EMA = 0.5 * 2 + 0.5 * 1 = 1.5
        self.assertAlmostEqual(result[1], 1.5)

    def test_weighted_moving_average(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        weights = [1.0, 2.0, 3.0]
        result = weighted_moving_average(data, weights)
        self.assertTrue(math.isnan(result[0]))
        self.assertTrue(math.isnan(result[1]))
        # (1*1 + 2*2 + 3*3) / 6 = 14/6
        self.assertAlmostEqual(result[2], 14.0 / 6.0)


class TestAutocorrelation(unittest.TestCase):
    def test_autocorrelation_lag_zero(self):
        data = [1.0, 2.0, 3.0, 4.0]
        self.assertAlmostEqual(autocorrelation(data, 0), 1.0)

    def test_autocorrelation_constant(self):
        # Constant series has ACF = 1 for all lags (degenerate)
        data = [5.0, 5.0, 5.0, 5.0]
        self.assertAlmostEqual(autocorrelation(data, 1), 0.0)

    def test_autocorrelation_function(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        acf = autocorrelation_function(data, 3)
        self.assertEqual(len(acf), 4)
        self.assertAlmostEqual(acf[0], 1.0)

    def test_partial_autocorrelation(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        pacf1 = partial_autocorrelation(data, 1)
        self.assertAlmostEqual(pacf1, autocorrelation(data, 1), places=5)

    def test_mean_variance(self):
        self.assertAlmostEqual(mean([1.0, 2.0, 3.0]), 2.0)
        self.assertAlmostEqual(variance([1.0, 2.0, 3.0]), 2.0 / 3.0)


class TestAR(unittest.TestCase):
    def test_ar_predict_simple(self):
        phi = [0.5]
        history = [1.0, 2.0]
        preds = ar_predict(phi, history, steps=2)
        # pred1 = 0.5 * 2.0 = 1.0
        self.assertAlmostEqual(preds[0], 1.0)
        # pred2 = 0.5 * 1.0 = 0.5
        self.assertAlmostEqual(preds[1], 0.5)

    def test_ar_yule_walker(self):
        # AR(1) process: y_t = 0.7 * y_{t-1}
        import random
        rng = random.Random(42)
        data = []
        y = 0.0
        for _ in range(200):
            y = 0.7 * y + rng.uniform(-1, 1)
            data.append(y)

        phi = ar_yule_walker(data, order=1)
        self.assertEqual(len(phi), 1)
        # Should be close to 0.7
        self.assertGreater(phi[0], 0.5)
        self.assertLess(phi[0], 0.9)

    def test_ar_yule_walker_order2(self):
        phi = ar_yule_walker([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], order=2)
        self.assertEqual(len(phi), 2)


class TestMA(unittest.TestCase):
    def test_ma_theoretical_acf_cutoff(self):
        # MA(1) with theta = [0.5]
        acf = ma_theoretical_acf([0.5], max_lag=3)
        # ACF at lag 0 = 1
        self.assertAlmostEqual(acf[0], 1.0)
        # ACF at lag 1 should be non-zero
        self.assertNotAlmostEqual(acf[1], 0.0)
        # ACF at lag 2 should be 0 (cutoff)
        self.assertAlmostEqual(acf[2], 0.0)
        self.assertAlmostEqual(acf[3], 0.0)


class TestARMA(unittest.TestCase):
    def test_arma_forecast(self):
        model = ARMAModel(p=2, q=0)
        data = [float(i) for i in range(20)]
        model.fit(data)
        preds = model.forecast(data, steps=3)
        self.assertEqual(len(preds), 3)


class TestStationarity(unittest.TestCase):
    def test_adf_stationary(self):
        # A stationary AR(1) process should have a negative ADF statistic
        import random
        rng = random.Random(42)
        data = []
        y = 0.0
        for _ in range(100):
            y = 0.3 * y + rng.uniform(-1, 1)
            data.append(y)
        stat = adf_test(data, max_lag=2)
        self.assertLess(stat, 0)

    def test_adf_unit_root(self):
        # A random walk (unit root) should have a less negative ADF
        import random
        rng = random.Random(42)
        data = []
        y = 0.0
        for _ in range(100):
            y = y + rng.uniform(-1, 1)
            data.append(y)
        stat = adf_test(data, max_lag=2)
        self.assertLess(stat, 1.0)


class TestDetrending(unittest.TestCase):
    def test_linear_detrend(self):
        # Linear trend: y = 2*t + 1
        data = [2.0 * i + 1.0 for i in range(10)]
        residuals = linear_detrend(data)
        # Residuals should be nearly zero
        for r in residuals:
            self.assertAlmostEqual(r, 0.0, places=6)

    def test_seasonal_decompose(self):
        # Data with a clear seasonal pattern
        data = []
        for i in range(48):
            data.append(10.0 * math.sin(2.0 * math.pi * i / 12) + 50.0)
        trend, seasonal, residual = seasonal_decompose(data, period=12)
        self.assertEqual(len(trend), len(data))
        self.assertEqual(len(seasonal), len(data))
        self.assertEqual(len(residual), len(data))


if __name__ == "__main__":
    unittest.main()
