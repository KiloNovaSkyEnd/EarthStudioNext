"""Build offline original-grid weather Earth + editable takes + two rim switches."""
import argparse
import json
import math
from pathlib import Path
import sys
import bpy
import faulthandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ges_next.camera import validate
from ges_next.isolation import require_writable
from scripts.blender_import_cesium_camera import import_track
from scripts.blender_support.editable_camera import create as rig
from scripts.blender_support.native_disk_material import create as native_disk
from scripts.blender_support.wgs84_rim import create as rim
from scripts.blender_support.gpu import configure


def main():
    faulthandler.dump_traceback_later(45, repeat=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    root, target = args.package.resolve(), require_writable(args.output)
    if target.exists():
        raise FileExistsError('Existing scene is preserved; choose a new candidate filename')
    manifest = json.loads((root/'package_manifest.json').read_text(encoding='utf-8'))
    master = json.loads((root/'native_master.json').read_text(encoding='utf-8'))
    bundle = json.loads((root/'camera_bundle.json').read_text(encoding='utf-8'))
    tracks = [validate(t) for t in bundle['tracks']]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    configure(scene)
    scene.cycles.samples = 32
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    scene.render.resolution_percentage = 100
    scene.render.fps = 30
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1
    scene.render.dither_intensity = 0
    scene.render.use_simplify = False
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure, scene.view_settings.gamma = 0, 1
    scene.world = bpy.data.worlds.new('Space · black background')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes.get('Background').inputs[0].default_value = (0, 0, 0, 1)
    cameras = []
    for track in tracks:
        print('BUILD_CAMERA', track['name'], flush=True)
        reference = import_track(scene, track, track['name'])
        editable = rig(scene, track, reference)
        reference.hide_set(True)
        cameras.append(editable or reference)
    active = bundle['timelineProject']['activeTrack']
    scene.camera = next((c for c, t in zip(cameras, tracks) if t['keyframeTrack']['id'] == active), cameras[0])
    scene.frame_start = 1
    scene.frame_end = max(math.ceil(1+t['samples'][-1]['seconds']*30) for t in tracks)
    print('BUILD_NATIVE_MATERIAL', flush=True)
    native_disk(scene, master, root/'assets')
    print('BUILD_RIM', flush=True)
    rim(scene, manifest['sun'], manifest['effects'])
    scene['earthstudio_camera_only'] = False
    scene['earthstudio_camera_tracks'] = len(tracks)
    scene['earthstudio_native_shape'] = master['shape']
    scene['earthstudio_observation_utc'] = manifest['utc']
    scene['earthstudio_weather_animated'] = False
    scene['earthstudio_missing_observations'] = 'Single H9 hemisphere only; neutral grey missing-data indicator'
    scene['earthstudio_earth_model'] = 'WGS84 ECEF; 1 Blender unit = 1000000 metres'
    scene['earthstudio_sun_ecef'] = manifest['sun']
    for name in ('package_manifest.json', 'native_master.json', 'camera_bundle.json'):
        bpy.data.texts.new(name).write((root/name).read_text(encoding='utf-8'))
    bpy.data.texts.new('START_HERE · 操作说明.txt').write('''本工程包含2026-10-20 22:40 UTC单景原始圆盘、WGS84地球、独立分镜和柔和大气。天气静止，镜头可以运动。\n
两条原有分镜来自此前已备份工程，额外A/B/C为测试镜头。\n
在场景属性→自定义属性，blueAtmosphere和nightAirglow是两个独立开关。\n
选择分镜的“参数控制器”，在物体属性→自定义属性调整经纬度、heading、pitch、rangeKm、roll、fov。动画参数改值后须插关键帧；Graph Editor可编辑速度及片长。\n
在场景相机栏选择各分镜的“可编辑相机”；原逐帧相机保留作比较。分镜有独立时长，渲染前按相机自定义属性设置结束帧。\n
材质直接读取assets内16块原生GeoColor TIFF，不经过网页截图或低分辨率全球图。灰色区域表示没有观测，不是静态地表。\n
红光网格22000×22000约500m，颜色1km、红外2km；2016年静态500m夜光已在Satpy配方内，不另叠灯。\n
请整体保留本目录和assets文件夹；采用相对路径，可离线移动。不得只复制blend文件。无需运行网页、Codex或Python后端。\n
1920×1080是默认输出画幅，可改4K。原始观测细节不随输出尺寸凭空增加。\n
这是静态单景整链小样，全球多星覆盖、连续天气和最终视觉质量仍待验收。\n''')
    scene.frame_set(1)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.region_3d.view_perspective = 'CAMERA'
                area.spaces.active.shading.type = 'MATERIAL'
                area.spaces.active.shading.use_scene_world = True
    target.parent.mkdir(parents=True, exist_ok=True)
    for image in bpy.data.images:
        if image.source == 'FILE' and image.filepath:
            image.filepath = bpy.path.relpath(image.filepath, start=str(target.parent))
    scene.render.filepath = '//renders/frame_'
    bpy.ops.wm.save_as_mainfile(filepath=str(target), relative_remap=False)
    faulthandler.cancel_dump_traceback_later()
    print('NATIVE_BRIDGE_READY', str(target), flush=True)


if __name__ == '__main__':
    main()
