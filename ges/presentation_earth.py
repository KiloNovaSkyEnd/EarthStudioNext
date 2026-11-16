"""User-requested flat observed clouds and blue, surface-attached display rim.

Separate from the historical scattering reference. This is an art-directed
display model, never an atmospheric retrieval. Source RGB/IR remain unchanged.
"""
from pathlib import Path
import numpy as np
from .observed_atmosphere import ObservedAtmosphereRenderer

PROFILE = 'flat-observed-blue-attached-rim-v1'


def rim_weights(tangent_height_km, solar_cosine, blue=True, warm=True):
    """CPU contract for the portable world-space shader, also used by tests."""
    h, mu = np.broadcast_arrays(np.asarray(tangent_height_km, float), np.asarray(solar_cosine, float))
    p = np.exp(-np.maximum(h, 0)/8+np.minimum(h, 0)/14)
    t = np.clip((mu+.104528)/.209056, 0, 1)
    day = t**3*(t*(6*t-15)+10)
    return .50*p*day*bool(blue), .13*p*(1-day)*bool(warm)


class PresentationEarthRenderer(ObservedAtmosphereRenderer):
    def _fragment_shader(self):
        shader = super()._fragment_shader()
        shader = shader.replace('#version 330', '#version 330\nuniform bool presentation_flat;', 1)
        # The dormant reference branch keeps the parent uniform API intact.
        # The presentation branch never calls cloud_height/local_normal/shadows.
        marker = '    if(!city_lights_enabled)night=vec3(0.);'
        assert shader.count(marker) == 1
        shader = shader.replace(marker, marker+'''
    if(presentation_flat)return night*(1.-c2(-.1045,.04,dot(n,sun_direction)))*city_light_gain;''')
        start = shader.index('    vec2 top=roots(camera_position,ray,R+8.4);')
        end = shader.index('    vec3 apparent_ir_base=base', start)
        reference = shader[start:end]
        shader = shader[:start]+'''    if(presentation_flat){
        if(hit&&clouds_enabled){
            vec3 point=camera_position+ray*ground.x;
            vec4 cloud=material(point,ray,dx,dy,ground.x);
            base=cloud.rgb*cloud.a+base*(1.-cloud.a);
        }
        // Exactly the same sphere for all IR classes and VIS. No shell,
        // oblique optical-depth exaggeration, relief normals or cloud shadows.
        finish=hit?ground.x:finish;
    }else{
'''+reference+'    }\n'+shader[end:]
        start = shader.index('    float observed_path_fraction=1.;')
        end = shader.index('    if(observed_coverage_debug)base=apparent_coverage_output;', start)
        reference = shader[start:end]
        limb = (Path(__file__).parent/'shaders/presentation_limb.glsl').read_text(encoding='utf-8')
        shader = shader[:start]+'    if(presentation_flat){\n'+limb+'\n    }else{\n'+reference+'    }\n'+shader[end:]
        return shader

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        with self.ctx:
            self.program['presentation_flat'].value = True

    def update(self, rgba, height, metadata):
        # Delivered L2 fields remain untouched in storage; display ignores heights.
        super().update(rgba, np.full((1, 1), np.nan, np.float32), metadata)
