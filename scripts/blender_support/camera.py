"""Editable orbit with a stable tracking target; no Euler angle interpolation."""
import bpy
from mathutils import Vector
from .geometry import position

PILOT_KEYS=[(1,-75,15,30000,-75,0),(32,0,15,27000,0,0),(64,85,20,21000,85,10),
            (80,127,25,7600,127,25),(96,138,20,7350,127,25)]
FULL_KEYS=[(1,-75,15,30000,-75,0),(49,-10,15,28000,-10,0),(97,30,10,26000,30,0),
           (145,75,15,24000,75,0),(209,125,25,21000,125,10),
           (241,125,22,8200,125,22),(268,136,18,7800,125,22),(292,130,25,7600,125,22)]


def create(scene,full=False):
    camera=bpy.data.objects.new('Camera · freely editable',bpy.data.cameras.new('Camera'))
    scene.collection.objects.link(camera); scene.camera=camera
    camera.data.lens=35; camera.data.clip_start=.1; camera.data.clip_end=100000
    aim=bpy.data.objects.new('Camera aim · move to reframe',None); scene.collection.objects.link(aim)
    tracking=camera.constraints.new('TRACK_TO'); tracking.target=aim
    tracking.track_axis='TRACK_NEGATIVE_Z'; tracking.up_axis='UP_Y'
    for frame,lon,lat,radius,tlon,tlat in (FULL_KEYS if full else PILOT_KEYS):
        camera.location=position(lon,lat,radius)
        aim.location=Vector((0,0,0)) if radius>15000 else position(tlon,tlat,6371)
        camera.keyframe_insert('location',frame=frame); aim.keyframe_insert('location',frame=frame)
    for obj in (camera,aim):
        for layer in obj.animation_data.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for point in curve.keyframe_points: point.interpolation='LINEAR'
    check(scene)
    return camera


def check(scene):
    camera=scene.camera
    for frame in range(1,scene.frame_end+1):
        scene.frame_set(frame); bpy.context.view_layer.update()
        origin=camera.matrix_world.translation
        direction=camera.matrix_world.to_quaternion() @ Vector((0,0,-1))
        projection=-origin.dot(direction)
        distance2=origin.length_squared-projection*projection
        if origin.length<6479 or projection<=0 or distance2>6371**2:
            raise ValueError(f'Camera misses Earth at frame {frame}')
