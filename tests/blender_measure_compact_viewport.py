"""Live GUI redraw sampling on a separate saved test project; no source edits."""
import json
from pathlib import Path
import time
import sys

import bpy

root = Path(__file__).resolve().parents[1]
out = root / 'reports/h9_11k_optimization'
scene = next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track') == 'WEB_1')
bpy.context.window.scene = scene
window = bpy.context.window
area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
area.spaces.active.shading.type = 'MATERIAL'
area.spaces.active.shading.use_scene_world = True
area.spaces.active.overlay.show_overlays = False
area.spaces.active.region_3d.view_perspective = 'CAMERA'
scene.sync_mode = 'FRAME_DROP'
scene.frame_set(1)
proxy = next(o for o in scene.objects if o.get('earthstudio_preview_proxy'))
movie = next(n for n in proxy.data.materials[0].node_tree.nodes if n.type == 'TEX_IMAGE')
tag = sys.argv[sys.argv.index('--')+1] if '--' in sys.argv else ''
state = dict(start=None, last=None, draws=[], owned_playback=False, already_playing=False)


def draw():
    if state['start'] is None or state['last'] == scene.frame_current:
        return
    state['last'] = scene.frame_current
    state['draws'].append(dict(wall_seconds=time.perf_counter() - state['start'],
                              frame=scene.frame_current,
                              weather_index=round(scene.frame_current + movie.image_user.frame_offset)))


handle = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')


def finish():
    with bpy.context.temp_override(window=window, area=area, region=region):
        if state['owned_playback'] and window.screen.is_animation_playing:
            bpy.ops.screen.animation_play()
    elapsed = time.perf_counter() - state['start']
    bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
    draws = state['draws']
    gaps = sorted(b['wall_seconds'] - a['wall_seconds'] for a, b in zip(draws, draws[1:]))
    report = dict(mode='actual visible Blender MATERIAL viewport, separate optimized saved project',
                  elapsed_seconds=elapsed, distinct_animation_draws=len(draws),
                  observed_animation_draws_per_second=len(draws) / elapsed,
                  largest_draw_gap_seconds=max(gaps, default=None),
                  p95_draw_gap_seconds=gaps[min(len(gaps)-1, int(len(gaps)*.95))] if gaps else None,
                  distinct_weather_nodes=len({d['weather_index'] for d in draws}), draws=draws,
                  frame_drop_enabled=True, warmup_seconds=15,
                  already_playing_at_start=state['already_playing'],
                  source_project_not_overwritten=True)
    (out / ('live_viewport_playback'+tag+'.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    if state['owned_playback']:scene.frame_set(scene.frame_end)
    print('LIVE_VIEWPORT_BENCHMARK_COMPLETE', json.dumps({k:v for k,v in report.items() if k!='draws'}), flush=True)
    return None


def start():
    state['already_playing']=window.screen.is_animation_playing
    state['owned_playback']=not state['already_playing']
    if state['owned_playback']:scene.frame_set(1)
    state['start'] = time.perf_counter()
    with bpy.context.temp_override(window=window, area=area, region=region):
        if not window.screen.is_animation_playing:bpy.ops.screen.animation_play()
    bpy.app.timers.register(finish, first_interval=12)
    return None


bpy.app.timers.register(start, first_interval=15)
