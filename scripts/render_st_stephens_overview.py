import bpy
from mathutils import Vector
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "outputs"
bpy.ops.wm.open_mainfile(filepath=str((OUT/"103_Bellevue_Ave_custom_v12.blend").resolve()))

def look_at(cam, tgt):
    d = Vector(tgt)-cam.location
    cam.rotation_euler = d.to_track_quat('-Z','Y').to_euler()

scene=bpy.context.scene
scene.render.resolution_x=1920
scene.render.resolution_y=1080

for o in list(bpy.data.objects):
    if o.type=='CAMERA':
        bpy.data.objects.remove(o, do_unlink=True)

nave=bpy.data.objects['custom_nave_103_Bellevue_Ave']
porch=bpy.data.objects['custom_front_porch_103_Bellevue_Ave']
tower=bpy.data.objects['custom_tower_103_Bellevue_Ave']
chap=bpy.data.objects['custom_chapel_strip_103_Bellevue_Ave']

# front-oblique (street corner feel)
loc=Vector((porch.location.x-18, porch.location.y+34, porch.location.z+8.0))
bpy.ops.object.camera_add(location=loc)
cam=bpy.context.active_object
look_at(cam, (porch.location.x-2.5, porch.location.y+2.0, porch.location.z+4.0))
cam.data.lens=32
scene.camera=cam
scene.render.filepath=str((OUT/"103_Bellevue_Ave_custom_v12_QA_front_oblique.png").resolve())
bpy.ops.render.render(write_still=True)

# long side elevation
loc=Vector((chap.location.x+36, chap.location.y+4, chap.location.z+8.3))
bpy.ops.object.camera_add(location=loc)
cam=bpy.context.active_object
look_at(cam, (chap.location.x-2.0, chap.location.y+1.0, chap.location.z+4.2))
cam.data.lens=35
scene.camera=cam
scene.render.filepath=str((OUT/"103_Bellevue_Ave_custom_v12_QA_side_oblique.png").resolve())
bpy.ops.render.render(write_still=True)