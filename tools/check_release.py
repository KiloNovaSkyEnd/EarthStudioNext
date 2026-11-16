"""Check the normal assets and bundled runtimes after extraction."""
from pathlib import Path
import argparse
import subprocess

from ges_next.night_resources import resolve as night_reference
from ges_next.pipeline.plan import runtime_signature
from ges_next.reference_resources import resolve as auxiliary_reference

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", action="store_true", help="Open and check the bundled project template")
    parser.add_argument("--ai", action="store_true", help="Check the AI-VIS model and runtime imports")
    args = parser.parse_args()

    import boto3
    import dask
    import imageio_ffmpeg
    import netCDF4
    import numpy
    import rasterio
    import satpy

    for metres in (500, 1000):
        path = night_reference(check_pixels=True, metres=metres)
        with rasterio.open(path) as raster:
            tile = raster.read(1, window=((10000, 10008), (10000, 10008)))
            assert tile.shape == (8, 8)
        print(f"Night reference {metres} m: {path.name}")

    print(f"Scientific dependencies: Satpy {satpy.__version__}, NumPy {numpy.__version__}, GDAL {rasterio.__gdal_version__}")
    print(f"GeoColor runtime: {len(runtime_signature())} hashed files")
    print(f"Auxiliary reference: {auxiliary_reference()}")
    print(f"FFmpeg: {imageio_ffmpeg.get_ffmpeg_version()}")

    if args.blender:
        executable = ROOT / "Runtime/Blender/blender.exe"
        template = ROOT / "resources/blender/production_template.blend"
        subprocess.run(
            [str(executable), "--background", "--factory-startup", "--disable-autoexec",
             str(template), "--python-exit-code", "5", "--python-expr",
             "import bpy; assert len(bpy.data.scenes) >= 1; print('Earth Studio template opened')"],
            check=True,
        )

    if args.ai:
        from ges_next.production.night_layers import preflight

        preflight({"NightMode": "ai-vis", "NightLightMetres": 1000})
        executable = ROOT / "Runtime/AI/python.exe"
        subprocess.run(
            [str(executable), "-c", "import torch, cv2, safetensors; print(torch.__version__, torch.cuda.is_available())"],
            check=True,
        )


if __name__ == "__main__":
    main()
