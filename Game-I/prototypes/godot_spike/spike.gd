extends Node3D
## The agreed engine test: the same character models, cape, trees, terrain, sun shadow and particle
## burst, posed by code every frame, timed for a fixed span, and written out as JSON.
## Arguments after "--": seconds=60 out=res.json ssao=1 shadows=1

const CHARACTERS := ["YELLOW", "WHITE", "GREEN", "BLACK", "RED"]
const TREES := 300

var seconds := 60.0
var out_path := "user://result.json"
var use_ssao := true
var use_shadows := true
var bodies: Array = []
var frame_ms: PackedFloat32Array = []
var elapsed := 0.0
var warm := 5.0
var last_us := 0
var burst_timer := 0.0
var burst: GPUParticles3D


func _ready() -> void:
	for argument in OS.get_cmdline_user_args():
		var parts: PackedStringArray = argument.split("=")
		if parts.size() != 2:
			continue
		match parts[0]:
			"seconds": seconds = float(parts[1])
			"out": out_path = parts[1]
			"ssao": use_ssao = parts[1] == "1"
			"shadows": use_shadows = parts[1] == "1"
	_build_environment()
	_build_terrain()
	_build_trees()
	_build_characters()
	_build_particles()
	var camera := Camera3D.new()
	camera.position = Vector3(0, 3.2, 8.5)
	camera.fov = 65.0
	add_child(camera)
	camera.look_at(Vector3(0, 1.6, 0))
	last_us = Time.get_ticks_usec()


func _build_environment() -> void:
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-46, 32, 0)
	sun.light_color = Color(1.0, .95, .88)
	sun.shadow_enabled = use_shadows
	sun.directional_shadow_max_distance = 80.0
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_ORTHOGONAL
	add_child(sun)
	var sky := ProceduralSkyMaterial.new()
	var environment := Environment.new()
	environment.background_mode = Environment.BG_SKY
	environment.sky = Sky.new()
	environment.sky.sky_material = sky
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	environment.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	environment.ssao_enabled = use_ssao
	environment.fog_enabled = true
	environment.fog_density = .0006
	var node := WorldEnvironment.new()
	node.environment = environment
	add_child(node)


func _build_terrain() -> void:
	var mesh := PlaneMesh.new()
	mesh.size = Vector2(2400, 2400)
	mesh.subdivide_width = 200
	mesh.subdivide_depth = 200
	var material := StandardMaterial3D.new()
	material.albedo_color = Color(.33, .42, .2)
	material.roughness = .95
	mesh.material = material
	var ground := MeshInstance3D.new()
	ground.mesh = mesh
	ground.position.y = -.25
	add_child(ground)


func _build_trees() -> void:
	var trunk := CylinderMesh.new()
	trunk.top_radius = .35
	trunk.bottom_radius = .55
	trunk.height = 8.0
	trunk.radial_segments = 8
	var trunk_material := StandardMaterial3D.new()
	trunk_material.albedo_color = Color(.3, .22, .15)
	trunk.material = trunk_material
	var crown := CylinderMesh.new()
	crown.top_radius = .1
	crown.bottom_radius = 3.6
	crown.height = 10.0
	crown.radial_segments = 10
	var crown_material := StandardMaterial3D.new()
	crown_material.albedo_color = Color(.12, .3, .15)
	crown.material = crown_material
	var random := RandomNumberGenerator.new()
	random.seed = 4107
	for part in [[trunk, 3.6], [crown, 11.0]]:
		var multi := MultiMesh.new()
		multi.transform_format = MultiMesh.TRANSFORM_3D
		multi.mesh = part[0]
		multi.instance_count = TREES
		random.seed = 4107
		for index in TREES:
			var spot := Vector3(random.randf_range(-260, 260), part[1], random.randf_range(-320, -12))
			multi.set_instance_transform(index, Transform3D(Basis(), spot))
		var instance := MultiMeshInstance3D.new()
		instance.multimesh = multi
		add_child(instance)


func _build_characters() -> void:
	var x := -6.0
	for character in CHARACTERS:
		var scene: PackedScene = load("res://models/%s.glb" % character)
		var body: Node3D = scene.instantiate()
		body.position = Vector3(x, 0, 0)
		add_child(body)
		var skeleton: Skeleton3D = body.find_children("*", "Skeleton3D", true, false)[0]
		var cape := _make_cape(character)
		var attach := BoneAttachment3D.new()
		attach.bone_name = "spine_03"
		skeleton.add_child(attach)
		attach.add_child(cape)
		cape.position = Vector3(0, .55, -.14)
		bodies.append({"skeleton": skeleton, "phase": x})
		x += 3.0


func _make_cape(character: String) -> MeshInstance3D:
	var shader := Shader.new()
	shader.code = "shader_type spatial;\nrender_mode cull_disabled;\nuniform vec3 tint;\nvoid vertex() {\n float row = UV.y;\n float wave = sin(TIME * 6.0 + UV.x * 15.0 + row * 8.0) * .34;\n VERTEX.x += wave * .05 * row;\n VERTEX.z -= row * abs(wave) * .1;\n}\nvoid fragment() { ALBEDO = tint; ROUGHNESS = .7; }\n"
	var material := ShaderMaterial.new()
	material.shader = shader
	material.set_shader_parameter("tint", {"YELLOW": Color(.08, .15, .36), "RED": Color(.2, .2, .2)}.get(character, Color(.5, .08, .1)))
	var mesh := PlaneMesh.new()
	mesh.size = Vector2(1.3, 2.25)
	mesh.subdivide_width = 19
	mesh.subdivide_depth = 13
	mesh.orientation = PlaneMesh.FACE_Z
	mesh.center_offset = Vector3(0, -1.125, 0)
	mesh.material = material
	var cape := MeshInstance3D.new()
	cape.mesh = mesh
	return cape


func _build_particles() -> void:
	burst = GPUParticles3D.new()
	burst.amount = 400
	burst.lifetime = 1.6
	burst.one_shot = true
	burst.explosiveness = .95
	var process := ParticleProcessMaterial.new()
	process.direction = Vector3.UP
	process.spread = 180.0
	process.initial_velocity_min = 8.0
	process.initial_velocity_max = 22.0
	process.gravity = Vector3(0, -6, 0)
	process.scale_min = .4
	process.scale_max = 1.4
	burst.process_material = process
	var quad := QuadMesh.new()
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	material.billboard_mode = BaseMaterial3D.BILLBOARD_ENABLED
	material.albedo_color = Color(1.0, .7, .3, .4)
	quad.material = material
	burst.draw_pass_1 = quad
	burst.position = Vector3(0, 2, -10)
	add_child(burst)


func _pose(time: float) -> void:
	for body in bodies:
		var skeleton: Skeleton3D = body["skeleton"]
		var swing: float = sin(time * 7.0 + body["phase"]) * .55
		_turn(skeleton, "thigh_l", Vector3.RIGHT, swing)
		_turn(skeleton, "thigh_r", Vector3.RIGHT, -swing)
		_turn(skeleton, "calf_l", Vector3.RIGHT, max(0.0, swing) * .8)
		_turn(skeleton, "calf_r", Vector3.RIGHT, max(0.0, -swing) * .8)
		_turn(skeleton, "upperarm_l", Vector3.RIGHT, -swing * .6)
		_turn(skeleton, "upperarm_r", Vector3.RIGHT, swing * .6)
		_turn(skeleton, "spine_03", Vector3.RIGHT, sin(time * 1.5) * .02)


func _turn(skeleton: Skeleton3D, bone: String, axis: Vector3, angle: float) -> void:
	skeleton.set_bone_pose_rotation(skeleton.find_bone(bone), Quaternion(axis, angle))


func _process(delta: float) -> void:
	var now := Time.get_ticks_usec()
	var ms := (now - last_us) / 1000.0
	last_us = now
	elapsed += delta
	_pose(elapsed)
	burst_timer -= delta
	if burst_timer <= 0.0:
		burst.restart()
		burst_timer = 3.0
	if warm > 0.0:
		warm -= delta
		return
	frame_ms.append(ms)
	seconds -= delta
	if seconds <= 0.0:
		_finish()


func _finish() -> void:
	var sorted := frame_ms.duplicate()
	sorted.sort()
	var total := 0.0
	for value in frame_ms:
		total += value
	var count: int = sorted.size()
	var low_count: int = max(1, count / 100)
	var low := 0.0
	for index in low_count:
		low += sorted[count - 1 - index]
	var result := {
		"engine": Engine.get_version_info().string, "adapter": RenderingServer.get_video_adapter_name(), "api": RenderingServer.get_video_adapter_api_version(),
		"method": RenderingServer.get_current_rendering_method(), "driver": RenderingServer.get_current_rendering_driver_name(),
		"window": [get_window().size.x, get_window().size.y], "frames": count, "seconds": round(total / 10.0) / 100.0,
		"average_fps": 1000.0 * count / total, "frame_ms_mean": total / count, "frame_ms_p95": sorted[int(count * .95)], "frame_ms_p99": sorted[int(count * .99)],
		"worst_frame_ms": sorted[count - 1], "one_percent_low_fps": 1000.0 * low_count / low,
		"frames_over_100ms": _over(sorted, 100.0), "frames_over_50ms": _over(sorted, 50.0), "frames_over_33ms": _over(sorted, 33.33),
		"static_memory_mb": Performance.get_monitor(Performance.MEMORY_STATIC) / 1048576.0,
		"video_memory_mb": Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED) / 1048576.0,
		"draw_calls": Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME),
		"primitives": Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME),
		"ssao": use_ssao, "shadows": use_shadows,
	}
	var file := FileAccess.open(out_path, FileAccess.WRITE)
	file.store_string(JSON.stringify(result, " "))
	file.close()
	print(JSON.stringify(result))
	var image := get_viewport().get_texture().get_image()
	if image != null:
		image.save_png(out_path.get_basename() + ".png")
	get_tree().quit()


func _over(sorted: PackedFloat32Array, limit: float) -> int:
	var count := 0
	for value in sorted:
		if value > limit:
			count += 1
	return count
