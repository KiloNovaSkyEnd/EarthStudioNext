"""Retain stock GeoColor's ground-background transmission, before JPEG encoding."""
from contextlib import contextmanager
import gc
from pathlib import Path
from unittest.mock import patch
import numpy as np


@contextmanager
def black_background(stock):
    original = stock.inject_background
    def inject(scene, *args, **kwargs):
        original(scene, *args, **kwargs)
        data = scene['_night_background_hires']
        scene['_night_background_hires'] = data.copy(data=data.data * 0)  # Preserve source NaNs.
    with patch.object(stock, 'inject_background', inject):
        yield


def store_layers(scene, area, night, reference, work, report, capture_night=False):
    import dask
    import dask.array as da
    from satpy.composites.core import enhance2dataset
    from satpy.composites.fill import DayNightCompositor
    from satpy.enhancements.enhancer import get_enhanced_image
    from ges.earth_validation import stock
    from ges.earth_validation.spill import bounded_compute
    from ges.earth_validation.compute_progress import ComputeProgress

    work = Path(work)
    retained = ['geo_color_high_clouds', 'geo_color_low_clouds', 'true_color_ndvi_green',
                'geo_color_night', '_night_background_hires']
    import json
    shared=work/'shared_cache.json'
    cache_root=Path(json.loads(shared.read_text())['path']) if shared.exists() else work
    kwargs = dict(native=True, native_tile=False, night_cache=cache_root/'night_cache', compute_chunk=1024)
    report('planning-stock')
    from ges_next.pipeline.locking import exclusive
    with exclusive(cache_root/'planning.lock',wait=True):
        full, actual = stock.compose(scene, area, night, reference, retain_datasets=retained, **kwargs)
        if actual.shape != (11000, 11000): raise ValueError('Expected original1kmH9 grid')
        report('planning-independent-ground')
        with black_background(stock):
            dark, dark_area = stock.compose(scene, area, night, reference, **kwargs)
    if dark_area != actual: raise ValueError('Layer grids differ')
    high = enhance2dataset(full['geo_color_high_clouds'], convert_p=True).sel(bands='A').fillna(0)
    low = enhance2dataset(full['geo_color_low_clouds'], convert_p=True).sel(bands='A').fillna(0)
    day = full['true_color_ndvi_green']
    compositor = DayNightCompositor('production-weight', lim_low=78, lim_high=88)
    solar = compositor._get_coszen_blending_weights([day, full['geo_color_night']])
    enhanced_day = enhance2dataset(day)
    day_data, night_data, _ = compositor._get_data_for_combined_product(enhanced_day, full['geo_color_night'])
    solar = compositor._mask_weights_with_data(solar, day_data, night_data)
    solar = compositor._fill_weights(solar)
    weight = ((1-high)*(1-low)*(1-solar)).fillna(0).clip(0, 1).data.astype(np.float32)
    def rgb(result):
        return get_enhanced_image(result['geo_color']).data.sel(bands=['R','G','B']).transpose('y','x','bands').data.astype(np.float32)
    normal, unlit = rgb(full), rgb(dark)
    static = full['_night_background_hires'].sel(bands=['R','G','B']).transpose('y','x','bands').data.astype(np.float32)
    valid = da.isfinite(normal).all(axis=2)
    normal, unlit = da.nan_to_num(normal), da.nan_to_num(unlit)
    static = da.nan_to_num(static)
    reconstructed = unlit + static/255 * weight[...,None]
    error = da.where(valid[...,None], da.abs(da.clip(reconstructed,0,1)-da.clip(normal,0,1)), 0).max()
    quantize = lambda value: da.rint(da.clip(value,0,1)*255).astype(np.uint8)
    arrays = dict(base=quantize(unlit), reference=quantize(normal), night=da.rint(da.clip(static,0,255)).astype(np.uint8),
                  transmission=da.rint(weight*65535).astype(np.uint16), support=(valid*255).astype(np.uint8))
    from .static_night import StaticNight
    if capture_night:
        arrays.update(day_branch=quantize(da.nan_to_num(get_enhanced_image(day).data.sel(bands=['R','G','B']).transpose('y','x','bands').data)),
            high_branch=quantize(high.data),low_branch=quantize(low.data),
            solar_branch=da.rint(da.clip(da.nan_to_num(solar.data),0,1)*65535).astype(np.uint16))
    cache_settings=json.loads(shared.read_text(encoding='utf-8')) if shared.exists() else {}
    if 'night_reference' in cache_settings:
        slot=StaticNight(cache_settings['night_reference'],dict(shape=list(actual.shape),
            extent=list(actual.area_extent),crs=actual.crs.to_wkt()),cache_settings['quality'])
        if slot.lookup() is not None:arrays.pop('night')
    maps = {}
    for name, value in arrays.items():
        path = work/(name+'.npy')
        maps[name] = np.lib.format.open_memmap(path, mode='w+', dtype=value.dtype, shape=value.shape)
    report('computing-stock-and-layers')
    from .store_target import StoreTarget
    stores = da.store(list(arrays.values()), [StoreTarget(v) for v in maps.values()], compute=False, lock=False)
    from ges_next.performance.policy import settings
    policy=settings()
    from ges.earth_validation.resources import monitor
    with monitor(work), bounded_compute(work, limit=policy['spill_bytes'], workers=policy['compute_workers']), ComputeProgress(work/'compute_progress.json','H9 JPEG independent ground layers'):
        _, maximum = dask.compute(stores, error)
    for value in maps.values(): value.flush()
    if not np.isfinite(maximum) or maximum > 2e-5:
        raise ValueError(f'Ground decomposition failed stock parity: {maximum}')
    metadata = dict(shape=list(actual.shape), extent=list(actual.area_extent), crs=actual.crs.to_wkt(),
                    maximum_float_recomposition_error=float(maximum), night_texture_metres=1000,
                    meaning='Static NASA night terrain/city-light background contribution, not individual physical lamps',
                    formula='displayRGB = stockWithoutNightBackground + stockTransmission * staticNightRGB; then sRGB transfer')
    del arrays, full, dark, normal, unlit, static, stores
    gc.collect()
    return maps, metadata
