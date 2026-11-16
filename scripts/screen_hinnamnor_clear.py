"""Exact display-only clear screen of the observed candidate; retain all old variants."""
import json
import numpy as np
from PIL import Image
from ges.storage import load_config
from ges.goni_lowcloud import screen_confident_clear


def main():
    root=load_config().processed_dir/'hinnamnor_targeted_v1'
    for stamp in ['1000','1130']:
        source=root/stamp/'candidate';dest=root/stamp/'screened_candidate';dest.mkdir(exist_ok=False)
        with np.load(root/stamp/'l2_observed_roi.npz') as f:mask=f['CloudMask'];q=f['CloudMaskQualFlag']
        clear=screen_confident_clear(np.ones(mask.shape),mask,q)==0
        selection=np.repeat(np.repeat(clear,2,0),2,1);valid_cloud=np.repeat(np.repeat(np.isin(mask,[2,3])&(q==0),2,0),2,1)
        records={}
        for name in ['B_current_material_rgba.png','B_current_upload_rgba.png','uniform_legacy_colour_rgba.png']:
            old=np.asarray(Image.open(source/name).convert('RGBA'));new=old.copy();new[selection]=0
            assert np.array_equal(new[valid_cloud],old[valid_cloud]),'A valid L2 cloud was altered'
            Image.fromarray(new).save(dest/name)
            records[name]={'clear_positive_alpha_removed':int(((old[...,3]>0)&selection).sum()),
                           'clear_max_old_alpha_dn':int(old[...,3][selection].max()),'valid_cloud_pixels_unchanged':int(valid_cloud.sum())}
        with np.load(source/'material_layers.npz') as f:layers={k:f[k] for k in f.files}
        for key in ['alpha','uploaded_alpha']:layers[key][selection]=0
        layers['probability']=screen_confident_clear(layers['probability'],mask,q)
        np.savez_compressed(dest/'material_layers.npz',**layers)
        meta=json.loads((source/'material_metadata.json').read_text());meta['region_policy']='observed_screened'
        meta['clear_screen_checks']=records
        (dest/'material_metadata.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
        print('CLEAR SCREEN READY',stamp,records,flush=True)


if __name__=='__main__':main()
