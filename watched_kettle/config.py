# config.py

FRAME_WIDTH = 192
FRAME_HEIGHT = 208
ATLAS_COLUMNS = 8

# V2 pointer-look frames are sampled often enough to feel responsive without
# tying their refresh rate to the idle animation timer.
LOOK_DIRECTION_INTERVAL = 50
LOOK_DIRECTION_DEADZONE = 48
# The original fixed enter/exit distances were 320/380. A smaller 240 default
# keeps the pet from reacting across too much of the desktop, while the exit
# margin preserves hysteresis near the selected boundary.
LOOK_RANGE_MIN = 120
LOOK_RANGE_MAX = 480
LOOK_RANGE_STEP = 20
DEFAULT_LOOK_RANGE = 240
LOOK_RANGE_EXIT_MARGIN = 60


# Codex 데스크톱 앱의 펫 크기 범위는 너비 80~224px이고 기본값은
# 112px입니다. 더 크게 보고 싶은 경우를 위해 256~352px 확장 단계를
# 제공하며, 원본 atlas 셀은 192x208로 유지합니다.
CODEX_MAX_PET_WIDTH = 224
EXTENDED_MAX_PET_WIDTH = 352
PET_WIDTH_OPTIONS = (
    80,
    112,
    144,
    176,
    192,
    CODEX_MAX_PET_WIDTH,
    256,
    288,
    320,
    EXTENDED_MAX_PET_WIDTH,
)
DEFAULT_PET_WIDTH = 112
DEFAULT_PET_ID = "mori-bot"


# 오랫동안 사용자 입력이 없을 때 재생할 짧은 자율 행동입니다. waiting,
# running, failed는 앱 상태 의미가 강하므로 기본 후보에서 제외합니다.
IDLE_ACTIVITY_MIN_DELAY = 20_000
IDLE_ACTIVITY_MAX_DELAY = 45_000
DEFAULT_IDLE_ACTIVITIES = (
    {
        "state": "waving",
        "weight": 3,
        "duration": 1_600,
    },
    {
        "state": "jumping",
        "weight": 2,
        "duration": 1_500,
    },
    {
        "state": "review",
        "weight": 1,
        "duration": 2_000,
    },
)


# 자동 이동은 자동 행동과 독립적으로 예약합니다. 좌표 이동은 애니메이션
# 프레임 타이머와 분리하고, 한 번에 현재 디스플레이 안의 짧은 거리만 걷습니다.
AUTO_MOVEMENT_MIN_DELAY = 30_000
AUTO_MOVEMENT_MAX_DELAY = 70_000
AUTO_MOVEMENT_MIN_DISTANCE = 60
AUTO_MOVEMENT_MAX_DISTANCE = 180
AUTO_MOVEMENT_SPEED = 72
AUTO_MOVEMENT_INTERVAL = 33


ANIMATIONS = {
    "idle": {
        "row": 0,
        "frames": 6,
        "interval": 180,
    },
    "running-right": {
        "row": 1,
        "frames": 8,
        "interval": 90,
    },
    "running-left": {
        "row": 2,
        "frames": 8,
        "interval": 90,
    },
    "waving": {
        "row": 3,
        "frames": 4,
        "interval": 160,
    },
    "jumping": {
        "row": 4,
        "frames": 5,
        "interval": 120,
    },
    "failed": {
        "row": 5,
        "frames": 8,
        "interval": 150,
    },
    "waiting": {
        "row": 6,
        "frames": 6,
        "interval": 180,
    },
    "running": {
        "row": 7,
        "frames": 6,
        "interval": 120,
    },
    "review": {
        "row": 8,
        "frames": 6,
        "interval": 160,
    },
}


# 현재는 문제 확인을 위한 테스트 모드.
#
# "running-right":
#     드래그 방향과 관계없이 무조건 오른쪽 달리기 애니메이션만 재생
#
# None:
#     실제 마우스 이동 방향에 따라 running-right / running-left 선택

FORCE_DRAG_ANIMATION = None

# 좌우 방향을 전환하기 위해 필요한 누적 마우스 이동량(px)
DRAG_DIRECTION_THRESHOLD = 10
