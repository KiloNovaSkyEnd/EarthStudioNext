"""Real on/off renders: effects are independent, reversible and not baked data."""
import hashlib,json,sys,math
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector,Quaternion

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from blender_make_earth import position_preview_camera,geographic_position


def main():
    scene=bpy.context.scene;folder=Path(bpy.data.filepath).parent
    source=Path(scene['GES_source_texture']);before=hashlib.sha256(source.read_bytes()).hexdigest()
    assert scene['GES_atmosphere_is_observation']==False
    earth=bpy.data.objects['Earth_Surface'];texture=next(n.image for n in earth.data.materials[0].node_tree.nodes if n.type=='TEX_IMAGE')
    assert texture.packed_file is not None
    shells=[o for o in scene.objects if o.name.startswith('Synthetic_Atmosphere_')]
    assert len(shells)==2 and all(o['GES_is_measured']==False for o in shells)
    scene.render.resolution_x=1920;scene.render.resolution_y=1080;scene.render.resolution_percentage=100
    scene.render.film_transparent=False;renders=[]
    def render(name,day,night):
        scene['GES_day_atmosphere']=day;scene['GES_night_airglow']=night
        scene.frame_set(scene.frame_current);bpy.context.view_layer.update()
        path=folder/(name+'.png');scene.render.filepath=str(path);bpy.ops.render.render(write_still=True)
        im=bpy.data.images.load(str(path),check_existing=False);a=np.empty(im.size[0]*im.size[1]*4,np.float32);im.pixels.foreach_get(a)
        result=a.reshape(im.size[1],im.size[0],4).copy();bpy.data.images.remove(im);return result
    # Both toggles off must match hiding the shells entirely, not just look close.
    position_preview_camera(scene.camera,5,10);scene.camera.data.lens=52
    off=render('toggle_off',False,False)
    for shell in shells:shell.hide_render=True
    hidden=render('shells_hidden_reference',False,False)
    error=float(abs(off-hidden).max());assert error<=1/255+.00001,error
    for shell in shells:shell.hide_render=False
    day=render('day_only',True,False);night=render('airglow_only',False,True)
    both=render('both_on',True,True)
    assert float(abs(day-off).max())>.01,'Day toggle has no visible effect'
    assert float(abs(night-off).max())>.005,'Airglow toggle has no visible effect'
    # No full-disk tint/fog: compare a central patch well away from the limb.
    center=np.s_[490:590,910:1010,:3]
    assert float(abs(both[center]-off[center]).max())<=1/255+.00001
    # Full globe + low fixed inspection angle; no animated camera path.
    for name,lon,lat,oblique in [('day_globe',-75,15,False),('night_globe',135,15,False),
        ('pacific_globe',-155,0,False),('day_horizon',-75,15,True),('night_horizon',135,15,True)]:
        if oblique:
            scene.camera.location=Vector(geographic_position(lon,lat,10000))
            target=Vector(geographic_position(lon+20,lat,6371))
            aim=(target-scene.camera.location).to_track_quat('-Z','Y')
            scene.camera.rotation_euler=(aim @ Quaternion((0,0,1),math.radians(-90))).to_euler();scene.camera.data.lens=35
        else:position_preview_camera(scene.camera,lon,lat);scene.camera.data.lens=52
        render(name+'_off',False,False);render(name+'_on',True,True)
        renders.append(name)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before,'Measurement texture changed'
    # Save a useful default with day blue on and synthetic airglow off. User
    # can independently toggle both in Scene > Custom Properties, no script.
    scene['GES_day_atmosphere']=True;scene['GES_night_airglow']=False
    position_preview_camera(scene.camera,5,10);scene.camera.data.lens=52
    scene.frame_set(scene.frame_current);bpy.context.view_layer.update()
    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    report={'passed':True,'render_width':1920,'off_vs_shells_hidden_max_error':error,
        'central_surface_max_error':float(abs(both[center]-off[center]).max()),
        'independent_day_and_airglow_controls':True,'satellite_png_sha256_unchanged':before,
        'source_coverage_unchanged':True,'comparisons':renders,'is_measured_atmosphere':False,
        'ocean_recolored':False,'limits':'Analytic limb display only; no gas/aerosol or airglow retrieval, no full scattering model. Static inspection cameras only.'}
    (folder/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
