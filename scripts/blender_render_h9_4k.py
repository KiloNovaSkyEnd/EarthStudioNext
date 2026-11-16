"""One native-detail 4K final-quality render, without changing saved scene."""
import bpy,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.blender_support.gpu import configure
scene=bpy.context.scene;scene.frame_set(scene.frame_end);configure(scene)
scene.render.resolution_x,scene.render.resolution_y=3840,2160;scene.render.resolution_percentage=100
scene.cycles.samples=64;scene.cycles.adaptive_min_samples=16;scene.cycles.use_denoising=False
scene.render.filepath=sys.argv[sys.argv.index('--')+1]
bpy.ops.render.render(write_still=True)
print('NATIVE_4K_RENDERED',scene.render.filepath,flush=True)
