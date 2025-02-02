#!/usr/bin/env python
# -*- coding: utf-8 -*-

# *************************************************************************** #
#                  Copyright © 2022, UChicago Argonne, LLC                    #
#                           All Rights Reserved                               #
#                         Software Name: Tomocupy                             #
#                     By: Argonne National Laboratory                         #
#                                                                             #
#                           OPEN SOURCE LICENSE                               #
#                                                                             #
# Redistribution and use in source and binary forms, with or without          #
# modification, are permitted provided that the following conditions are met: #
#                                                                             #
# 1. Redistributions of source code must retain the above copyright notice,   #
#    this list of conditions and the following disclaimer.                    #
# 2. Redistributions in binary form must reproduce the above copyright        #
#    notice, this list of conditions and the following disclaimer in the      #
#    documentation and/or other materials provided with the distribution.     #
# 3. Neither the name of the copyright holder nor the names of its            #
#    contributors may be used to endorse or promote products derived          #
#    from this software without specific prior written permission.            #
#                                                                             #
#                                                                             #
# *************************************************************************** #
#                               DISCLAIMER                                    #
#                                                                             #
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS         #
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT           #
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS           #
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT    #
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,      #
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED    #
# TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR      #
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF      #
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING        #
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS          #
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.                #
# *************************************************************************** #

import os
import time
from pathlib import Path
from threading import Thread
import argparse
import h5py
import numpy as np
import cupy as cp
import numexpr as ne
import sys
from tomocupy import log_local as logging

log = logging.getLogger(__name__)
# Print iterations progress


def printProgressBar(iteration, total, qsize, prefix='', suffix='', decimals=1, length=100, fill='█', printEnd="\r"):
    """
    Call in a loop to create terminal progress bar
    @params:
        iteration   - Required  : current iteration (Int)
        total       - Required  : total iterations (Int)
        prefix      - Optional  : prefix string (Str)
        suffix      - Optional  : suffix string (Str)
        decimals    - Optional  : positive number of decimals in percent complete (Int)
        length      - Optional  : character length of bar (Int)
        fill        - Optional  : bar fill character (Str)
        printEnd    - Optional  : end character (e.g. "\r", "\r\n") (Str)
    """
    percent = ("{0:." + str(decimals) + "f}").format(100 *
                                                     (iteration / float(total)))
    filledLength = int(length * iteration // total)
    bar = fill * filledLength + '-' * (length - filledLength)
    print(
        f'\rqueue size {qsize:03d} | {prefix} |{bar}| {percent}% {suffix}', end=printEnd)
    # Print New Line on Complete
    if iteration == total:
        print()


def positive_int(value):
    """Convert *value* to an integer and make sure it is positive."""
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError('Only positive integers are allowed')
    return result


def restricted_float(x):

    x = float(x)
    if x < 0.0 or x > 1.0:
        raise argparse.ArgumentTypeError("%r not in range [0.0, 1.0]" % (x,))
    return x


def pinned_array(array):
    """Allocate pinned memory and associate it with numpy array"""

    mem = cp.cuda.alloc_pinned_memory(array.nbytes)
    src = np.frombuffer(
        mem, array.dtype, array.size).reshape(array.shape)
    src[...] = array
    return src


def signal_handler(sig, frame):
    """Calls abort_scan when ^C or ^Z is typed"""

    print('Abort')
    sys.exit(1)


class WRThread():
    def __init__(self):
        self.thread = None

    def run(self, fun, args):
        self.thread = Thread(target=fun, args=args)
        self.thread.start()

    def is_alive(self):
        if self.thread == None:
            return False
        return self.thread.is_alive()

    def join(self):
        if self.thread == None:
            return
        self.thread.join()


def find_free_thread(threads):
    ithread = 0
    while True:
        if not threads[ithread].is_alive():
            break
        ithread = ithread+1
        # ithread=(ithread+1)%len(threads)
        if ithread == len(threads):
            ithread = 0
            time.sleep(0.01)
    return ithread


def downsample(data, binning):
    """Downsample data"""
    for j in range(binning):
        x = data[:, :, ::2]
        y = data[:, :, 1::2]
        data = ne.evaluate('x + y')  # should use multithreading
    for k in range(binning):
        x = data[:, ::2]
        y = data[:, 1::2]
        data = ne.evaluate('x + y')
    return data


def take_filter(Ne, filter):
    d = 0.5
    t = cp.arange(0, Ne/2+1)/Ne

    if (filter == 'ramp'):
        wfa = Ne*0.5*wint(12, t)  # .*(t/(2*d)<=1)%compute the weigths
    elif (filter == 'shepp'):
        wfa = Ne*0.5*wint(12, t)*cp.sinc(t/(2*d))*(t/d <= 2)
    elif (filter == 'cosine'):
        wfa = Ne*0.5*wint(12, t)*cp.cos(cp.pi*t/(2*d))*(t/d <= 1)
    elif (filter == 'cosine2'):
        wfa = Ne*0.5*wint(12, t)*(cp.cos(cp.pi*t/(2*d)))**2*(t/d <= 1)
    elif (filter == 'hamming'):
        wfa = Ne*0.5*wint(12, t)*(.54 + .46 * cp.cos(cp.pi*t/d))*(t/d <= 1)
    elif (filter == 'hann'):
        wfa = Ne*0.5*wint(12, t)*(1+cp.cos(cp.pi*t/d)) / 2.0*(t/d <= 1)
    elif (filter == 'parzen'):
        wfa = Ne*0.5*wint(12, t)*pow(1-t/d, 3)*(t/d <= 1)

    wfa = 2*wfa*(wfa >= 0)
    wfa[0] *= 2
    wfa = wfa.astype('float32')
    return wfa

def wint(n, t):

    N = len(t)
    s = cp.linspace(1e-40, 1, n)
    # Inverse vandermonde matrix
    tmp1 = cp.arange(n)
    tmp2 = cp.arange(1, n+2)
    iv = cp.linalg.inv(cp.exp(cp.outer(tmp1, cp.log(s))))    
    u = cp.diff(cp.exp(cp.outer(tmp2,cp.log(s)))*cp.tile(1.0/tmp2[...,cp.newaxis], [1, n]))  # integration over short intervals                                                                
    W1 = cp.matmul(iv,u[1:n+1, :])# x*pn(x) term
    W2 = cp.matmul(iv,u[0:n, :])# const*pn(x) term

    # Compensate for overlapping short intervals
    tmp1 = cp.arange(1,n)
    tmp2 = (n-1)*cp.ones((N-2*(n-1)-1))
    tmp3 = cp.arange(n-1, 0, -1)
    p = 1/cp.concatenate((tmp1,tmp2,tmp3))
    w = cp.zeros(N)
    for j in range(N-n+1):
        # Change coordinates, and constant and linear parts
        W = ((t[j+n-1]-t[j])**2)*W1+(t[j+n-1]-t[j])*t[j]*W2

        for k in range(n-1):
            w[j:j+n] = w[j:j+n] + p[j+k]*W[:, k]

    wn = w
    wn[-40:] = (w[-40])/(N-40)*cp.arange(N-40, N)
    return wn


def read_bright_ratio(params):
    '''Read the ratio between the bright exposure and other exposures.
    '''
    log.info('  *** *** Find bright exposure ratio params from the HDF file')
    try:
        possible_names = ['/measurement/instrument/detector/different_flat_exposure',
                        '/process/acquisition/flat_fields/different_flat_exposure']
        for pn in possible_names:
            if check_item_exists_hdf(params.file_name, pn):
                diff_bright_exp = param_from_dxchange(params.file_name, pn,
                                    attr = None, scalar = False, char_array = True)
                break
        if diff_bright_exp.lower() == 'same':
            log.error('  *** *** used same flat and data exposures')
            params.bright_exp_ratio = 1
            return params
        possible_names = ['/measurement/instrument/detector/exposure_time_flat',
                        '/process/acquisition/flat_fields/flat_exposure_time',
                        '/measurement/instrument/detector/brightfield_exposure_time']
        for pn in possible_names:
            if check_item_exists_hdf(params.file_name, pn):
                bright_exp = param_from_dxchange(params.file_name, pn,
                                    attr = None, scalar = True, char_array = False)
                break    
        log.info('  *** *** %f' % bright_exp)
        norm_exp = param_from_dxchange(params.file_name,
                                    '/measurement/instrument/detector/exposure_time',
                                    attr = None, scalar = True, char_array = False)
        log.info('  *** *** %f' % norm_exp)
        params.bright_exp_ratio = bright_exp / norm_exp
        log.info('  *** *** found bright exposure ratio of {0:6.4f}'.format(params.bright_exp_ratio))
    except:
        log.warning('  *** *** problem getting bright exposure ratio.  Use 1.')
        params.bright_exp_ratio = 1
    return params


def check_item_exists_hdf(hdf_filename, item_name):
    '''Checks if an item exists in an HDF file.
    Inputs
    hdf_filename: str filename or pathlib.Path object for HDF file to check
    item_name: name of item whose existence needs to be checked
    '''
    with h5py.File(hdf_filename, 'r') as hdf_file:
        return item_name in hdf_file


def param_from_dxchange(hdf_file, data_path, attr=None, scalar=True, char_array=False):
    """
    Reads a parameter from the HDF file.
    Inputs
    hdf_file: string path or pathlib.Path object for the HDF file.
    data_path: path to the requested data in the HDF file.
    attr: name of the attribute if this is stored as an attribute (default: None)
    scalar: True if the value is a single valued dataset (dafault: True)
    char_array: if True, interpret as a character array.  Useful for EPICS strings (default: False)
    """
    if not Path(hdf_file).is_file():
        return None
    with h5py.File(hdf_file,'r') as f:
        try:
            if attr:
                return f[data_path].attrs[attr].decode('ASCII')
            elif char_array:
                return ''.join([chr(i) for i in f[data_path][0]]).strip(chr(0))
            elif scalar:
                return f[data_path][0]
            else:
                return None
        except KeyError:
            return None
