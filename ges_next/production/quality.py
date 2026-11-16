"""Full-grid JPEG quality checking with bounded image strips."""

def measure(root,reference,support,night_path=None):
    from ges_next.performance.quality_strips import measure as bounded_measure
    return bounded_measure(root,reference,support,night_path=night_path,strip_rows=64)
