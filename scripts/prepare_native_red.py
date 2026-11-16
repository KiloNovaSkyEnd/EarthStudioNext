"""Budgeted single real 500m ABI red band matching the cached 2020 scene."""
from pathlib import Path
from ges.catalog import Scene,s3_client,list_objects,utc_time
from ges.storage import load_config
from ges.download import download_scene


def main():
    s3=s3_client();prefix='ABI-L1b-RadF/2020/303/16/'
    matches=[o for o in list_objects(s3,'noaa-goes16',prefix) if 'C02_' in o['Key'] and '_s20203031640189_' in o['Key']]
    if len(matches)!=1:raise ValueError('Exact historical red band ambiguous/missing')
    obj=matches[0];cfg=load_config()
    scene=Scene('goes16','noaa-goes16',prefix,utc_time('2020-10-29T16:40:18.9Z'),
        (obj['Key'],),obj['Size'],'ABI-L1b-RadF-C02',(obj['Size'],))
    print('ONE REAL C02 BAND',obj['Size'],'bytes; budget/reserve/atomic checks required',flush=True)
    print(download_scene(s3,scene,cfg.raw_dir/'native_red',cfg),flush=True)


if __name__=='__main__':main()
