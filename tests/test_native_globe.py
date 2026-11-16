"""Render the shipped preview shader on GPU and verify geographic orientation."""
from pathlib import Path
import re
import unittest
import numpy as np
import moderngl

ROOT = Path(__file__).resolve().parents[1]


class NativeGlobeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / 'native/EarthStudio.App/Preview/globe.js').read_text(encoding='utf-8')
        fragment = re.search(r'const fragment = `(.*?)`;', source, re.S).group(1)
        fragment = fragment.replace('precision highp float;', '#version 330\nout vec4 pixel;')
        fragment = fragment.replace('varying vec2 v;', 'in vec2 v;').replace('texture2D(', 'texture(').replace('gl_FragColor', 'pixel')
        cls.fragment_source = fragment
        cls.vertex_source = '''#version 330
            in vec2 p; out vec2 v; void main(){v=p;gl_Position=vec4(p,0,1);}'''
        cls.ctx = moderngl.create_standalone_context()
        cls.program = cls.ctx.program(vertex_shader=cls.vertex_source, fragment_shader=fragment)
        buffer = cls.ctx.buffer(np.array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1], np.float32).tobytes())
        cls.vao = cls.ctx.simple_vertex_array(cls.program, buffer, 'p')
        cls.buffer = buffer
        cls.target = cls.ctx.simple_framebuffer((201,201), components=4, dtype='f4')
        # Texture rows are south->north, matching the shipped UNPACK_FLIP_Y upload.
        lon = (np.arange(720)+.5)/720
        lat = (np.arange(360)+.5)/360
        values = np.empty((360,720,3), np.float32)
        values[...,0] = lon[None,:]
        values[...,1] = lat[:,None]
        values[...,2] = .25
        cls.texture = cls.ctx.texture((720,360), 3, values.tobytes(), dtype='f4')
        cls.texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        cls.texture.repeat_x = False
        cls.texture.repeat_y = False

    @classmethod
    def tearDownClass(cls):
        for value in (cls.texture, cls.target, cls.vao, cls.buffer, cls.program, cls.ctx):
            value.release()

    def render(self, longitude, latitude):
        yaw, pitch = np.deg2rad([-longitude, latitude])
        cp,sp,cy,sy = np.cos(pitch),np.sin(pitch),np.cos(yaw),np.sin(yaw)
        p = self.program
        p['camera'].value = (3.25*cp*cy, 3.25*sp, 3.25*cp*sy)
        p['right'].value = (sy,0,-cy)
        p['up'].value = (-sp*cy,cp,-sp*sy)
        width,height = self.target.size
        p['resolution'].value = (width,height)
        p['surface'].value = 0
        p['loaded'].value = True
        self.target.use()
        self.texture.use(0)
        self.vao.render()
        return np.frombuffer(self.target.read(components=4,dtype='f4'),np.float32).reshape(height,width,4)

    def test_center_longitude_latitude_at_multiple_viewpoints(self):
        for longitude,latitude in [(0,0),(110,20),(-100,40),(80,-35)]:
            with self.subTest(longitude=longitude,latitude=latitude):
                pixel = self.render(longitude,latitude)[100,100,:3]
                n = np.array([np.cos(np.deg2rad(latitude))*np.cos(np.deg2rad(longitude)),
                              np.sin(np.deg2rad(latitude)),
                              -np.cos(np.deg2rad(latitude))*np.sin(np.deg2rad(longitude))])
                light = .42+.58*max(0,np.dot(n,np.array([-1,1,2])/np.sqrt(6)))
                # GPU transcendental/texture precision: below 1/32 of one latitude texel.
                np.testing.assert_allclose(pixel[:2]/light, [(longitude+180)/360,(latitude+90)/180],atol=1/360/32)

    def test_screen_right_is_east_and_screen_up_is_north(self):
        image = self.render(0,0)
        # Ratios remove the shader's lighting from the geographic color ramp.
        east = image[100,120,0]/image[100,120,2]
        west = image[100,80,0]/image[100,80,2]
        north = image[120,100,1]/image[120,100,2]
        south = image[80,100,1]/image[80,100,2]
        self.assertGreater(east,west)
        self.assertGreater(north,south)
