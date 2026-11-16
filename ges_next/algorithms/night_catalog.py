"""Same NOAA catalog adapter with an isolated, explicit optional-band contract."""
from types import FunctionType
from .night_modes import recipe
from ges_next import noaa

def probe_for(profile):
    selected=recipe(profile)
    if selected.mode=='geocolor':return noaa.probe
    # Fresh function globals avoid mutating NOAA's default six-band contract.
    adapted=FunctionType(noaa.probe.__code__,dict(noaa.probe.__globals__,AHI_BANDS=selected.bands),noaa.probe.__name__,noaa.probe.__defaults__)
    def probe(client,candidate,when):
        if candidate.satellite!='himawari9':raise ValueError('Optional AI night modes currently require Himawari-9')
        return adapted(client,candidate,when)
    return probe
