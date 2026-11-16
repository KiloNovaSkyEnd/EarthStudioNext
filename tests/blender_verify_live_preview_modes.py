"""Exercise actual GUI playback transitions; leave a paused clear composition."""
import json
from pathlib import Path
import bpy

root = Path(__file__).resolve().parents[1]
scene = bpy.context.scene
window = bpy.context.window
area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
area.spaces.active.shading.type = 'MATERIAL'
area.spaces.active.shading.use_scene_world = True
area.spaces.active.overlay.show_overlays = False
area.spaces.active.region_3d.view_perspective = 'CAMERA'
area.spaces.active.show_region_ui = True
control = bpy.data.objects[scene.camera['earthstudio_controller']]
path = json.loads(control['earthstudio_parameter_paths'])['["previewHigh"]']
events = []


def record(label, expected):
    high = bool(control.path_resolve(path))
    events.append(dict(state=label,playing=window.screen.is_animation_playing,high_detail=high))
    assert high == expected, events


def start():
    record('initial_pause', True)
    with bpy.context.temp_override(window=window, area=area, region=region):
        assert not window.screen.is_animation_playing
        bpy.ops.screen.animation_play()
    bpy.app.timers.register(stop, first_interval=6)


def stop():
    record('playing', False)
    with bpy.context.temp_override(window=window, area=area, region=region):
        assert window.screen.is_animation_playing
        bpy.ops.screen.animation_play()
    bpy.app.timers.register(finish, first_interval=3)


def finish():
    blocked = bool(scene.get('earthstudio_preview_memory_warning'))
    record('paused_after_play_memory_guard' if blocked else 'paused_after_play', not blocked)
    (root/'reports/h9_11k_optimization/live_preview_mode_guard_verification.json').write_text(json.dumps(dict(events=events,memory_fallback=blocked),indent=2))
    print('LIVE_PREVIEW_MODE_SWITCH_VERIFIED', events, flush=True)


bpy.app.timers.register(start, first_interval=15)
