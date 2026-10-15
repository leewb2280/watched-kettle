import math


LOOK_DIRECTION_COUNT = 16
DEGREES_PER_DIRECTION = 360 / LOOK_DIRECTION_COUNT


def is_pointer_near(
    dx: float,
    dy: float,
    enter_distance: float,
    exit_distance: float,
    was_near: bool = False,
):
    """Return pointer proximity with hysteresis around the pet.

    A pointer must cross ``enter_distance`` to start tracking, but it can move
    out to ``exit_distance`` before tracking stops. This prevents rapid
    idle/look switching near the boundary.
    """
    if enter_distance < 0 or exit_distance < 0:
        raise ValueError("추적 거리는 0 이상이어야 합니다.")

    if enter_distance > exit_distance:
        raise ValueError("진입 거리는 이탈 거리보다 클 수 없습니다.")

    limit = exit_distance if was_near else enter_distance
    return math.hypot(dx, dy) <= limit


def mirrored_right_frame_source(direction_index: int):
    """Map a target direction to the approved left-side pose family.

    Returns ``(source_index, flip_horizontal)``. Up and down keep their
    original cardinal cells, the left half reuses row-9 poses in reverse
    order, and the right half mirrors those same approved poses.
    """
    direction_index %= LOOK_DIRECTION_COUNT

    if 1 <= direction_index <= 7:
        return direction_index, True

    if 9 <= direction_index <= 15:
        return LOOK_DIRECTION_COUNT - direction_index, False

    return direction_index, False


def direction_index_from_vector(
    dx: float,
    dy: float,
    deadzone: float = 0,
    direction_offset: int = 0,
    mirror_horizontal: bool = False,
    max_distance: float | None = None,
):
    """Return a clockwise V2 look index where 0 means screen-up.

    Qt screen coordinates grow downward, so ``dy`` is inverted when the
    angle is measured. ``None`` means the pointer is inside the neutral
    deadzone or outside the optional maximum distance, so idle should be
    shown.
    """
    if deadzone < 0:
        raise ValueError("deadzone은 0 이상이어야 합니다.")

    if max_distance is not None:
        if max_distance < 0:
            raise ValueError("최대 추적 거리는 0 이상이어야 합니다.")

        if max_distance < deadzone:
            raise ValueError("최대 추적 거리는 deadzone보다 작을 수 없습니다.")

    distance = math.hypot(dx, dy)

    if distance <= deadzone or (max_distance is not None and distance > max_distance):
        return None

    angle = (math.degrees(math.atan2(dx, -dy)) + 360) % 360

    direction_index = (
        math.floor(angle / DEGREES_PER_DIRECTION + 0.5) % LOOK_DIRECTION_COUNT
    )

    if mirror_horizontal:
        direction_index = (-direction_index) % LOOK_DIRECTION_COUNT

    return (direction_index + direction_offset) % LOOK_DIRECTION_COUNT
