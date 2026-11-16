"""Batch mesh construction; avoids slow high-resolution edit-mesh operators."""
def create(name, radii, columns=1024, rows=512):
    import bpy
    import numpy as np
    longitude = np.linspace(0, 2*np.pi, columns+1, dtype=np.float64)
    latitude = np.linspace(-np.pi/2, np.pi/2, rows+1, dtype=np.float64)
    x = np.cos(latitude)[:, None]*np.cos(longitude)[None, :]*radii[0]
    y = np.cos(latitude)[:, None]*np.sin(longitude)[None, :]*radii[1]
    z = np.broadcast_to(np.sin(latitude)[:, None]*radii[2], x.shape)
    vertices = np.stack((x, y, z), axis=-1).astype(np.float32).reshape(-1, 3)
    base = (np.arange(rows)[:, None]*(columns+1)+np.arange(columns)[None, :]).reshape(-1)
    faces = np.stack((base, base+1, base+columns+2, base+columns+1), axis=-1).astype(np.int32)
    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(len(vertices))
    mesh.vertices.foreach_set('co', vertices.reshape(-1))
    mesh.loops.add(faces.size)
    mesh.loops.foreach_set('vertex_index', faces.reshape(-1))
    mesh.polygons.add(len(faces))
    mesh.polygons.foreach_set('loop_start', np.arange(len(faces), dtype=np.int32)*4)
    mesh.polygons.foreach_set('loop_total', np.full(len(faces), 4, dtype=np.int32))
    mesh.polygons.foreach_set('use_smooth', np.ones(len(faces), dtype=bool))
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj
