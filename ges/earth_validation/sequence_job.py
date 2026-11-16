"""All requested observation nodes; each committed sensor image is resumable."""
import gc
import json
from datetime import datetime,timezone
from pathlib import Path
import msvcrt
import traceback
from .stock import configure,open_scene,export_scene,SUPPORTED
from .stock_job import combine_proxy
from .project import save
from .capabilities import inspect


def run(root):
    root=Path(root)
    status=root/'reports/sequence_status.json'
    def update(stage,**values):
        record={'stage':stage,'updated_utc':datetime.now(timezone.utc).isoformat(),**values}
        save(status,record); print(json.dumps(record,ensure_ascii=False),flush=True)
    with (root/'reports/stock_job.lock').open('a+b') as lock:
        if lock.tell()==0: lock.write(b'0'); lock.flush()
        lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        try:
            audit=inspect(root)
            if audit['archive_receipt_problems']: raise ValueError('Archive receipt audit failed')
            plan=json.loads((root/'inventory.json').read_text(encoding='utf-8'))
            night=root/'raw/references/blackmarble_2016_500m/global_500m.vrt'
            frames=[]
            for index,utc in enumerate(plan['frames'],1):
                paths=[]
                descriptors=[s for s in plan['scenes'] if s['nominal_utc']==utc and s['sensor'] in SUPPORTED]
                for descriptor in descriptors:
                    update('sensor_proxy',node=index,total=len(plan['frames']),nominal_utc=utc,
                           sensor=descriptor['sensor'],scene_id=descriptor['scene_id'])
                    kind='disk_proxy_12km' if descriptor['sensor'].startswith('meteosat') else 'disk_proxy_8km'
                    existing=root/'processed/stock_geocolor'/descriptor['scene_id']/kind/'metadata.json'
                    if existing.is_file():
                        paths.append(export_scene(root,plan,descriptor,None,kind,night,sensor_native=True))
                    else:
                        configure(root); scene,records=open_scene(root,plan,descriptor)
                        infrared=('B13' if descriptor['sensor']=='himawari8' else
                                  'IR_108' if descriptor['sensor'].startswith('meteosat') else 'C13')
                        area=scene[infrared].attrs['area']
                        grid=area.copy(width=area.width//4,height=area.height//4)
                        paths.append(export_scene(root,plan,descriptor,grid,kind,night,sensor_native=True,opened=(scene,records)))
                        del scene; gc.collect()
                frame=combine_proxy(root,paths,index,utc,'global_sequence_4k',width=4096)
                frame['missing_sensors']=sorted(SUPPORTED-{s['sensor'] for s in descriptors})
                # SEVIRI repeated scans remain explicit; the source metadata
                # records actual start/end, separate from this nominal node.
                frames.append(frame)
                save(root/'reports/stock_sequence_partial.json',{'frames':frames,'complete_sequence':False})
                update('node_committed',node=index,total=len(plan['frames']),nominal_utc=utc)
            result={'frames':frames,'complete_sequence':len(frames)==73,'global_native_detail':False,
                    'visual_acceptance_passed':False,'global_acceptance_passed':False,
                    'limits':'Complete requested time axis; proxy images do not provide native close-up detail.'}
            save(root/'reports/stock_sequence.json',result)
            update('sequence_ready',nodes=len(frames),global_native_detail=False)
            return result
        except Exception as error:
            update('failed',error_type=type(error).__name__,error=str(error))
            traceback.print_exc(); raise
