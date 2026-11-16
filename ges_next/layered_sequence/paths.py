from pathlib import Path

def layer_path(root,sequence,component,index,preview=False):
    if component in sequence.get('static_components',[]):index=1
    ext='jpg' if component in ('base','night') else 'png'
    return Path(root)/('preview_layers' if preview else 'assets')/component/f'weather_{index:04d}.{ext}'
