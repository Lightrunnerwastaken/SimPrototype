SCREEN_WIDTH = 960
SCREEN_HEIGHT = 540
TILE_SIZE = 32
FPS = 60
PLAYER_SPEED = 180  # pixels per second
CAMERA_LERP = 8.0
DEMOLISH_TIME = 0.75
WATER_SPEED_MULT = 0.6
PLAYER_HUNGER_DECAY = 0.003
PLAYER_EAT_AMOUNT = 0.35
PLAYER_STARVE_THRESHOLD = 0.02
PLAYER_STARVE_DAMAGE = 1.0
PLAYER_STARVE_COOLDOWN = 1.2
SMELT_TIME_IRON = 1.6
HOME_RADIUS = 12
REGION_SIZE = 50
CIV_SPAWN_INTERVAL = 8.0
CIV_TICK_INTERVAL = 6.0
CIV_MIN_SPAWN_DIST = 80
CIV_MAX_SPAWN_DIST = 200
CIV_MATERIALIZE_DIST = 50
CIV_MAX_REGIONS = 18
GATHER_TIME = {
    "tree": 0.9,
    "rock": 1.3,
    "crate": 0.6,
    "iron_ore": 1.6,
}

BUILD_ITEMS = {
    "wall": {"wood": 2},
    "floor": {"wood": 1},
    "workbench": {"wood": 6},
    "door": {"wood": 2},
    "crate": {"wood": 2},
    "stone_wall": {"stone": 2},
    "stone_floor": {"stone": 1},
    "road": {"wood": 1},
    "furnace": {"stone": 10, "iron_ore": 3},
}

DEMOLISH_REFUND = {
    "wall": {"wood": 1},
    "floor": {"wood": 1},
    "workbench": {"wood": 3},
    "door_closed": {"wood": 1},
    "crate": {"wood": 1},
    "stone_wall": {"stone": 1},
    "stone_floor": {"stone": 1},
    "furnace": {"stone": 5, "iron_ore": 1},
}

CRAFT_RECIPES = {
    "pickaxe": {"wood": 4},
}

WEAPON_STATS = {
    "club": {
        "damage": 3,
        "cost": {"wood": 2},
        "range": TILE_SIZE * 1.05,
        "min_dot": 0.2,
        "cooldown": 0.55,
        "swing": 0.22,
    },
    "spear": {
        "damage": 4,
        "cost": {"wood": 1, "stone": 1},
        "range": TILE_SIZE * 1.7,
        "min_dot": 0.78,
        "cooldown": 0.45,
        "swing": 0.2,
    },
}

COLORS = {
    "bg": (20, 20, 24),
    "ground": (60, 80, 60),
    "floor": (110, 140, 110),
    "tree": (30, 110, 40),
    "rock": (110, 110, 120),
    "wall": (120, 80, 50),
    "player": (230, 210, 80),
    "cursor": (240, 240, 240),
    "ui_text": (230, 230, 230),
    "ui_accent": (250, 200, 80),
}
