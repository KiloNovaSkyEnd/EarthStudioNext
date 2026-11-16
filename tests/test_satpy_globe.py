import unittest
import numpy as np
from ges.satpy_globe import SatpyGlobeRenderer,rim_profile
from ges.atmosphere_scattering import geographic,camera_basis


class SoftRimTests(unittest.TestCase):
    def test_soft_profile_attached_and_restricted_inside(self):
        h=np.array([-12.,-6.,0.,6.,18.,36.])
        p=rim_profile(h)
        self.assertEqual(p.argmax(),2)
        self.assertLess(p[0],2e-8)
        self.assertGreater(p[4],.6)
        self.assertLess(abs(float(rim_profile(-1e-5)-rim_profile(1e-5))),1e-9)

    def test_stock_pixels_unchanged_interior_and_camera_return(self):
        rgb=np.full((64,64,3),[110,140,160],np.uint8)
        meta=dict(composite='geo_color',shape=[64,64],nominal_utc='2026-10-20T19:20:00Z',extent=[-5500000,-5500000,5500000,5500000],
            projection=dict(proj='geos',sweep='y',a=6378137.,b=6356752.3,h=35785863.,lon_0=140.7))
        r=SatpyGlobeRenderer(rgb,meta,192,128,1)
        cam=dict(position=geographic(140.7,0,42164),target=np.zeros(3),up=np.array([0.,0.,1.]),fov=21.)
        try:
            off=r.render(cam,False,False)
            np.testing.assert_allclose(off[64,96],rgb[32,32],atol=1)
            on=r.render(cam)
            right,up,forward=camera_basis(cam['position'],cam['target'],cam['up'])
            yy,xx=np.indices((128,192))
            rays=forward+np.tan(np.deg2rad(10.5))*((2*(xx+.5)-192)[...,None]/128*right+(128-2*(yy+.5))[...,None]/128*up)
            rays/=np.linalg.norm(rays,axis=-1,keepdims=True)
            h=np.linalg.norm(np.cross(cam['position'],rays),axis=-1)-6371
            # At this coarse disk size a pixel spans tens of km. Stay beyond
            # the 4x4 silhouette quadrature footprint, not just its centre ray.
            np.testing.assert_array_equal(on[h < -120],off[h < -120])
            r.render(dict(cam,fov=25.))
            np.testing.assert_array_equal(on,r.render(cam))
        finally:r.close()


if __name__=='__main__':unittest.main()
