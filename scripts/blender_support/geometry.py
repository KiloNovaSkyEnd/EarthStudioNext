"""Geographic sphere meshes; Blender-only and independent of old renderers."""
import math
import bpy
from mathutils import Vector


def position(lon,lat,radius):
    lon,lat=map(math.radians,(lon,lat))
    return Vector((radius*math.cos(lat)*math.cos(lon),radius*math.cos(lat)*math.sin(lon),radius*math.sin(lat)))


def mesh_patch(name,bounds,radius,cols,rows):
    w,s,e,n=bounds
    vertices=[position(w+(e-w)*x/cols,s+(n-s)*y/rows,radius) for y in range(rows+1) for x in range(cols+1)]
    faces=[]
    for y in range(rows):
        for x in range(cols):
            a=y*(cols+1)+x; faces.append((a,a+1,a+cols+2,a+cols+1))
    mesh=bpy.data.meshes.new(name); mesh.from_pydata(vertices,[],faces); mesh.update()
    uv=mesh.uv_layers.new(name='Geographic UV')
    for polygon in mesh.polygons:
        polygon.use_smooth=True
        for loop in polygon.loop_indices:
            vertex=mesh.loops[loop].vertex_index
            uv.data[loop].uv=(vertex%(cols+1)/cols,vertex//(cols+1)/rows)
    obj=bpy.data.objects.new(name,mesh); bpy.context.collection.objects.link(obj)
    return obj
