"""Shared immutable scientific/post-editing profile for scan and queue owners."""
def h9_profile(quality,night_metres,night_mode=None):
    if night_metres not in (500,1000):raise ValueError("Night resolution must be500 or1000 metres")
    profile=dict(quality=quality,night_metres=night_metres,grid_shape=[11000,11000],require_rebuild_recipe=True,
        required_capabilities=['groundEnabled','groundBrightness','groundHue','groundSaturation',
            'groundTintR','groundTintG','groundTintB','blueAtmosphere','nightAirglow',
            *[prefix+suffix for prefix in ('blue','warm') for suffix in ('Density','Thickness','Hue','Saturation','Brightness')]])

    if night_metres==500:profile["night_grid_shape"]=[22000,22000]
    from ges_next.algorithms.night_modes import recipe
    selected=recipe({'NightMode':night_mode})
    if selected.mode!='geocolor':profile['night_recipe']=selected.identity()
    return profile
