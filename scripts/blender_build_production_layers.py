"""Create a separate editable one-scan production scene from the accepted template."""
import json
from pathlib import Path
import sys
import bpy

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable
from ges_next.production.assets import digest, verify_assets
from scripts.blender_support.dual_airglow import create
from scripts.blender_support.production_layers import configure


def main():
    package=Path(sys.argv[sys.argv.index('--')+1]).resolve()
    output=require_writable(package/'EarthStudio_JPEG_独立灯光.blend')
    if output.exists(): raise FileExistsError(output)
    manifest=json.loads((package/'commit.json').read_text(encoding='utf-8'))
    verify_assets(package,manifest['assets'])
    master={'shape':manifest['grid']['shape'],'extent':manifest['grid']['extent'],
            'production_layers':manifest['assets']}
    sun=manifest.get('sun_ecef')
    if sun is None:
        solar=json.loads((package/'solar.json').read_text(encoding='utf-8'))
        if solar['utc']!=manifest['utc']: raise ValueError('Solar UTC differs')
        sun=solar['sun_ecef']
    for scene in bpy.data.scenes:
        bpy.context.window.scene=scene
        control=bpy.data.objects[scene.camera['earthstudio_controller']]
        configure(control)
        paths=json.loads(control['earthstudio_parameter_paths'])
        for obj in list(scene.objects):
            if obj.get('earthstudio_layered_atmosphere') or obj.get('earthstudio_preview_proxy'):
                bpy.data.objects.remove(obj,do_unlink=True)
            elif obj.name.startswith(('WGS84 Earth','大气显示')):
                obj.hide_render=True;obj.hide_viewport=True
        master['production_control']=control.name
        create(scene,master,package,{},sun,control,paths)
        scene['production_utc']=manifest['utc']
        scene['production_manifest_sha256']=digest(package/'commit.json')
        scene['production_single_scan']=True
        scene['production_note']='单时次分层验证；旧天气视频不用于本场景。地面夜景参数在运镜控制器的中文修改器面板。'
        # Disable the previous sequence viewport; it has different baked-in lights.
        for obj in scene.objects:
            if obj.get('earthstudio_preview_proxy') or '流畅预览' in obj.name or 'viewport' in obj.name.lower():
                obj.hide_render=True;obj.hide_viewport=True
        scene.frame_set(1)
    allowed={(package/a['path']).resolve() for a in manifest['assets']}
    for image in list(bpy.data.images):
        if image.source in ('FILE','SEQUENCE','MOVIE'):
            resolved=Path(bpy.path.abspath(image.filepath)).resolve()
            if resolved not in allowed:
                bpy.data.images.remove(image,do_unlink=True)
            else:
                image.filepath='//'+resolved.relative_to(package).as_posix()
    bpy.data.texts.new('生产分层说明.txt').write('JPG正式颜色层＋无损支持/传输标量遮罩。地面夜景可独立开关、亮度、色相、饱和度、RGB染色；蓝色大气和夜间气辉保持各自控制。此包仅一个真实时次，不代表动画序列已迁移。')
    bpy.ops.wm.save_as_mainfile(filepath=str(output),relative_remap=False)
    print('PRODUCTION_BLEND_READY',str(output),flush=True)


if __name__=='__main__': main()
