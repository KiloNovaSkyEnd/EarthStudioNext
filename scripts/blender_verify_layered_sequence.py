"""Fresh-process animation/preview controls and optional stationary-camera frame renders."""
import hashlib
import json
from pathlib import Path
import sys
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.production.assets import verify_assets


def main():
    args=sys.argv[sys.argv.index('--')+1:];root=Path(args[0]).resolve()
    sequence=json.loads((root/'sequence_manifest.json').read_text(encoding='utf-8'));verify_assets(root,sequence['files']+sequence['auxiliary_files'])
    count=len(sequence['nodes']);scenes=[]
    for scene in bpy.data.scenes:
        bpy.context.window.scene=scene
        if not scene.get('layered_weather_sequence'):continue
        control=bpy.data.objects[scene.camera['earthstudio_controller']];paths=json.loads(control['earthstudio_parameter_paths'])
        formal=[o for o in scene.objects if o.get('earthstudio_layered_atmosphere') and not o.get('earthstudio_preview_proxy')]
        proxy=[o for o in scene.objects if o.get('earthstudio_preview_proxy')]
        if len(formal)!=1 or len(proxy)!=1 or proxy[0].hide_render is not True:raise ValueError('Independent formal/playback objects required')
        indices=[]
        for frame,expected in ((scene.frame_start,1),(scene.frame_end,count)):
            if scene.get('earthstudio_project_clock'):expected=min(count,frame-scene.frame_start+1)
            scene.frame_set(frame);bpy.context.view_layer.update()
            nodes=[n for n in formal[0].data.materials[0].node_tree.nodes if n.type=='TEX_IMAGE']
            actual=[1 if n.image.source=='FILE' else frame+n.image_user.frame_offset for n in nodes]
            master=json.loads((root/'native_master.json').read_text(encoding='utf-8'))
            static={a['role'] for a in master['production_layers'] if a.get('static')}
            wanted=[1 if count==1 or n.label in static else expected for n in nodes]
            if any(n.image.source!='SEQUENCE' for n in nodes if count>1 and n.label not in static):raise ValueError('Dynamic weather layer is static')
            if len(actual)!=4 or actual!=wanted:raise ValueError(f'Weather drivers did not advance: {scene.name}: {actual}, expected {wanted}')
            indices.append(actual)
        owner,key=paths['["previewHigh"]'].rsplit('.',1)
        for high in (False,True):
            setattr(control.path_resolve(owner),key,high);control.update_tag();bpy.context.view_layer.update()
            if formal[0].hide_viewport==high or proxy[0].hide_viewport!=high:raise ValueError('Preview switching did not change visibility')
            if formal[0].hide_render or not proxy[0].hide_render:raise ValueError('Viewport switch changed final render dependency')
        scenes.append(dict(scene=scene.name,first_last_indices=indices,preview_switch_verified=True))
    if not scenes:raise ValueError('No layered animation scenes')
    with Path(bpy.data.filepath).open('rb') as stream:blend_hash=hashlib.file_digest(stream,'sha256').hexdigest()
    proof=dict(schema='earthstudio.layered_animation.reopen.v1',scenes=scenes,source_L1_required=False,blend_sha256=blend_hash)
    if '--render' in args:
        scene=bpy.data.scenes[scenes[0]['scene']];bpy.context.window.scene=scene;scene.frame_set(scene.frame_start)
        old=scene.camera;camera=old.copy();camera.data=old.data.copy();camera.animation_data_clear();camera.data.animation_data_clear()
        matrix=old.matrix_world.copy();camera.parent=None
        for constraint in list(camera.constraints):camera.constraints.remove(constraint)
        camera.matrix_world=matrix;scene.collection.objects.link(camera);scene.camera=camera
        scene.render.resolution_x=320;scene.render.resolution_y=180;scene.render.resolution_percentage=100
        scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=4;scene.cycles.use_denoising=False
        outputs=[]
        for label,frame in (('first',scene.frame_start),('last',scene.frame_end)):
            scene.frame_set(frame);scene.render.filepath=str(root/f'verify_{label}.png');scene.render.image_settings.file_format='PNG'
            bpy.ops.render.render(write_still=True)
            outputs.append(hashlib.sha256(Path(scene.render.filepath).read_bytes()).hexdigest())
        if count>1 and outputs[0]==outputs[1]:raise ValueError('Actual first/last renders unchanged')
        proof['stationary_camera_weather_render_sha256']=outputs
    proof_path=Path(args[args.index('--proof')+1]) if '--proof' in args else root/'animation_reopen.json'
    proof_path.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    print('LAYERED_SEQUENCE_REOPEN_VERIFIED',json.dumps(proof,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
