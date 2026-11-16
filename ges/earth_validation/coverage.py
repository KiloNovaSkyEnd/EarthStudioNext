"""Observation footprint guard without treating cold 3.9um noise as no scan.

Stock LowCloudCompositor suppresses the 3.9um contribution below230K; the
valid thermal-window high cloud must remain available there. The auxiliary
shortwave IR band therefore cannot veto the whole final stock composite.
"""
import numpy as np

SUPPORT_VERSION = 2
LOW_CLOUD_AUXILIARY = frozenset(('B07', 'C07', 'IR_039'))


def observed_support(scene, names):
    support = None
    for name in names:
        if name in LOW_CLOUD_AUXILIARY:
            continue
        valid = np.isfinite(scene[name])
        support = valid if support is None else support & valid
    if support is None:
        raise ValueError('No primary observation bands available for footprint guard')
    return support
