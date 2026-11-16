"""Current preparation entry; the static-daytime legacy recipe stays frozen."""
from .stock_job import run


def prepare(root,pilot=False,detail=True):
    if not pilot:
        raise RuntimeError('Full sequence requires validated stock pilot and native-tile coverage first; use stock-pilot. Legacy static-daytime processing is disabled.')
    return run(root)
