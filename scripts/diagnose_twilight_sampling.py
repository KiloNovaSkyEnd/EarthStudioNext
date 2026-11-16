"""Isolate measured noise, nearest decimation and 2x2 ratio sharpening offline."""
import json
import os
from pathlib import Path

import dask
import numpy as np
import satpy
from PIL import Image
from satpy import Scene
from satpy.enhancements.enhancer import get_enhanced_image

from ges.observed_rgb import _sha
from ges.storage import load_config


def main():
    cfg = load_config()
    out = cfg.processed_dir/'twilight_sampling_audit_v2'
    out.mkdir(exist_ok=False)
    source = cfg.processed_dir/'observed_twilight_v1/sources/1000'
    before = _sha(source/'rgb.npy')
    metadata = json.loads((source/'metadata.json').read_text())['observation_metadata']
    files = [p for p in metadata['input_file_sha256'] if any(f'_B{b:02}_' in p for b in [1, 2, 3, 4])]
    config = out/'config'
    (config/'composites').mkdir(parents=True)
    recipe = (source/'satpy_config/composites/ahi.yaml').read_text()+'''  observed_unsharpened_rgb:
    compositor: !!python/name:satpy.composites.core.GenericCompositor
    prerequisites:
    - name: B03
      modifiers: [sunz_corrected, observed_rayleigh]
    - name: observed_ndvi_green
    - name: B01
      modifiers: [sunz_corrected, observed_rayleigh]
    standard_name: true_color
'''
    (config/'composites/ahi.yaml').write_text(recipe)
    os.environ['PSP_CONFIG_FILE'] = str((cfg.raw_dir/'reference/pyspectral/pyspectral.yaml').resolve())
    with satpy.config.set(config_path=list(satpy.config.get('config_path'))+[str(config.resolve())],
                          data_dir=str((cfg.raw_dir/'reference/satpy_geocolor_v060').resolve()), download_aux=False), dask.config.set(num_workers=2):
        scene = Scene(reader='ahi_hsd', filenames=files)
        scene.load(['B01', 'B02', 'B03', 'B04'])
        # Declared diagnostic subarea covering both user-marked crops, not a correction ROI.
        xmin, ymin, xmax, ymax = metadata['area_extent_m']
        dx = (xmax-xmin)/metadata['output_shape_yx'][1]
        dy = (ymax-ymin)/metadata['output_shape_yx'][0]
        extent = [xmin+200*dx, ymax-1500*dy, xmin+1600*dx, ymax-300*dy]
        crop = scene.copy()
        for name in ['B01', 'B02', 'B03', 'B04']:
            dataset = scene[name]
            area = dataset.attrs['area']
            x0 = round((extent[0]-area.area_extent[0])/area.pixel_size_x)
            y0 = round((area.area_extent[3]-extent[3])/area.pixel_size_y)
            nx = round((extent[2]-extent[0])/area.pixel_size_x)
            ny = round((extent[3]-extent[1])/area.pixel_size_y)
            subarea = area[y0:y0+ny, x0:x0+nx]
            assert np.allclose(subarea.area_extent, extent, rtol=0, atol=.1)
            part = dataset.isel(y=slice(y0,y0+ny), x=slice(x0,x0+nx))
            part.attrs = {**dataset.attrs, 'area': subarea}
            crop[name] = part
            print('RAW_GRID', name, part.shape, flush=True)
        target = crop['B01'].attrs['area']
        assert crop['B01'].shape == (1200, 1400) and crop['B03'].shape == (2400, 2800)
        raw = {}
        for name in ['B01', 'B02', 'B03', 'B04']:
            values = crop[name].data.compute(scheduler='threads', num_workers=2)
            raw[name] = np.asarray(values, np.float32)
            np.save(out/(name+'_native_percent.npy'), raw[name], allow_pickle=False)
        print('RAW_EXPORTED', flush=True)
        crop.load(['observed_twilight_rgb', 'observed_unsharpened_rgb'], generate=True, unload=False)
        images = {}
        for resampler in ['nearest', 'native']:
            result = crop.resample(target, resampler=resampler, unload=False)
            fields = []
            names = []
            for product in ['observed_twilight_rgb', 'observed_unsharpened_rgb']:
                dataset = result[product]
                fields.append(dataset.data)
                names.append(resampler+'_'+('sharp' if product == 'observed_twilight_rgb' else 'plain'))
            calculated = dask.compute(*fields, scheduler='threads', num_workers=2)
            for name, unenhanced in zip(names, calculated):
                # CIRA as installed: retain scientific-scale intermediate separately.
                data = np.moveaxis(np.asarray(unenhanced, np.float32), 0, -1)
                np.save(out/(name+'_percent.npy'), data, allow_pickle=False)
                log_root = np.log10(np.float32(.0223))
                display = (np.log10(np.maximum(data*.01, np.finfo(float).eps))-log_root)/((1-log_root)*.75)
                np.save(out/(name+'_display.npy'), display, allow_pickle=False)
                rgb = np.rint(np.clip(np.nan_to_num(display), 0, 1)*255).astype(np.uint8)
                Image.fromarray(rgb).save(out/(name+'.png'))
                images[name] = rgb
            print('VARIANTS_EXPORTED', resampler, flush=True)
        m = dict(nominal_utc=metadata['nominal_utc'], source_subarea_in_previous_rgb_yxyx=[300, 1500, 200, 1600],
                 area_extent_m=list(target.area_extent), source_shape_yx=list(target.shape), projection=metadata['projection'],
                 raw_input_sha256={p: metadata['input_file_sha256'][p] for p in files},
                 existing_source_sha256=before, limits='Ablations, no denoising/painted data. Raw bands exported at true resolutions.')
        assert _sha(source/'rgb.npy') == before
        (out/'metadata.json').write_text(json.dumps(m, indent=2))


if __name__ == '__main__':
    main()
