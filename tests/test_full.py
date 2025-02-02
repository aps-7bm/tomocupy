import unittest
import os
import numpy as np
import tifffile
import inspect
import h5py
import shutil
from pathlib import Path

prefix = 'tomocupy recon --file-name data/test_data.h5 --reconstruction-type full --rotation-axis 782.5 --nsino-per-chunk 4'
prefix2 = 'tomocupy recon --file-name data/Downsampled_WB.h5 --reconstruction-type full --nsino-per-chunk 4 --rotation-axis 808 --sample-material Pb '
prefix3 = '--read-pixel-size --read-scintillator --filter-1-auto True --filter-2-auto True --filter-3-auto True --sample-density 11.34 --dezinger 3 '
prefix4 = '--filter-1-density 1.85 --filter-2-density 8.9 --filter-3-density 8.9' 
prefix5 = '--filter-1-density 0.0 --filter-2-density 0.0 --filter-3-density 0.0' 
cmd_dict = {
    f'{prefix} ': 28.307,
    f'{prefix2} {prefix3} {prefix5} --beam-hardening-method standard --calculate-source standard': 3251.278,
    f'{prefix2} {prefix3} {prefix4} --beam-hardening-method standard': 3250.038,
    f'{prefix2} {prefix3} {prefix4} --beam-hardening-method standard --calculate-source standard': 3250.038,
    f'{prefix2} {prefix3} {prefix4} --beam-hardening-method standard --calculate-source standard --e-storage-ring 3.0': 1588.259,
    f'{prefix} --reconstruction-algorithm lprec ': 27.992,
    f'{prefix} --reconstruction-algorithm linerec ': 28.341,
    f'{prefix} --dtype float16': 24.186,
    f'{prefix} --reconstruction-algorithm lprec --dtype float16': 24.050,
    f'{prefix} --reconstruction-algorithm linerec --dtype float16': 25.543,
    f'{prefix} --binning 1': 12.286,
    f'{prefix} --reconstruction-algorithm lprec --binning 1': 12.252,
    f'{prefix} --reconstruction-algorithm linerec --binning 1': 12.259,
    f'{prefix} --start-row 3 --end-row 15 --start-proj 200 --end-proj 700': 17.589,
    f'{prefix} --save-format h5': 28.307,
    f'{prefix} --nsino-per-chunk 2 --file-type double_fov': 15.552,
    f'{prefix} --nsino-per-chunk 2 --blocked-views [0.2,1]': 30.790,
    f'{prefix} --nsino-per-chunk 2 --blocked-views [[0.2,1],[2,3]]': 40.849,
    f'{prefix} --remove-stripe-method fw': 28.167,
    f'{prefix} --remove-stripe-method fw --dtype float16': 23.945,
    f'{prefix} --start-column 200 --end-column 1000': 18.248,
    f'{prefix} --start-column 200 --end-column 1000 --binning 1': 7.945,
    f'{prefix} --flat-linear True': 28.308,
    f'{prefix} --rotation-axis-auto auto --rotation-axis-method sift  --reconstruction-type full' : 28.305,
    f'{prefix} --rotation-axis-auto auto --rotation-axis-method vo --center-search-step 0.1 --nsino 0.5 --center-search-width 100 --reconstruction-type full' : 28.303,
    f'{prefix} --remove-stripe-method vo-all ': 27.993,
}


class SequentialTestLoader(unittest.TestLoader):
    def getTestCaseNames(self, testCaseClass):
        test_names = super().getTestCaseNames(testCaseClass)
        testcase_methods = list(testCaseClass.__dict__.keys())
        test_names.sort(key=testcase_methods.index)
        return test_names


class Tests(unittest.TestCase):

    def test_full_recon(self):
        for cmd in cmd_dict.items():
            shutil.rmtree('data_rec',ignore_errors=True)      
            print(f'TEST {inspect.stack()[0][3]}: {cmd[0]}')
            st = os.system(cmd[0])
            self.assertEqual(st, 0)
            ssum = 0
            root_name = self.find_data_file_name(cmd[0])
            hdf_recon_path = Path.cwd().joinpath('data_rec', f'{root_name}_rec.h5')
            if hdf_recon_path.is_file():
                with h5py.File(hdf_recon_path, 'r') as fid:
                    data = fid['exchange/data']
                    ssum = np.sum(np.linalg.norm(data[:], axis=(1, 2)))
            else:
                rec_folder = Path.cwd().joinpath('data_rec', f'{root_name}_rec')
                good_recons = [i for i in rec_folder.iterdir() if i.name.startswith('recon_')]
                for i in good_recons:
                    ssum += np.linalg.norm(tifffile.imread(i))
            print(f'Summed norm = {ssum:8.3f}')
            self.assertAlmostEqual(ssum, cmd[1], places=0)

    def find_data_file_name(self, cmd):
        '''Returns the name (no extension) of the data file being reconstructed.
        '''
        split_1 = cmd.split('--file-name ')[1]
        split_2 = split_1.split(' ')[0]
        split_3 = split_2.split('/')[1]
        return split_3.split('.')[0]

if __name__ == '__main__':
    unittest.main(testLoader=SequentialTestLoader(), failfast=True)
