"""Complete first native disk qualification, committing reusable production data."""
from ges.earth_validation import bootstrap  # noqa: F401
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
from ges.earth_validation.stock import configure,open_scene,export_scene
from ges.earth_validation.project import save
from ges.earth_validation.resources import monitor


def main(root):
    root=Path(root)
    plan=json.loads((root/'inventory.json').read_text(encoding='utf-8'))
    descriptor=next(s for s in plan['scenes'] if s['sensor']=='himawari8' and s['nominal_utc']==plan['frames'][0])
    def status(stage,**values):
        save(root/'reports/full_pipeline_status.json',{'stage':stage,'native_only':True,
            'updated_utc':datetime.now(timezone.utc).isoformat(),'node':1,'total':73,
            'sensor':'himawari8','full_global_delivery_complete':False,**values})
    import msvcrt
    with (root/'reports/full_pipeline.lock').open('a+b') as lock:
        lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        try:
            with monitor(root):
                status('qualifying_full_native_memory')
                configure(root); scene,records=open_scene(root,plan,descriptor)
                metadata=export_scene(root,plan,descriptor,scene.finest_area(),'full_native_disk_v4',
                    root/'raw/references/blackmarble_2016_500m/global_500m.vrt',native=True,opened=(scene,records))
                result=json.loads(metadata.read_text(encoding='utf-8'))
                if result['shape']!=[22000,22000]: raise ValueError('Full original AHI red grid not retained')
                save(root/'reports/full_native_memory_qualification.json',{'metadata':str(metadata),
                    'native_shape':result['shape'],'finite_alpha_pixels':result['finite_alpha_pixels'],
                    'rgba_bytes':result['bytes'],'observation_support_version':result['observation_support_version'],
                    'success':True,'global_delivery_complete':False})
                status('full_native_memory_qualified',metadata=str(metadata))
        except Exception as error:
            status('native_memory_qualification_failed',error=str(error)); raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--root',required=True)
    main(parser.parse_args().root)
