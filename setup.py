from ez_setup import use_setuptools
use_setuptools()

from setuptools import setup, find_packages
setup(
        name = "labscript_devices",
        packages = find_packages(),
        install_requires = ['h5py', 'labscript_utils', 'zprocess',
                            'blacs', 'spinapi', 'PyDAQmx',
                            'numpy', 'labscript', 'PySide', 'pyzmq==13.1.0']

)

