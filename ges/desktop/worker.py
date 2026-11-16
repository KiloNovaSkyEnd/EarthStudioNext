"""One task per subprocess. Heavy scientific imports never run on the UI thread."""
from pathlib import Path
import json
import subprocess
import sys
from .jobs import ROOT


def execute(action, opts, directory):
    from ges.storage import load_config
    cfg = load_config()
    if action in ('search', 'download'):
        from ges.catalog import utc_time, s3_client, selected_himawari, himawari_scene, goes_scene, scene_as_json
        from ges.download import download_scene, cached_bytes
        from ges.storage import preflight
        utc = utc_time(opts['utc'])
        satellite = opts['satellite']
        if satellite == 'auto':
            satellite = selected_himawari(utc)
        if satellite.startswith('himawari') and satellite != selected_himawari(utc):
            raise ValueError('所选日葵卫星与历史日期不匹配，请选择 auto。')
        client = s3_client()
        bands = ('B01', 'B02', 'B03') if opts['product'] == 'rgb' else ('B13',)
        scene = (himawari_scene(client, utc, bands, 20) if satellite.startswith('himawari')
                 else goes_scene(client, utc, satellite, 20))
        inventory = directory / 'inventory.json'
        inventory.write_text(json.dumps(scene_as_json(scene), ensure_ascii=False, indent=2), encoding='utf-8')
        print(inventory.read_text(encoding='utf-8'), flush=True)
        if action == 'search':
            return inventory
        print('磁盘预算检查:', preflight(scene.total_bytes, cfg.raw_dir / scene.scene_id, cfg,
              existing_bytes=cached_bytes(scene, cfg.raw_dir / scene.scene_id)), flush=True)
        return download_scene(client, scene, cfg.raw_dir, cfg)
    if action == 'render':
        from ges.render import render
        return render(Path(opts['manifest']), directory / 'products', opts['product'], int(opts['width']))
    if action == 'render-batch':
        from ges.render import render
        import gc
        manifests = opts['manifests']
        if not manifests:
            raise ValueError('请先添加原始场景清单。')
        summary = directory / 'batch_results.json'
        results = []
        for index, manifest in enumerate(manifests, 1):
            print(f'批量处理 {index}/{len(manifests)}: {manifest}', flush=True)
            product = render(Path(manifest), directory / f'scene_{index:04d}', opts['product'], int(opts['width']))
            results.append({'manifest': manifest, 'path': str(product)})
            temp = summary.with_suffix('.tmp')
            temp.write_text(json.dumps({'completed': results, 'total': len(manifests)}, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(summary)
            gc.collect()
        return summary
    if action == 'mosaic':
        from ges.render import combine_images
        from ges.catalog import utc_time
        return combine_images([Path(p) for p in opts['images']], directory / 'mosaic.png', utc_time(opts['utc']))
    if action == 'meteosat-search':
        from ges.meteosat import search_observation
        from ges.catalog import utc_time
        data = {'candidates': [search_observation(utc_time(opts['utc']), service, 20)
                               for service in ('zero', 'iodc')]}
        target = directory / 'meteosat_inventory.json'
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(target.read_text(encoding='utf-8'), flush=True)
        return target
    if action == 'meteosat-download':
        from ges.meteosat_download import download_candidates
        inventory = json.loads(Path(opts['inventory']).read_text(encoding='utf-8'))
        download_candidates(inventory['candidates'])
        return cfg.raw_dir
    if action == 'export':
        from ges.export import export_product
        return export_product(Path(opts['image']), cfg.export_dir)
    if action == 'daylight':
        from ges.daylight import render_daylight
        return render_daylight(opts['manifest'], directory / 'daylight', int(opts['width']))
    if action == 'day-night':
        from ges.day_night import compose_day_night
        return compose_day_night(opts['day'], opts['night'], directory / 'day_night.png', opts['utc'])
    if action == 'blend-ir':
        from ges.blend import blend_ir
        records = json.loads(Path(opts['sources']).read_text(encoding='utf-8'))
        return blend_ir(records, directory / 'blended_ir.png', opts['utc'], 64)
    if action == 'blender':
        executable = Path(opts['blender'])
        if not executable.is_file():
            raise ValueError('请选择 Blender 可执行文件。')
        target = directory / 'earth.blend'
        command = [str(executable), '--background', '--factory-startup', '--python-exit-code', '1',
                   '--python', str(ROOT / 'blender_make_earth.py'), '--', '--cloud', opts['image'],
                   '--out', str(target), '--preview', str(directory / 'earth.png')]
        if opts.get('earth'):
            command.extend(['--earth', opts['earth']])
        # Keep Blender in this worker's process tree so cancellation can stop both.
        subprocess.run(command, check=True)
        if not target.is_file():
            raise RuntimeError('Blender 未生成场景文件，请查看日志。')
        return target
    raise ValueError('Unknown action')


def main():
    path = Path(sys.argv[1]).resolve()
    job = json.loads(path.read_text(encoding='utf-8'))
    result = execute(job['action'], job['options'], path.parent)
    target = path.parent / 'result.json'
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps({'path': str(result)}, ensure_ascii=False), encoding='utf-8')
    temp.replace(target)
    print('完成:', result, flush=True)


if __name__ == '__main__':
    main()
