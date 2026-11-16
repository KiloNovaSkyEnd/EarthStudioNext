"""Node-based finite-path emission transport. No viewport-dependent radial painting.
Layer quadrature, Earth occultation, per-sample solar visibility and RGB extinction.
"""
import math
import numpy as np
from .airglow_parameters import LAYERS,R

def group():
 import bpy
 from .shader_math import Nodes
 tree=bpy.data.node_groups.new('Research R3 · finite-path layered airglow','ShaderNodeTree')
 for name,typ in [('Closest','NodeSocketVector'),('Direction','NodeSocketVector'),('Sun','NodeSocketVector'),('Impact','NodeSocketFloat'),('CameraS','NodeSocketFloat'),('Density','NodeSocketFloat'),('Thickness','NodeSocketFloat')]:tree.interface.new_socket(name=name,in_out='INPUT',socket_type=typ)
 tree.interface.new_socket(name='Radiance',in_out='OUTPUT',socket_type='NodeSocketColor')
 n=Nodes(tree);m,v=n.m,n.v;inp=n.node('NodeGroupInput');out=n.node('NodeGroupOutput');p=inp.outputs
 impact=p['Impact'];b2=m('MULTIPLY',impact,impact);cam=p['CameraS']
 ground=m('SQRT',m('MAXIMUM',0.,m('SUBTRACT',R*R,b2)))
 block=m('MULTIPLY',m('LESS_THAN',impact,R),m('GREATER_THAN',cam,ground))
 lower=m('ADD',m('MULTIPLY',ground,block),m('MULTIPLY',-10000.,m('SUBTRACT',1.,block)))
 height=m('SUBTRACT',impact,R)
 width=m('MINIMUM',2.,m('MAXIMUM',.5,p['Thickness']))
 H=8.;scale=m('SQRT',m('MULTIPLY',2*H,m('MAXIMUM',R,impact)))
 def erf(x):return m('TANH',m('ADD',m('MULTIPLY',1.128379167,x),m('MULTIPLY',.1,m('MULTIPLY',m('MULTIPLY',x,x),x))))
 cam_erf=erf(m('DIVIDE',cam,scale))
 column_base=m('MULTIPLY',m('EXPONENT',m('MULTIPLY',m('MAXIMUM',-1.,height),-1/H)),m('SQRT',m('MULTIPLY',math.pi*H/2,m('MAXIMUM',R,impact))))
 total=(0.,0.,0.)
 gx,gw=np.polynomial.legendre.leggauss(12)
 for layer in LAYERS:
  sigma=m('MULTIPLY',layer['sigma'],width)
  low_alt=m('MAXIMUM',0.,m('SUBTRACT',layer['height'],m('MULTIPLY',4.,sigma)))
  high_alt=m('ADD',layer['height'],m('MULTIPLY',4.,sigma))
  lo_radius=m('ADD',R,low_alt);hi_radius=m('ADD',R,high_alt)
  slo=m('SQRT',m('MAXIMUM',0.,m('SUBTRACT',m('MULTIPLY',lo_radius,lo_radius),b2)))
  shi=m('SQRT',m('MAXIMUM',0.,m('SUBTRACT',m('MULTIPLY',hi_radius,hi_radius),b2)))
  for near in (True,False):
   start=slo if near else m('MULTIPLY',-1.,shi)
   end=shi if near else m('MULTIPLY',-1.,slo)
   start=m('MAXIMUM',start,lower);end=m('MAXIMUM',start,m('MINIMUM',end,cam))
   half=m('MULTIPLY',.5,m('SUBTRACT',end,start));mid=m('MULTIPLY',.5,m('ADD',end,start))
   for x,w in zip(gx,gw):
    s=m('ADD',mid,m('MULTIPLY',float(x),half))
    pos=v('SUBTRACT',p['Closest'],v('SCALE',p['Direction'],s))
    altitude=m('SUBTRACT',m('SQRT',m('ADD',b2,m('MULTIPLY',s,s))),R)
    z=m('DIVIDE',m('SUBTRACT',altitude,layer['height']),sigma)
    emission=m('EXPONENT',m('MULTIPLY',-.5,m('MULTIPLY',z,z)))
    # Visibility/exposure taper, NOT a full photochemical model. C2 quintic,
    # evaluated at each emitting point, not the ground/closest-point terminator.
    cosine=v('DOT_PRODUCT',v('NORMALIZE',pos),p['Sun'])
    u=m('MINIMUM',1.,m('MAXIMUM',0.,m('DIVIDE',m('SUBTRACT',.02,cosine),.32)))
    smooth=m('MULTIPLY',m('MULTIPLY',m('MULTIPLY',u,u),u),m('ADD',10.,m('MULTIPLY',u,m('SUBTRACT',m('MULTIPLY',6.,u),15.))))
    strength=m('MULTIPLY',m('MULTIPLY',emission,smooth),m('MULTIPLY',float(w)*layer['gain'],half))
    column=m('MAXIMUM',0.,m('MULTIPLY',column_base,m('SUBTRACT',cam_erf,erf(m('DIVIDE',s,scale)))))
    rgb=[]
    for c,beta in zip(layer['color'],(.005802,.013558,.033100)):
     rgb.append(m('MULTIPLY',c,m('EXPONENT',m('MULTIPLY',-beta,column))))
    contribution=v('SCALE',n.combine(rgb),strength)
    total=v('ADD',total,contribution)
 total=v('SCALE',total,p['Density']);n.put(total,out.inputs['Radiance'])
 return tree

def ray_inputs(n,proxy_material,sun,density,thickness):
 from .native_disk_material import A,B
 m,v=n.m,n.v
 geometry=n.node('ShaderNodeNewGeometry');camera=n.node('ShaderNodeCameraData')
 incoming=v('NORMALIZE',geometry.outputs['Incoming'])
 origin_world=v('ADD',geometry.outputs['Position'],v('SCALE',incoming,camera.outputs['View Distance']))
 origin=v('MULTIPLY',origin_world,(R/A,R/A,R/B))
 direction=v('NORMALIZE',v('MULTIPLY',v('SCALE',incoming,-1.),(1/A,1/A,1/B)))
 t=m('MULTIPLY',-1.,v('DOT_PRODUCT',origin,direction))
 closest=v('ADD',origin,v('SCALE',direction,t))
 g=n.node('ShaderNodeGroup');g.node_tree=proxy_material
 for name,value in [('Closest',closest),('Direction',direction),('Sun',sun),('Impact',v('LENGTH',closest)),('CameraS',t),('Density',density),('Thickness',thickness)]:n.put(value,g.inputs[name])
 first=m('MAXIMUM',m('SUBTRACT',1.,geometry.outputs['Backfacing']),m('LESS_THAN',v('LENGTH',origin),R+500.))
 return g.outputs['Radiance'],first

