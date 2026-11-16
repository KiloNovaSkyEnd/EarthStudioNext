"""Set library import-time chunk constants before any Satpy/pyresample import."""
import os

os.environ['PYTROLL_CHUNK_SIZE'] = '512'
os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('GDAL_CACHEMAX', '256')
