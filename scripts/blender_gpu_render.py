"""Executed after loading a scene and before Blender's -f render argument."""
from pathlib import Path
import sys
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parent))
from blender_support.gpu import configure
configure(bpy.context.scene)
