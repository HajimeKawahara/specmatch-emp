"""
@filename match.py

Defines the Match class
"""
import pandas as pd
import numpy as np
import lmfit
from scipy.interpolate import LSQUnivariateSpline
from scipy import signal
from scipy.ndimage.filters import convolve1d

import specmatchemp.kernels

class Match:
    def __init__(self, wav, s_targ, s_ref, mode='default', opt='lm'):
        """
        The Match class used for matching two spectra

        Args:
            wav (np.ndarray): Common wavelength scale
            s_targ (np.ndarray): 2d array containing target spectrum and uncertainty
            s_ref (np.ndarray): 2d array containing reference spectrum and uncertainty
            mode: default (unnormalized chi-square), normalized (normalized chi-square)
            opt: lm (Levenberg-Marquadt optimization), nelder (Nelder-Mead)
        """
        self.w = np.copy(wav)
        self.s_targ = np.copy(s_targ[0])
        self.serr_targ = np.copy(s_targ[1])
        self.s_ref = np.copy(s_ref[0])
        self.serr_ref = np.copy(s_ref[1])
        self.best_params = lmfit.Parameters()
        self.best_chisq = np.NaN
        self.mode = mode
        self.opt = opt

        # add spline knots
        num_knots = 5
        interval = int(len(self.w)/(num_knots+1))
        # Add spline positions
        self.knot_x = []
        for i in range(1, num_knots+1):
            self.knot_x.append(self.w[interval*i])
        self.knot_x = np.array(self.knot_x)

    def create_model(self, params):
        """
        Creates a tweaked model based on the parameters passed,
        based on the reference spectrum.
        Stores the tweaked model in spectra.s_mod and serr_mod.
        """
        self.s_mod = np.copy(self.s_ref)
        self.serr_mod = np.copy(self.serr_ref)

        # Apply broadening kernel
        vsini = params['vsini'].value
        self.s_mod = self.broaden(vsini, self.s_mod)
        self.serr_mod = self.broaden(vsini, self.serr_mod)

        # Use linear least squares to fit a spline
        s = LSQUnivariateSpline(self.w, self.s_targ/self.s_mod, self.knot_x)
        self.spl = s(self.w)

        self.s_mod *= self.spl
        self.serr_mod *= self.spl


    def broaden(self, vsini, spec):
        """
        Applies a broadening kernel to the given spectrum (or error)

        Args:
            vsini (float): vsini to determine width of broadening
            spec (np.ndarray): spectrum to broaden
        Returns:
            broadened (np.ndarray): Broadened spectrum
        """
        SPEED_OF_LIGHT = 2.99792e5
        dv = (self.w[1]-self.w[0])/self.w[0]*SPEED_OF_LIGHT
        n = 151 # fixed number of points in the kernel
        varr, kernel = specmatchemp.kernels.rot(n, dv, vsini)
        # broadened = signal.fftconvolve(spec, kernel, mode='same')
        broadened = convolve1d(spec, kernel)

        return broadened


    def objective(self, params):
        """
        Objective function evaluating goodness of fit given the passed parameters

        Args:
            params
        Returns:
            Reduced chi-squared value between the target spectra and the 
            model spectrum generated by the parameters
        """
        self.create_model(params)

        # Calculate residuals (data - model)
        if self.mode == 'normalized':
            residuals = (self.s_targ-self.s_mod)/np.sqrt(self.serr_targ**2+self.serr_mod**2)
        else:
            residuals = (self.s_targ-self.s_mod)

        chi_square = np.sum(residuals**2)

        if self.opt == 'lm':
            return residuals
        elif self.opt == 'nelder':
            return chi_square

    def best_fit(self, params=None):
        """
        Calculates the best fit model by minimizing over the parameters:
        - spline fitting to the continuum
        - rotational broadening
        """
        if params is None:
            params = lmfit.Parameters()

        ### Rotational broadening parameters
        params.add('vsini', value=1.0, min=0.0, max=10.0)

        # Perform fit
        if self.opt == 'lm':
            out = lmfit.minimize(self.objective, params)
            self.best_chisq = np.sum(self.objective(out.params)**2)
        elif self.opt == 'nelder':
            out = lmfit.minimize(self.objective, params, method='nelder')
            self.best_chisq = self.objective(out.params)

        self.best_params = out.params

        return self.best_chisq

    def best_residuals(self):
        """Returns the residuals between the target spectrum and best-fit spectrum
        
        Returns:
            np.ndarray
        """
        if self.mode == 'normalized':
            return (self.s_targ-self.s_mod)/np.sqrt(self.serr_targ**2+self.serr_mod**2)
        else:
            return (self.s_targ-self.s_mod) # data - model


class MatchLincomb(Match):
    def __init__(self, wav, s_targ, s_refs, vsini, mode='default', opt='lm'):
        """
        Match subclass to find the best match from a linear combination of 
        reference spectra.

        Args:
            wav (np.ndarray): Common wavelength scale
            s_targ (np.ndarray): 2d array containing target spectrum and uncertainty
            s_refs (np.ndarray): 3d list containing reference spectra and uncertainty
            vsini (np.ndarray): array containing vsini broadening for each reference spectrum
        """
        self.w = np.copy(wav)
        self.s_targ = np.copy(s_targ[0])
        self.serr_targ = np.copy(s_targ[1])
        self.num_refs = len(s_refs)
        self.s_refs = np.copy(s_refs)

        ## Broaden reference spectra
        for i in range(self.num_refs):
            self.s_refs[i,0] = self.broaden(vsini[i], self.s_refs[i,0])
            self.s_refs[i,1] = self.broaden(vsini[i], self.s_refs[i,1])

        self.best_params = lmfit.Parameters()
        self.best_chisq = np.NaN
        self.mode = mode
        self.opt = opt

        # add spline knots
        num_knots = 5
        interval = int(len(self.w)/(num_knots+1))
        # Add spline positions
        self.knot_x = []
        for i in range(1, num_knots+1):
            self.knot_x.append(self.w[interval*i])
        self.knot_x = np.array(self.knot_x)

    def create_model(self, params):
        """
        Creates a tweaked model based on the parameters passed,
        based on the reference spectrum.
        Stores the tweaked model in spectra.s_mod and serr_mod.
        """
        self.s_mod = np.zeros_like(self.w)
        self.serr_mod = np.zeros_like(self.w)

        # create the model from a linear combination of the reference spectra
        for i in range(self.num_refs):
            p = 'coeff_{0:d}'.format(i)
            self.s_mod += self.s_refs[i,0] * params[p].value
            self.serr_mod += self.s_refs[i,1] * params[p].value

        # Use linear least squares to fit a spline
        s = LSQUnivariateSpline(self.w, self.s_targ/self.s_mod, self.knot_x)
        self.spl = s(self.w)

        self.s_mod *= self.spl
        self.serr_mod *= self.spl
        

    def objective(self, params):
        """
        Objective function evaluating goodness of fit given the passed parameters

        Args:
            params
        Returns:
            Reduced chi-squared value between the target spectra and the 
            model spectrum generated by the parameters
        """
        chi_square = super().objective(params)

        # Add a Gaussian prior
        sum_coeff = 0
        for i in range(self.num_refs):
            p = 'coeff_{0:d}'.format(i)
            sum_coeff += params[p].value

        WIDTH = 1e-3
        chi_square += (sum_coeff-1)**2/(2*WIDTH**2)

        return chi_square

    def best_fit(self):
        """
        Calculates the best fit model by minimizing over the parameters:
        - Coefficients of reference spectra
        - spline fitting to the continuum
        - rotational broadening
        """
        params = lmfit.Parameters()
        ### Linear combination parameters
        params = self.add_lincomb_params(params)

        # Minimize chi-squared
        out = lmfit.minimize(self.objective, params, method='nelder')

        # Save best fit parameters
        self.best_params = out.params
        self.best_chisq = self.objective(self.best_params)

        return self.best_chisq

    def add_lincomb_params(self, params):
        params.add('num_refs', value=self.num_refs, vary=False)

        for i in range(self.num_refs):
            p = 'coeff_{0:d}'.format(i)
            params.add(p, value=1/self.num_refs, min=0.0, max=1.0)

        return params
