"""Blender camera footprint -> bounded, repeatable native cell requests."""
import json
import math
from pathlib import Path
import uuid
import bpy
from mathutils import Vector


def footprint(scene,frame,force_level=None):
    scene.frame_set(frame); bpy.context.view_layer.update()
    camera=scene.camera.evaluated_get(bpy.context.evaluated_depsgraph_get())
    origin=camera.matrix_world.translation
    corners=camera.data.view_frame(scene=scene)
    xs=[p.x/(-p.z) for p in corners]; ys=[p.y/(-p.z) for p in corners]
    width=scene.render.resolution_x*scene.render.resolution_percentage/100
    pixel_km=2*max(1,origin.length-6371)*max(abs(v) for v in xs)/width
    level=max(0,min(3,int(math.floor(math.log2(max(.434,pixel_km/2)/.434)))))
    if force_level is not None: level=force_level
    if scene.get('earth_force_finest',False): level=0
    span=5*2**level; columns=360//span; rows=math.ceil(180/span)
    cells=set()
    # The Earth limb is sampled too; all actual screen intersections are
    # conservatively expanded by one geographic cell below.
    for j in range(25):
        for i in range(41):
            ray=camera.matrix_world.to_3x3() @ Vector((min(xs)+(max(xs)-min(xs))*i/40,
                                                     min(ys)+(max(ys)-min(ys))*j/24,-1))
            ray.normalize(); b=origin.dot(ray); disc=b*b-origin.length_squared+6371**2
            if disc<0: continue
            t=-b-math.sqrt(disc)
            if t<=0: continue
            point=origin+t*ray
            lon=math.degrees(math.atan2(point.y,point.x))
            lat=math.degrees(math.asin(max(-1,min(1,point.z/6371))))
            if abs(lat)>=70: continue
            c=min(columns-1,int((lon+180)//span)); r=min(rows-1,int((lat+90)//span))
            margin=5 if level==0 else 2
            for dlon in (-margin,0,margin):
                for dlat in (-margin,0,margin):
                    cc=int((lon+dlon+180)//span)%columns
                    rr=int((lat+dlat+90)//span)
                    if 0<=rr<rows:
                        south=-90+rr*span
                        if south<70 and south+span>-70: cells.add((cc,rr,level))
    return sorted(cells)


def write(scene,all_nodes=False):
    root=Path(scene['earth_project_root'])
    nodes=json.loads(scene['weather_utc_nodes']); hold=int(scene['weather_hold_frames'])
    old=scene.frame_current
    selected=range(len(nodes)) if all_nodes else [min(len(nodes)-1,max(0,(old-1)//hold))]
    jobs=[]
    try:
        for index in selected:
            first=index*hold+1; last=(index+1)*hold
            cells=set()
            for frame in range(first,last+1): cells.update(footprint(scene,frame))
            levels={cell[2] for cell in cells}
            if len(levels)>1:
                level=min(levels); cells=set()
                for frame in range(first,last+1): cells.update(footprint(scene,frame,level))
            if len(cells)>512:
                raise ValueError('此机位覆盖超过512块原始细节。请先选择近景时间段，或使用全球代理预览；未降低原始清晰度。')
            jobs.append({'nominal_utc':nodes[index],'cells':sorted(cells),'display_frames':[first,last]})
    finally: scene.frame_set(old)
    folder=root/'requests'; folder.mkdir(exist_ok=True)
    path=folder/f'camera_{uuid.uuid4().hex[:12]}.json'
    path.write_text(json.dumps({'nodes':jobs,'blend_file':bpy.data.filepath},ensure_ascii=False,indent=2),encoding='utf-8')
    return path
