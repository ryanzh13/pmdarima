# -*- coding: utf-8 -*-
#
# Author: Taylor Smith <taylor.smith@alkaline-ml.com>
#
# Tests for stationarity

from __future__ import absolute_import, division
from sklearn.base import BaseEstimator
from sklearn.utils.validation import column_or_1d, check_array
from sklearn.linear_model import LinearRegression
from sklearn.externals import six
from statsmodels import api as sm
from abc import ABCMeta, abstractmethod
import numpy as np

from ..compat.numpy import DTYPE
from ..utils.array import c, diff
from .approx import approx

# since the C import relies on the C code having been built with Cython,
# and since pyramid never plans to use setuptools for the 'develop' option,
# make this an absolute import.
from pyramid.arima._arima import C_tseries_pp_sum

__all__ = [
    'ADFTest',
    'KPSSTest',
    'PPTest'
]


class _BaseStationarityTest(six.with_metaclass(ABCMeta, BaseEstimator)):
    @staticmethod
    def _base_case(x):
        # if x is empty, return false so the other methods return False
        if (x is None) or (x.shape[0] == 0):
            return False
        return True

    @staticmethod
    def _embed(x, k):
        # lag the vector and put the lags into columns
        n = x.shape[0]
        rows = [
            # so, if k=2, it'll be (x[1:n], x[:n-1])
            x[j:n - i] for i, j in enumerate(range(k - 1, -1, -1))
        ]
        return np.asarray(rows)
        # return np.array([x[1:], x[:m]])


class _DifferencingStationarityTest(six.with_metaclass(ABCMeta, _BaseStationarityTest)):
    """Provides the base class for stationarity tests such as the
    Kwiatkowski–Phillips–Schmidt–Shin, Augmented Dickey-Fuller and the
    Phillips–Perron tests. These tests are used to determine whether a time
    series is stationary.
    """
    def __init__(self, alpha):
        self.alpha = alpha

    @abstractmethod
    def is_stationary(self, x):
        """Test whether the time series is stationary.

        Parameters
        ----------
        x : array-like, shape=(n_samples,)
            The time series vector.
        """


class KPSSTest(_DifferencingStationarityTest):
    """In econometrics, Kwiatkowski–Phillips–Schmidt–Shin (KPSS) tests are used
    for testing a null hypothesis that an observable time series is stationary
    around a deterministic trend (i.e. trend-stationary) against the alternative
    of a unit root.


    Parameters
    ----------
    alpha : float, optional (default=0.05)
        Level of the test

    null : str, optional (default='level')
        Whether to fit the linear model on the one vector, or an arange.
        If ``null`` is 'trend', a linear model is fit on an arange, if
        'level', it is fit on the one vector.

    lshort : bool, optional (default=True)
        Whether or not to truncate the ``l`` value in the C code.


    References
    ----------
    [1] https://github.com/cran/tseries/blob/8ceb31fa77d0b632dd511fc70ae2096fa4af3537/R/test.R#L719
    """
    _valid = {'trend', 'null'}

    def __init__(self, alpha=0.05, null='level', lshort=True):
        super(KPSSTest, self).__init__(alpha=alpha)

        self.null = null
        self.lshort = lshort

    def is_stationary(self, x):
        if not self._base_case(x):
            return np.nan, False

        # ensure vector
        x = column_or_1d(check_array(x, ensure_2d=False, dtype=DTYPE, force_all_finite=True))
        n = x.shape[0]

        # check on status of null
        null = self.null

        # fit a model on an arange to determine the residuals
        if null == 'trend':
            t = np.arange(n).reshape(n, 1)

            # these numbers came out of the R code.. I've found NO doc for these...
            table = c(0.216, 0.176, 0.146, 0.119)
        elif null == 'level':
            t = np.ones(n).reshape(n, 1)

            # these numbers came out of the R code.. I've found NO doc for these...
            table = c(0.739, 0.574, 0.463, 0.347)
        else:
            raise ValueError("null must be one of %r" % self._valid)

        # fit the model
        lm = LinearRegression().fit(t, x)
        e = x - lm.predict(t)  # residuals
        tablep = c(0.01, 0.025, 0.05, 0.10)

        s = np.cumsum(e)
        eta = (s * s).sum() / (n**2)
        s2 = (e * e).sum() / n

        scalar, denom = 10, 14
        if self.lshort:
            scalar, denom = 3, 13
        l = int(np.trunc(scalar * np.sqrt(n) / denom))

        # compute the C subroutine
        s2 = C_tseries_pp_sum(e, n, l, s2)
        stat = eta / s2

        # do approximation
        _, pval = approx(table, tablep, xout=stat, rule=2)

        # R does a test for rule=1, but we don't want to do that, because they
        # just do it to issue a warning in case the P-value is smaller/greater than
        # the printed value is.
        return pval[0], pval[0] < self.alpha


class ADFTest(_DifferencingStationarityTest):
    """In statistics and econometrics, an augmented Dickey–Fuller test (ADF) tests
    the null hypothesis of a unit root is present in a time series sample. The alternative
    hypothesis is different depending on which version of the test is used, but is usually
    stationarity or trend-stationarity. It is an augmented version of the Dickey–Fuller test
    for a larger and more complicated set of time series models.


    Parameters
    ----------
    alpha : float, optional (default=0.05)
        Level of the test

    k : int, optional (default=None)
        The drift parameter. If ``k`` is None, it will be set to:
        ``np.trunc(np.power(x.shape[0] - 1, 1 / 3.0))``


    Notes
    -----
    * ADF test does not perform as reliably to the R code as do the KPSS and PP tests.
      This is due to the fact that is has to use statsmodels OLS regression for std err
      estimates rather than the more robust sklearn LinearRegression.


    References
    ----------
    [1] https://en.wikipedia.org/wiki/Augmented_Dickey–Fuller_test
    """

    def __init__(self, alpha=0.05, k=None):
        super(ADFTest, self).__init__(alpha=alpha)

        self.k = k
        if k is not None and k < 0:
            raise ValueError('k must be a positive integer (>= 0)')

    def is_stationary(self, x):
        if not self._base_case(x):
            return np.nan, False

        # ensure vector
        x = column_or_1d(check_array(x, ensure_2d=False, dtype=DTYPE, force_all_finite=True))

        # if k is none...
        k = self.k
        if k is None:
            k = np.trunc(np.power(x.shape[0] - 1, 1 / 3.0))

        k = int(k) + 1
        y = diff(x)
        n = y.shape[0]
        z = self._embed(y, k)
        yt = z[0, :]
        tt = np.arange(k - 1, n)
        xt1 = x[tt]  # R does [k:n]... but that's 1-based indexing and inclusive on the tail...

        # make tt inclusive again (it was used as a mask before)
        tt += 1

        # the array that will create the LM:
        _n = xt1.shape[0]
        X = np.hstack([xt1.reshape((_n, 1)), np.ones(_n).reshape((_n, 1)), tt.reshape((_n, 1))])
        if k > 1:
            yt1 = z[1:k, :]  # R had 2:k
            X = np.hstack([X, yt1.T])

        # fit the linear regression - this one is a bit strange in that we are using
        # OLS from statsmodels rather than LR from sklearn. This is because we need
        # the std errors, and sklearn does not have a way to store them.
        res = sm.OLS(yt, X).fit()
        STAT = res.params[0] / res.HC0_se[0]  # FIXME: is the denominator correct?...
        table = -np.array([c(4.38, 4.15, 4.04, 3.99, 3.98, 3.96),
                           c(3.95, 3.80, 3.73, 3.69, 3.68, 3.66),
                           c(3.60, 3.50, 3.45, 3.43, 3.42, 3.41),
                           c(3.24, 3.18, 3.15, 3.13, 3.13, 3.12),
                           c(1.14, 1.19, 1.22, 1.23, 1.24, 1.25),
                           c(0.80, 0.87, 0.90, 0.92, 0.93, 0.94),
                           c(0.50, 0.58, 0.62, 0.64, 0.65, 0.66),
                           c(0.15, 0.24, 0.28, 0.31, 0.32, 0.33)]).T

        tablen = table.shape[1]
        tableT = c(25, 50, 100, 250, 500, 100000)
        tablep = c(0.01, 0.025, 0.05, 0.10, 0.90, 0.95, 0.975, 0.99)

        tableipl = np.zeros(tablen)
        for i in range(tablen):
            _, pval = approx(tableT, table[:, i], xout=n, rule=2)
            tableipl[i] = pval

        # make sure to do 1 - x...
        _, interpol = approx(tableipl, tablep, xout=STAT, rule=2)
        pval = 1 - interpol[0]

        # in the R code, here is where the P value warning is tested again...
        return pval, pval < self.alpha


class PPTest(_DifferencingStationarityTest):
    """In statistics, the Phillips–Perron test (named after Peter C. B. Phillips
    and Pierre Perron) is a unit root test. It is used in time series analysis to test the null
    hypothesis that a time series is integrated of order 1. It builds on the Dickey–Fuller test
    of the null hypothesis ``p = 0``.

    The R code allows for two types of test: 'Z(alpha)' and 'Z(t_alpha)'. Since sklearn
    does not allow extraction of std errors from the lm fit, t_alpha is much more difficult
    to achieve... so don't allow that variant.


    Parameters
    ----------
    alpha : float, optional (default=0.05)
        Level of the test

    lshort : bool, optional (default=True)
        Whether or not to truncate the ``l`` value in the C code.


    References
    ----------
    [1] https://github.com/cran/tseries/blob/8ceb31fa77d0b632dd511fc70ae2096fa4af3537/R/test.R#L549
    """
    def __init__(self, alpha=0.05, lshort=True):
        super(PPTest, self).__init__(alpha=alpha)

        self.lshort = lshort

    def is_stationary(self, x):
        if not self._base_case(x):
            return np.nan, False

        # ensure vector
        x = column_or_1d(check_array(x, ensure_2d=False, dtype=DTYPE, force_all_finite=True))

        # embed the vector. This is some funkiness that goes on in the R code...
        # basically, make a matrix where the column (rows if not T) are lagged windows of x
        z = self._embed(x, 2)
        yt = z[0, :]
        yt1 = z[1, :]

        # fit a linear model to a predictor matrix
        n = yt.shape[0]
        tt = (np.arange(n) + 1) - (n / 2.0)
        X = np.array([np.ones(n), tt, yt1]).T
        res = LinearRegression().fit(X, yt)  # lm(yt ~ 1 + tt + yt1)
        coef = res.coef_

        # check for singularities - do we want to do this??? in the R code, it happens.
        # but the very same lm in the R code is rank 3, and here it is rank 2. Should
        # we just ignore?...
        # if res.rank_ < 3:
        #     raise ValueError('singularities in regression')

        u = yt - res.predict(X)  # residuals
        ssqru = (u * u).sum() / float(n)

        scalar = 12 if not self.lshort else 4
        l = int(np.trunc(scalar * np.power(n / 100.0, 0.25)))
        ssqrtl = C_tseries_pp_sum(u, n, l, ssqru)

        # define trm vals
        n2 = n * n
        syt11n = (yt1 * (np.arange(n) + 1)).sum()  # sum(yt1*(1:n))
        trm1 = n2 * (n2 - 1) * (yt1 ** 2).sum() / 12.0
        trm2 = n * (syt11n ** 2)  # n*sum(yt1*(1:n))^2
        trm3 = n * (n + 1) * syt11n * yt1.sum()  # n*(n+1)*sum(yt1*(1:n))*sum(yt1)
        trm4 = (n * (n + 1) * (2 * n + 1) * (yt1.sum() ** 2)) / 6.0
        dx = trm1 - trm2 + trm3 - trm4

        # if self.typ == 'alpha':
        alpha = coef[2]  # it's the last col...
        STAT = n * (alpha - 1) - (n ** 6) / (24.0 * dx) * (ssqrtl - ssqru)

        table = -np.array([
            c(22.5, 25.7, 27.4, 28.4, 28.9, 29.5),
            c(19.9, 22.4, 23.6, 24.4, 24.8, 25.1),
            c(17.9, 19.8, 20.7, 21.3, 21.5, 21.8),
            c(15.6, 16.8, 17.5, 18.0, 18.1, 18.3),
            c(3.66, 3.71, 3.74, 3.75, 3.76, 3.77),
            c(2.51, 2.60, 2.62, 2.64, 2.65, 2.66),
            c(1.53, 1.66, 1.73, 1.78, 1.78, 1.79),
            c(0.43, 0.65, 0.75, 0.82, 0.84, 0.87)
        ]).T

        tablen = table.shape[1]
        tableT = c(25, 50, 100, 250, 500, 100000).astype(DTYPE)
        tablep = c(0.01, 0.025, 0.05, 0.10, 0.90, 0.95, 0.975, 0.99)
        tableipl = np.zeros(tablen)

        for i in range(tablen):
            _, pval = approx(tableT, table[:, i], xout=n, rule=2)
            tableipl[i] = pval

        # make sure to do 1 - x...
        _, interpol = approx(tableipl, tablep, xout=STAT, rule=2)
        pval = 1 - interpol[0]

        # in the R code, here is where the P value warning is tested again...
        return pval, pval < self.alpha
