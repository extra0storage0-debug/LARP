"""Upright third-person chase camera and shared flight heading controller."""

from __future__ import annotations

from math import atan2, cos, degrees, exp, radians, sin, sqrt, tan

from ursina import Entity, Vec3, camera, held_keys, mouse, scene
from movement.camera_controls import apply_camera_input
from game.controls import CONTROL_BINDINGS, key_axis
from game.world_raycast import world_raycast
from movement.flight_physics import Vec3 as SimVec3

ZOOM_NEAREST, ZOOM_FARTHEST = 4.0, 30.0
ZOOM_STEP = 1.2
MAX_FOLLOW_LAG = 6.0         # at flight speed the view must not drop behind, or fall past, the body
LOCK_TURN_RATE = 7.0         # how quickly the view closes on the target, per second
LOCK_MAX_TURN = 300.0        # degrees per second, so nothing ever whips the view round
LOCK_MIN_PITCH, LOCK_MAX_PITCH = -85.0, 85.0
AIM_PITCH_LIMIT = 89.0       # straight up or down, and never over the top
LOCK_HOLD_RADIUS = 2.0       # directly overhead or underfoot the direction means nothing; hold still
LOCK_CLOSE_METRES = 22.0     # nearer than this, the camera backs off to fit both of them in
LOCK_MAX_PULL_BACK = 7.0
BODY_MIDDLE = 1.3            # metres above the body's origin, measured on the models
BODY_HALF_HEIGHT = 1.55
FRAME_POSITION = .77         # the middle of the body, as a share of the way down the screen
FRAME_LOWEST_FEET = .94      # however it is zoomed, the feet stay at least this far up from the bottom edge
FOLLOW_HEIGHT = 3.55         # the setting's default: raising it above this moves the body lower still
GROUND_CLEARANCE = .35


def screen_half_height() -> float:
    """Half the screen's height at one metre from the camera, for this field of view and window shape."""
    lens = getattr(camera, "lens", None)
    if lens is not None:
        return tan(radians(lens.get_fov()[1] * .5))
    return tan(radians(camera.fov * .5)) * 9.0 / 16.0  # no window: the shape it would have


BLOCKED_FRAMES = 4  # how long something must stay between the camera and the body before the camera comes in


class CameraManager:
    DEFAULT_PITCH = 10.0  # camera elevation above the target, not camera roll
    DEFAULT_DISTANCE = 9.5
    TURN_RATE = 125.0
    AIM_ZOOM = .62
    vision_zoom = 1.0  # set by telescopic and microscopic vision

    def __init__(self, game):
        self.game = game
        self.pivot = Entity(position=game.sentry.position, model=None)
        self.yaw = float(game.sentry.local_yaw)
        self.pivot.rotation_y = self.yaw
        self.pitch = self.DEFAULT_PITCH
        self.distance = self.DEFAULT_DISTANCE
        self.zoom = 0.0
        self.base_fov = 82.0
        self.frame_position = FRAME_POSITION
        self.turn_intent = 0.0
        self.tracking = False
        self._lock_pull_back = 0.0
        self._reset_distance_timer = 0.0
        self._smooth_mouse = (0.0, 0.0)
        self._follow_rate = 12.0
        self._zoom_rate = 4.0
        self._shake_scale = 1.0
        self._blocked_frames = 0
        self._reset_hold = .65
        self._follow_height = FOLLOW_HEIGHT
        self._focus_offset = Vec3(0, FOLLOW_HEIGHT, 0)  # the middle of the screen, relative to the feet

        # Keep the global camera at scene root so camera.ui remains screen-aligned.
        camera.parent = scene
        camera.position = (0, 5.2, -11.3)
        camera.look_at(Vec3(0, 3.55, 0))
        self.aim_target = Vec3(0, 3.55, 0)
        self.apply_tuning(initial=True)
        camera.fov = self.base_fov
        self.apply_settings()

    def apply_tuning(self, *, initial: bool = False) -> None:
        """Read the player profile's camera settings."""
        tuning = getattr(self.game, "tuning", None)
        if tuning is None:
            return
        previous_default = self.DEFAULT_DISTANCE
        self.DEFAULT_DISTANCE = tuning.metres("camera_follow_distance_cm")
        if initial or self.distance == previous_default:
            self.distance = self.DEFAULT_DISTANCE
        self._follow_height = tuning.metres("camera_follow_height_cm")
        self.frame_position = max(.5, min(FRAME_LOWEST_FEET, tuning.fraction("camera_frame_position_pct")))
        self.base_fov = tuning.number("camera_fov")
        self._follow_rate = tuning.number("camera_smoothing")
        self._zoom_rate = tuning.seconds("camera_zoom_speed_cs")
        self._shake_scale = tuning.fraction("camera_shake_pct")
        self._reset_hold = .65 / max(.01, tuning.fraction("camera_reset_speed_pct"))

    def aim_direction(self, position) -> SimVec3:
        """The centre of the screen: exactly the camera's forward, this frame, and what flight follows."""
        return self.game.planet.heading(position, self.yaw, -self.pitch)

    @property
    def flight_yaw(self) -> float:
        """Compatibility alias; flight and camera use exactly the same yaw."""
        return self.yaw

    @flight_yaw.setter
    def flight_yaw(self, value: float) -> None:
        self.yaw = float(value)

    def apply_settings(self) -> None:
        # Ursina creates its lens after GameManager initialization. Seed the
        # backing clip value first, then update the real lens when it exists.
        far_plane = float(self.game.settings.render_distance)
        lens = getattr(camera, "lens", None)
        if lens is not None:
            lens.set_far(far_plane)
        camera._clip_plane_far = far_plane

    def zoom_by(self, metres: float) -> None:
        """Mouse wheel: move the follow distance within limits that keep the character framed."""
        self.zoom = max(ZOOM_NEAREST - self.DEFAULT_DISTANCE,
                        min(ZOOM_FARTHEST - self.DEFAULT_DISTANCE, self.zoom + metres))

    def _body_below_centre(self, depth: float) -> float:
        """How far below the middle of the screen the body's middle goes, in metres at this depth.

        Measured in screen heights rather than metres, so it holds at every zoom, speed and window shape.
        """
        half_height = depth * screen_half_height()
        wanted =(self.frame_position - .5) * 2.0 * half_height
        feet_allow = (FRAME_LOWEST_FEET - .5) * 2.0 * half_height - BODY_HALF_HEIGHT
        return max(0.0, min(wanted, feet_allow))

    def update_control(self, dt: float, steering_axis: float = 0.0,
                       *, flying: bool = False) -> None:
        """Consume mouse and arrow look; flight movement is resolved separately."""
        point = self.game.combat.targets.locked_point()
        if point is not None:
            self._track_lock(point, dt)
            return
        if self.tracking:  # back to the free camera exactly where the lock left it
            self.tracking = False
            self._lock_pull_back = 0.0
            self._smooth_mouse = (0.0, 0.0)
        mouse_dx = mouse_dy = 0.0
        if mouse.locked:
            delta = mouse.velocity
            mouse_dx, mouse_dy = float(delta[0]), float(delta[1])
        tuning = getattr(self.game, "tuning", None)
        arrow_turn, arrow_pitch = 90.0, 65.0
        if tuning is not None:
            mode = tuning.fraction("flight_camera_pct" if flying else "ground_camera_pct")
            overall = tuning.fraction("mouse_sensitivity_pct") * mode
            mouse_dx *= overall * tuning.fraction("camera_horizontal_pct")
            mouse_dy *= overall * tuning.fraction("camera_vertical_pct")
            if tuning.flag("invert_mouse_y"):
                mouse_dy = -mouse_dy
            smoothing = min(.95, tuning.fraction("mouse_smoothing_pct"))
            if smoothing > 0.0:
                previous_x, previous_y = self._smooth_mouse
                mouse_dx = previous_x + (mouse_dx - previous_x) * (1.0 - smoothing)
                mouse_dy = previous_y + (mouse_dy - previous_y) * (1.0 - smoothing)
            self._smooth_mouse = (mouse_dx, mouse_dy)
            rotation = tuning.number("camera_rotation_speed")
            arrow_turn, arrow_pitch = rotation, rotation * 65.0 / 90.0
        camera_x = key_axis(held_keys, CONTROL_BINDINGS["camera_right"],
                            CONTROL_BINDINGS["camera_left"])
        camera_y = key_axis(held_keys, CONTROL_BINDINGS["camera_up"],
                            CONTROL_BINDINGS["camera_down"])
        self.yaw, self.pitch, self.turn_intent = apply_camera_input(
            self.yaw, self.pitch, mouse_dx, mouse_dy, dt, steering_axis,
            flying=flying, turn_rate=self.TURN_RATE,
            camera_x_axis=camera_x, camera_y_axis=camera_y,
            arrow_turn_rate=arrow_turn, arrow_pitch_rate=arrow_pitch)
        if tuning is not None:
            self.pitch = max(tuning.number("camera_pitch_min"),
                             min(tuning.number("camera_pitch_max"), self.pitch))
        self.pitch = max(-AIM_PITCH_LIMIT, min(AIM_PITCH_LIMIT, self.pitch))
        # Mouse, arrows and airborne A/D all resolve through this shared yaw/pitch.
        self.pivot.rotation_y = self.yaw

    def _track_lock(self, point: SimVec3, dt: float) -> None:
        """Target Lock Camera: turn the shared yaw and pitch so the target sits on the view's centre."""
        self.tracking = True
        self.turn_intent = 0.0
        sentry = self.game.sentry
        focus = self._focus_offset  # the crosshair is above the body, so the turn is measured from there
        dx = point.x - float(sentry.x) - focus.x
        dy = point.y - float(sentry.y) - focus.y
        dz = point.z - float(sentry.z) - focus.z
        flat = sqrt(dx * dx + dz * dz)
        blend = 1.0 - exp(-LOCK_TURN_RATE * max(0.0, dt))
        limit = LOCK_MAX_TURN * max(0.0, dt)
        if flat > LOCK_HOLD_RADIUS:
            turn = (degrees(atan2(dx, dz)) - self.yaw + 180.0) % 360.0 - 180.0
            self.yaw += max(-limit, min(limit, turn * blend))
            wanted = max(LOCK_MIN_PITCH, min(LOCK_MAX_PITCH, -degrees(atan2(dy, flat))))
            self.pitch += max(-limit, min(limit, (wanted - self.pitch) * blend))
        apart = sqrt(flat * flat + dy * dy)
        self._lock_pull_back = LOCK_MAX_PULL_BACK * max(0.0, 1.0 - apart / LOCK_CLOSE_METRES)
        self.pivot.rotation_y = self.yaw

    def reset(self) -> None:
        """Restore the default chase view behind the current character's heading."""
        self.yaw = float(self.game.sentry.local_yaw)
        self.pivot.rotation_y = self.yaw
        self.pitch = self.DEFAULT_PITCH
        self.distance = self.DEFAULT_DISTANCE
        self.zoom = 0.0
        self._reset_distance_timer = self._reset_hold
        camera.fov = self.base_fov
        self.game.camera_impulse = 0.0

    def update(self, dt: float) -> None:
        sentry = self.game.sentry
        blend = min(1.0, dt * self._follow_rate)
        self.pivot.position += (sentry.position - self.pivot.position) * blend
        behind = self.pivot.position - sentry.position
        if behind.length() > MAX_FOLLOW_LAG:
            self.pivot.position = sentry.position + behind.normalized() * MAX_FOLLOW_LAG
        sentry_pos = SimVec3(sentry.x, sentry.y, sentry.z)
        east, up, north = self.game.planet.tangent_frame(sentry_pos)
        focus_pos = SimVec3(*self.pivot.world_position)
        focus_pos = self.game.planet.project(focus_pos, self.game.planet.altitude(sentry_pos))

        speed_alpha = min(1.0, sentry.flight.speed_mps / sentry.flight.config.boost_speed)
        altitude = max(0.0, self.game.planet.altitude(sentry_pos))
        if self._reset_distance_timer > 0.0:
            self._reset_distance_timer = max(0.0, self._reset_distance_timer - dt)
            target_distance = self.DEFAULT_DISTANCE
        else:
            target_distance = self.DEFAULT_DISTANCE + self.zoom + speed_alpha * 8.5 + self._lock_pull_back
            if sentry.flight.is_flying:
                target_distance += 1.0
        self.distance += (target_distance - self.distance) * min(1.0, dt * self._zoom_rate)

        heading = self.game.planet.heading(sentry_pos, self.yaw)
        effective_pitch = self.pitch
        pitch_radians = radians(effective_pitch)
        along, rise = cos(pitch_radians), sin(pitch_radians)
        forward = Vec3(heading.x * along - up.x * rise, heading.y * along - up.y * rise,
                       heading.z * along - up.z * rise)
        view_up = Vec3(up.x * along + heading.x * rise, up.y * along + heading.y * rise,
                       up.z * along + heading.z * rise)

        # Frame by sliding the camera along its own up, so the view keeps its direction and the body
        # lands at the same height on the screen at every pitch, and however far the follow lags.
        body = Vec3(sentry_pos.x + up.x * BODY_MIDDLE, sentry_pos.y + up.y * BODY_MIDDLE,
                    sentry_pos.z + up.z * BODY_MIDDLE)
        follow = Vec3(focus_pos.x + up.x * BODY_MIDDLE, focus_pos.y + up.y * BODY_MIDDLE,
                      focus_pos.z + up.z * BODY_MIDDLE)
        lag = body - follow
        depth = max(.1, self.distance + lag.dot(forward))
        lift = lag.dot(view_up) + self._body_below_centre(depth) + self._follow_height - FOLLOW_HEIGHT
        target = follow + view_up * lift
        self.aim_target = target
        offset = target - forward * self.distance - body

        # Sweep from the body to the desired camera position. Coming in along that line, the body stays
        # at the same height on the screen, and the camera cannot cross walls or sink into the ground.
        full_reach = reach = offset.length()
        camera_direction = offset.normalized()
        hit = world_raycast(body, camera_direction, distance=reach,
                            ignore=[sentry, self.pivot,
                                    *getattr(self.game, "camera_transparent", ())])
        # A wall stays; debris thrown past the lens is gone again in a moment, and must not jerk the view in and out.
        self._blocked_frames = self._blocked_frames + 1 if hit.hit else 0
        if hit.hit and (self._blocked_frames >= BLOCKED_FRAMES or hit.distance > reach * .8):
            reach = min(reach, max(3.0, hit.distance - .55))
        camera_position = SimVec3(body.x + camera_direction.x * reach, body.y + camera_direction.y * reach,
                                  body.z + camera_direction.z * reach)
        camera_altitude = self.game.planet.altitude(camera_position)
        if camera_altitude < GROUND_CLEARANCE:
            room = self.game.planet.altitude(SimVec3(body.x, body.y, body.z)) - GROUND_CLEARANCE
            sinking = room + GROUND_CLEARANCE - camera_altitude
            if room > 0.0 and sinking > 0.0:
                reach *= room / sinking
                camera_position = SimVec3(body.x + camera_direction.x * reach, body.y + camera_direction.y * reach,
                                          body.z + camera_direction.z * reach)
            if self.game.planet.altitude(camera_position) < GROUND_CLEARANCE:  # on the rise of a slope
                camera_position = self.game.planet.project(camera_position, GROUND_CLEARANCE)
        camera.position = Vec3(camera_position.x, camera_position.y, camera_position.z)
        # What a target lock turns about: pulled in with the camera, on the line the crosshair really is on.
        self._focus_offset = (camera.position + forward * (self.distance * reach / max(full_reach, 1e-6))
                              - sentry.position)
        camera.setQuat(self.game.planet.surface_quaternion(sentry_pos, self.yaw, effective_pitch))

        impact = self.game.camera_impulse
        if impact > .01:
            shake = impact * self._shake_scale
            shake_side = shake * .035
            shake_up = sin(self.game.elapsed * 31.0) * shake * .017
            shake_forward = sin(self.game.elapsed * 39.0) * shake * .024
            camera.position += Vec3(east.x * shake_side + up.x * shake_up + north.x * shake_forward,
                                    east.y * shake_side + up.y * shake_up + north.y * shake_forward,
                                    east.z * shake_side + up.z * shake_up + north.z * shake_forward)
            self.game.camera_impulse = max(0.0, impact - dt * 4.5)

        target_fov = self.base_fov + speed_alpha * 16.0
        zoom = self.vision_zoom
        if sentry.powers is not None and sentry.powers.aiming:
            zoom = min(zoom, self.AIM_ZOOM)
        target_fov *= zoom
        camera.fov += (target_fov - camera.fov) * min(1.0, dt * 3.0)
        far_plane = max(float(self.game.settings.render_distance),
                        min(altitude * 2.5 + self.game.settings.render_distance,
                            altitude + self.game.planet.radius * 3.5))
        # Preserve the existing altitude-aware near plane while applying the
        # island-sized far plane through Ursina's supported camera properties.
        near_plane = max(0.1, min(4.0, altitude * 0.00001))
        lens = getattr(camera, "lens", None)
        if lens is not None:
            lens.set_near(near_plane)
            lens.set_far(far_plane)
        camera._clip_plane_near = near_plane
        camera._clip_plane_far = far_plane
