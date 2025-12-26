import random
from collections import deque

import pygame

from src.constants import TILE_SIZE, BUILD_ITEMS, GATHER_TIME, CRAFT_RECIPES, HOME_RADIUS, WEAPON_STATS
from src.entity import NPC, Animal, Carcass
from src.vegetation import PlantManager
from src.world import World
from src.systems.movement_system import move_agent
from src.systems.movement_helpers import random_dir, resolve_move_dir
from src.systems.combat_system import find_nearest_carcass


class NPCGroup:
    def __init__(self, group_id: int, camp_grid: tuple[int, int]) -> None:
        self.group_id = group_id
        self.camp_grid = camp_grid
        self.build_origin: tuple[int, int] | None = None
        self.expanded = False
        self.is_raider = False
        self.stockpile = {"wood": 0, "food": 0, "stone": 0}
        self.tools = {"pickaxe": 0}
        self.weapons = {"club": 0, "spear": 0}
        self.storage_tiles: set[tuple[int, int]] = set()
        self.storage_capacity = {"wood": 0, "food": 0, "stone": 0}
        self.base_capacity = {"wood": 10, "food": 10, "stone": 10}
        self.build_queue: list[tuple[tuple[int, int], str]] = []
        self.claimed: dict[tuple[int, int], int] = {}
        self.goals: list[str] = []
        self.current_goal = "setup"
        self.needs: dict[str, float] = {}
        self.home_grid = camp_grid
        self.home_radius = HOME_RADIUS
        self.avoid_tiles: dict[tuple[int, int], float] = {}

    def claim(self, task_pos: tuple[int, int], npc_id: int) -> bool:
        if task_pos in self.claimed and self.claimed[task_pos] != npc_id:
            return False
        self.claimed[task_pos] = npc_id
        return True

    def release(self, task_pos: tuple[int, int]) -> None:
        if task_pos in self.claimed:
            del self.claimed[task_pos]


def find_nearest_tile(world: World, start_grid: tuple[int, int], targets: set[str], radius: int = 12) -> tuple[int, int] | None:
    best = None
    best_dist = None
    for y in range(start_grid[1] - radius, start_grid[1] + radius + 1):
        for x in range(start_grid[0] - radius, start_grid[0] + radius + 1):
            tile = world.get_tile((x, y))
            if tile not in targets:
                continue
            dist = abs(x - start_grid[0]) + abs(y - start_grid[1])
            if best is None or dist < best_dist:
                best = (x, y)
                best_dist = dist
    return best

def find_reachable_target(
    world: World,
    start_grid: tuple[int, int],
    targets: set[str],
    radius: int = 12,
    home_grid: tuple[int, int] | None = None,
    home_radius: int | None = None,
) -> tuple[int, int] | None:
    best = None
    best_dist = None
    for y in range(start_grid[1] - radius, start_grid[1] + radius + 1):
        for x in range(start_grid[0] - radius, start_grid[0] + radius + 1):
            tile = world.get_tile((x, y))
            if tile not in targets:
                continue
            if home_grid is not None and home_radius is not None:
                if abs(x - home_grid[0]) + abs(y - home_grid[1]) > home_radius:
                    continue
            adjacent = find_adjacent_walkable(world, (x, y), start_grid, allow_doors=True)
            if adjacent is None:
                continue
            path = find_path(world, start_grid, adjacent, max_radius=16, allow_doors=True)
            if path is None:
                continue
            dist = abs(x - start_grid[0]) + abs(y - start_grid[1])
            if best is None or dist < best_dist:
                best = (x, y)
                best_dist = dist
    return best

def find_adjacent_walkable(
    world: World,
    target: tuple[int, int],
    origin: tuple[int, int],
    allow_doors: bool = False,
) -> tuple[int, int] | None:
    tx, ty = target
    candidates = [(tx + 1, ty), (tx - 1, ty), (tx, ty + 1), (tx, ty - 1)]
    candidates.sort(key=lambda p: abs(p[0] - origin[0]) + abs(p[1] - origin[1]))
    for pos in candidates:
        tile = world.get_tile(pos)
        if tile != "water" and not world.is_blocking(tile):
            return pos
        if allow_doors and tile == "door_closed":
            return pos
    return None

def find_path(
    world: World,
    start: tuple[int, int],
    goal: tuple[int, int],
    max_radius: int = 14,
    allow_doors: bool = False,
) -> list[tuple[int, int]] | None:
    if start == goal:
        return []
    min_x = start[0] - max_radius
    max_x = start[0] + max_radius
    min_y = start[1] - max_radius
    max_y = start[1] + max_radius
    queue = deque([start])
    came_from: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    while queue:
        current = queue.popleft()
        if current == goal:
            break
        cx, cy = current
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if nx < min_x or nx > max_x or ny < min_y or ny > max_y:
                continue
            nxt = (nx, ny)
            if nxt in came_from:
                continue
            tile = world.get_tile(nxt)
            if world.is_blocking(tile) and not (allow_doors and tile == "door_closed"):
                continue
            came_from[nxt] = current
            queue.append(nxt)
    if goal not in came_from:
        return None
    path: list[tuple[int, int]] = []
    cur = goal
    while cur != start:
        path.append(cur)
        cur = came_from[cur]
    path.reverse()
    return path

def find_free_tile_near(world: World, origin: tuple[int, int], radius: int = 3) -> tuple[int, int] | None:
    ox, oy = origin
    for r in range(1, radius + 1):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if abs(dx) != r and abs(dy) != r:
                    continue
                pos = (ox + dx, oy + dy)
                tile = world.get_tile(pos)
                if tile != "water" and not world.is_blocking(tile):
                    return pos
    return None

def is_clear_build_spot(
    world: World,
    grid_pos: tuple[int, int],
    clearance: int = 1,
    allow_blockers: set[str] | None = None,
) -> bool:
    gx, gy = grid_pos
    allow_blockers = allow_blockers or set()
    for y in range(gy - clearance, gy + clearance + 1):
        for x in range(gx - clearance, gx + clearance + 1):
            tile = world.get_tile((x, y))
            if tile == "water":
                return False
            if world.is_blocking(tile) and tile not in allow_blockers:
                return False
    return True

def find_home_door(group: NPCGroup, world: World) -> tuple[int, int] | None:
    hx, hy = group.home_grid
    for offset in range(-3, 4):
        pos = (hx + offset, hy + group.home_radius)
        if world.get_tile(pos) in {"door_closed", "door_open"}:
            return pos
    for offset in range(-3, 4):
        pos = (hx + offset, hy - group.home_radius)
        if world.get_tile(pos) in {"door_closed", "door_open"}:
            return pos
    for offset in range(-3, 4):
        pos = (hx - group.home_radius, hy + offset)
        if world.get_tile(pos) in {"door_closed", "door_open"}:
            return pos
        pos = (hx + group.home_radius, hy + offset)
        if world.get_tile(pos) in {"door_closed", "door_open"}:
            return pos
    return None

def find_work_zone_exit(
    group: NPCGroup,
    world: World,
    start_grid: tuple[int, int],
    radius: int = 8,
) -> tuple[int, int] | None:
    hx, hy = group.home_grid
    r = group.home_radius
    for dist in range(1, radius + 1):
        for dx in range(-dist, dist + 1):
            for dy in (-dist, dist):
                gx = start_grid[0] + dx
                gy = start_grid[1] + dy
                if abs(gx - hx) + abs(gy - hy) <= r:
                    continue
                tile = world.get_tile((gx, gy))
                if tile == "water" or world.is_blocking(tile):
                    continue
                if find_path(world, start_grid, (gx, gy), max_radius=16, allow_doors=True):
                    return (gx, gy)
        for dy in range(-dist + 1, dist):
            for dx in (-dist, dist):
                gx = start_grid[0] + dx
                gy = start_grid[1] + dy
                if abs(gx - hx) + abs(gy - hy) <= r:
                    continue
                tile = world.get_tile((gx, gy))
                if tile == "water" or world.is_blocking(tile):
                    continue
                if find_path(world, start_grid, (gx, gy), max_radius=16, allow_doors=True):
                    return (gx, gy)
    return None

def pick_stockpile_target(group: NPCGroup, world: World, from_grid: tuple[int, int]) -> tuple[int, int]:
    if not group.storage_tiles:
        return group.camp_grid
    best = None
    best_dist = None
    for pos in group.storage_tiles:
        if world.get_tile(pos) != "crate":
            continue
        dist = abs(pos[0] - from_grid[0]) + abs(pos[1] - from_grid[1])
        if best is None or dist < best_dist:
            best = pos
            best_dist = dist
    return best if best is not None else group.camp_grid

def pick_stockpile_destination(
    group: NPCGroup,
    world: World,
    from_grid: tuple[int, int],
) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    best = None
    best_approach = None
    best_dist = None
    for pos in group.storage_tiles:
        if world.get_tile(pos) != "crate":
            continue
        approach = find_adjacent_walkable(world, pos, from_grid, allow_doors=True)
        if approach is None:
            continue
        dist = abs(approach[0] - from_grid[0]) + abs(approach[1] - from_grid[1])
        if best is None or dist < best_dist:
            best = pos
            best_approach = approach
            best_dist = dist
    if best is not None:
        return best, best_approach
    fallback = group.camp_grid
    approach = find_adjacent_walkable(world, fallback, from_grid, allow_doors=True)
    if approach is None:
        return None, None
    return fallback, approach

def stockpile_capacity(group: NPCGroup) -> dict[str, int]:
    return {
        "wood": group.base_capacity["wood"] + group.storage_capacity["wood"],
        "stone": group.base_capacity["stone"] + group.storage_capacity["stone"],
        "food": group.base_capacity["food"] + group.storage_capacity["food"],
    }

def add_to_stockpile(group: NPCGroup, item: str, amount: int) -> int:
    capacity = stockpile_capacity(group)[item]
    current = group.stockpile.get(item, 0)
    space = max(0, capacity - current)
    to_add = min(space, amount)
    group.stockpile[item] = current + to_add
    return to_add

def find_tile_in_radius(world: World, center: tuple[int, int], target: str, radius: int) -> tuple[int, int] | None:
    cx, cy = center
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            if world.get_tile((x, y)) == target:
                return (x, y)
    return None

def base_complete(world: World, origin: tuple[int, int]) -> bool:
    cx, cy = origin
    min_x, max_x = cx - 3, cx + 3
    min_y, max_y = cy - 2, cy + 2
    door_ok = world.get_tile((cx, max_y)) in {"door_closed", "door_open"}
    workbench_ok = world.get_tile((cx, cy - 1)) == "workbench"
    crate_ok = world.get_tile((cx, cy)) == "crate"
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            tile = world.get_tile((x, y))
            if x == cx and y == max_y:
                if not door_ok:
                    return False
                continue
            if x == cx and y == cy - 1:
                if not workbench_ok:
                    return False
                continue
            if x == cx and y == cy:
                if not crate_ok:
                    return False
                continue
            if x == min_x or x == max_x or y == min_y or y == max_y:
                if tile not in {"wall", "stone_wall"}:
                    return False
            else:
                if tile not in {"floor", "stone_floor"}:
                    return False
    return True

def compute_home_radius(group: NPCGroup, base_done: bool) -> int:
    radius = HOME_RADIUS + min(6, len(group.storage_tiles))
    if base_done:
        radius += 3
    if group.expanded:
        radius += 3
    return radius

def update_group_goals(group: NPCGroup, world: World, member_count: int) -> None:
    home_grid = group.build_origin or group.camp_grid
    base_done = group.build_origin is not None and base_complete(world, group.build_origin)
    has_workbench = find_tile_in_radius(world, home_grid, "workbench", radius=2) is not None
    cap = stockpile_capacity(group)

    def need_ratio(item: str) -> float:
        limit = max(1, cap[item])
        return 1.0 - min(1.0, group.stockpile.get(item, 0) / limit)

    needs = {
        "food": need_ratio("food"),
        "wood": need_ratio("wood"),
        "stone": need_ratio("stone"),
        "build": 0.7 if not base_done else 0.2,
        "craft": 0.0,
    }
    if group.build_queue:
        needs["build"] = min(1.0, needs["build"] + min(0.6, len(group.build_queue) / 12))
    if has_workbench and group.tools.get("pickaxe", 0) < 1:
        needs["craft"] = max(needs["craft"], 0.6)
    if has_workbench and (group.weapons["club"] + group.weapons["spear"]) < max(1, member_count // 2):
        needs["craft"] = max(needs["craft"], 0.4)

    ordered = sorted(needs.items(), key=lambda item: item[1], reverse=True)
    group.needs = needs
    group.goals = [key for key, _score in ordered]
    group.current_goal = group.goals[0] if group.goals else "idle"

def ensure_build_queue(group: NPCGroup, world: World) -> None:
    if group.build_queue:
        return
    if group.build_origin is None:
        group.build_origin = group.camp_grid
    cx, cy = group.build_origin
    allow = {"wall", "floor", "door_closed", "door_open", "workbench", "crate", "stone_wall", "stone_floor"}
    base_done = base_complete(world, group.build_origin)
    min_x, max_x = cx - 3, cx + 3
    min_y, max_y = cy - 2, cy + 2
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            if not is_clear_build_spot(world, (x, y), clearance=1, allow_blockers=allow):
                continue
            tile = world.get_tile((x, y))
            if tile == "crate":
                group.storage_tiles.add((x, y))
            if (x, y) == (cx, cy):
                if tile not in {"floor", "stone_floor"}:
                    group.build_queue.append(((x, y), "floor"))
                if tile != "crate":
                    group.build_queue.append(((x, y), "crate"))
            elif (x, y) == (cx, cy - 1):
                if tile not in {"floor", "stone_floor"}:
                    group.build_queue.append(((x, y), "floor"))
                if tile != "workbench":
                    group.build_queue.append(((x, y), "workbench"))
            elif (x, y) == (cx, max_y):
                if tile not in {"door_closed", "door_open"}:
                    group.build_queue.append(((x, y), "door"))
            elif x == min_x or x == max_x or y == min_y or y == max_y:
                if tile not in {"wall", "stone_wall"}:
                    group.build_queue.append(((x, y), "wall"))
            else:
                if tile not in {"floor", "stone_floor"}:
                    group.build_queue.append(((x, y), "floor"))
    if base_done and group.tools.get("pickaxe", 0) > 0:
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                tile = world.get_tile((x, y))
                if x == cx and y == max_y:
                    continue
                if x == cx and y == cy - 1:
                    continue
                if x == cx and y == cy:
                    if tile == "floor":
                        group.build_queue.append(((x, y), "stone_floor"))
                    continue
                if x == min_x or x == max_x or y == min_y or y == max_y:
                    if tile == "wall":
                        group.build_queue.append(((x, y), "stone_wall"))
                else:
                    if tile == "floor":
                        group.build_queue.append(((x, y), "stone_floor"))
    if base_done and group.tools.get("pickaxe", 0) > 0 and not group.expanded:
        outer_min_x, outer_max_x = min_x - 1, max_x + 1
        outer_min_y, outer_max_y = min_y - 1, max_y + 1
        for y in range(outer_min_y, outer_max_y + 1):
            for x in range(outer_min_x, outer_max_x + 1):
                if min_x <= x <= max_x and min_y <= y <= max_y:
                    continue
                if x == cx and y == outer_max_y:
                    if world.get_tile((x, y)) not in {"door_closed", "door_open"}:
                        group.build_queue.append(((x, y), "door"))
                    continue
                tile = world.get_tile((x, y))
                if tile in {"tree", "rock", "mountain", "water"}:
                    continue
                if x == outer_min_x or x == outer_max_x or y == outer_min_y or y == outer_max_y:
                    if tile != "stone_wall":
                        group.build_queue.append(((x, y), "stone_wall"))
                else:
                    if tile not in {"stone_floor", "floor"}:
                        group.build_queue.append(((x, y), "stone_floor"))
        group.expanded = True

def update_npcs(
    npcs: list[NPC],
    groups: dict[int, NPCGroup],
    world: World,
    plants: PlantManager,
    animals: list[Animal],
    carcasses: list[Carcass],
    dt: float,
    manual_control: bool = False,
    raids: list[dict[str, object]] | None = None,
    debug: dict[int, dict[str, str]] | None = None,
) -> None:
    def fmt_grid(pos: tuple[int, int] | None) -> str:
        return "-" if pos is None else f"{pos[0]},{pos[1]}"

    def open_adjacent_door(npc: NPC) -> bool:
        gx, gy = world.to_grid(npc.position)
        for nx, ny in ((gx + 1, gy), (gx - 1, gy), (gx, gy + 1), (gx, gy - 1)):
            if world.get_tile((nx, ny)) == "door_closed":
                world.set_tile((nx, ny), "door_open")
                return True
        return False

    def goal_label(job: str) -> str:
        return {
            "build": "build_base",
            "chop": "chop_tree",
            "mine": "mine_rock",
            "gather_food": "gather_food",
            "hunt": "hunt",
            "eat": "eat",
            "eat_stock": "eat_stock",
            "haul_meat": "haul_meat",
            "haul": "haul_stock",
            "craft_tool": "craft_tool",
            "craft_weapon": "craft_weapon",
            "raid": "raid",
            "return_home": "return_home",
            "move": "move",
            "wander": "wander",
            "idle": "idle",
        }.get(job, job)

    task_jobs = {
        "build",
        "chop",
        "mine",
        "gather_food",
        "hunt",
        "eat",
        "eat_stock",
        "haul_meat",
        "haul",
        "craft_tool",
        "craft_weapon",
        "raid",
    }

    def apply_melee_attack(attacker: NPC, target: NPC) -> None:
        if attacker.attack_cooldown > 0:
            return
        if attacker.position.distance_to(target.position) > TILE_SIZE * 0.7:
            return
        damage = 1
        if attacker.weapon:
            damage = WEAPON_STATS.get(attacker.weapon, {"damage": 1})["damage"]
        target.hp = max(0.0, target.hp - damage)
        attacker.attack_cooldown = 0.8

    def find_hunt_target(npc: NPC, radius: float = TILE_SIZE * 12) -> Animal | None:
        closest = None
        closest_dist = None
        for animal in animals:
            if animal.species == "wolf":
                continue
            dist = npc.position.distance_to(animal.position)
            if dist > radius:
                continue
            if closest is None or dist < closest_dist:
                closest = animal
                closest_dist = dist
        return closest

    def steer_npc(npc: NPC, move_dir: pygame.Vector2, speed: float) -> None:
        if move_dir.length_squared() == 0:
            npc.velocity *= 0.5
            return
        move_dir = move_dir.normalize()
        npc.velocity += (move_dir * speed - npc.velocity) * min(1.0, dt * 6.0)
        if npc.velocity.length_squared() > 0.01:
            move_agent(npc, npc.velocity.normalize(), dt, world, npc.velocity.length(), can_swim=False)

    def drive_to_target(npc: NPC, target: tuple[int, int], speed: float) -> None:
        ensure_path_to_target(npc, target)
        if npc.path_index < len(npc.path):
            next_grid = npc.path[npc.path_index]
            if world.get_tile(next_grid) == "door_closed":
                npc.door_waits += 1
                npc_grid = world.to_grid(npc.position)
                if abs(npc_grid[0] - next_grid[0]) + abs(npc_grid[1] - next_grid[1]) <= 1:
                    world.set_tile(next_grid, "door_open")
        move_dir = resolve_move_dir(npc, get_move_dir_to_target(npc, target), world)
        if move_dir.length_squared() == 0 and open_adjacent_door(npc):
            move_dir = resolve_move_dir(npc, get_move_dir_to_target(npc, target), world)
        steer_npc(npc, move_dir, speed)

    def apply_manual_command(npc: NPC, command: tuple[str, tuple[int, int] | None, tuple[int, int] | None, object | None, str]) -> None:
        job, target_grid, action_grid, hunt_target, label = command
        npc.job = job
        npc.job_lock_timer = 0.0
        npc.task_timer = 0.0
        npc.task_key = None
        npc.task_commit_timer = 0.0
        npc.task_cooldowns.pop(job, None)
        npc.target_grid = target_grid
        npc.action_grid = action_grid
        npc.hunt_target = hunt_target if job == "hunt" else None
        npc.eat_target = None
        npc.path = []
        npc.path_index = 0
        npc.path_retries = 0
        npc.path_target = None
        npc.path_cooldown = 0.0
        npc.current_command_label = label

    path_cache: dict[tuple[int, int, int, int], tuple[list[tuple[int, int]], float]] = {}

    def find_path_avoiding(
        start: tuple[int, int],
        goal: tuple[int, int],
        avoid: set[tuple[int, int]],
        max_radius: int,
    ) -> list[tuple[int, int]] | None:
        if start == goal:
            return []
        min_x = start[0] - max_radius
        max_x = start[0] + max_radius
        min_y = start[1] - max_radius
        max_y = start[1] + max_radius
        queue = deque([start])
        came_from: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        while queue:
            current = queue.popleft()
            if current == goal:
                break
            cx, cy = current
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if nx < min_x or nx > max_x or ny < min_y or ny > max_y:
                    continue
                nxt = (nx, ny)
                if nxt in came_from or nxt in avoid:
                    continue
                tile = world.get_tile(nxt)
                if world.is_blocking(tile) and tile != "door_closed":
                    continue
                came_from[nxt] = current
                queue.append(nxt)
        if goal not in came_from:
            return None
        path: list[tuple[int, int]] = []
        cur = goal
        while cur != start:
            path.append(cur)
            cur = came_from[cur]
        path.reverse()
        return path

    def cached_path(start: tuple[int, int], target: tuple[int, int], avoid: set[tuple[int, int]]) -> list[tuple[int, int]] | None:
        if avoid:
            return find_path_avoiding(start, target, avoid, max_radius=14)
        key = (start[0], start[1], target[0], target[1])
        cached = path_cache.get(key)
        if cached is not None:
            path, ttl = cached
            if ttl > 0:
                path_cache[key] = (path, ttl - dt)
                return path
            path_cache.pop(key, None)
        path = find_path(world, start, target, max_radius=14, allow_doors=True)
        if path:
            path_cache[key] = (path, 1.4)
        return path

    def ensure_path_to_target(npc: NPC, target: tuple[int, int]) -> None:
        if npc.path_target != target:
            npc.path = []
            npc.path_index = 0
            npc.path_target = target
        if npc.path_cooldown > 0:
            return
        start = world.to_grid(npc.position)
        if start == target:
            npc.path = []
            npc.path_index = 0
            return
        avoid = {pos for pos, weight in group.avoid_tiles.items() if weight > 0.6}
        path = cached_path(start, target, avoid)
        if path:
            npc.path = path
            npc.path_index = 0
            npc.path_retries = 0
            npc.path_cooldown = 0.5
        else:
            npc.path_retries += 1
            npc.path_failures += 1
            npc.path_cooldown = min(1.2, 0.3 * npc.path_retries)

    def get_move_dir_to_target(npc: NPC, target: tuple[int, int]) -> pygame.Vector2:
        target_px = pygame.Vector2((target[0] + 0.5) * TILE_SIZE, (target[1] + 0.5) * TILE_SIZE)
        if npc.path_target != target:
            npc.path = []
            npc.path_index = 0
            npc.path_target = target
        if npc.path_index < len(npc.path):
            next_grid = npc.path[npc.path_index]
            next_px = pygame.Vector2((next_grid[0] + 0.5) * TILE_SIZE, (next_grid[1] + 0.5) * TILE_SIZE)
            if npc.position.distance_to(next_px) < 10:
                npc.path_index += 1
                if npc.path_index >= len(npc.path):
                    npc.path = []
                    return target_px - npc.position
                next_grid = npc.path[npc.path_index]
                next_px = pygame.Vector2((next_grid[0] + 0.5) * TILE_SIZE, (next_grid[1] + 0.5) * TILE_SIZE)
            return next_px - npc.position
        return target_px - npc.position

    def pick_build_task(group: NPCGroup, npc_id: int) -> tuple[tuple[int, int], str] | None:
        for task_pos, task_tile in group.build_queue:
            if task_pos in group.claimed and group.claimed[task_pos] != npc_id:
                continue
            cost = BUILD_ITEMS.get(task_tile, {"wood": 2})
            if group.stockpile["wood"] < cost.get("wood", 0):
                continue
            if group.claim(task_pos, npc_id):
                return task_pos, task_tile
        return None

    members_by_group: dict[int, list[NPC]] = {}
    for npc in npcs:
        members_by_group.setdefault(npc.group_id, []).append(npc)
    npc_by_id = {npc.npc_id: npc for npc in npcs}

    for group_id, members in members_by_group.items():
        if group_id not in groups:
            groups[group_id] = NPCGroup(group_id, world.to_grid(members[0].position))
        group = groups[group_id]
        group.camp_grid = world.to_grid(members[0].position)
        ensure_build_queue(group, world)
        if group.build_origin is not None:
            bx, by = group.build_origin
            for y in range(by - 1, by + 2):
                for x in range(bx - 1, bx + 2):
                    if world.get_tile((x, y)) == "crate":
                        group.storage_tiles.add((x, y))
        group.storage_tiles = {pos for pos in group.storage_tiles if world.get_tile(pos) == "crate"}
        for key in group.storage_capacity:
            group.storage_capacity[key] = len(group.storage_tiles) * 20

    group_ids = list(members_by_group.keys())
    for i in range(len(group_ids)):
        for j in range(i + 1, len(group_ids)):
            if group_ids[i] not in groups or group_ids[j] not in groups:
                continue
            g1 = groups[group_ids[i]]
            g2 = groups[group_ids[j]]
            if g1.is_raider or g2.is_raider:
                continue
            if abs(g1.camp_grid[0] - g2.camp_grid[0]) + abs(g1.camp_grid[1] - g2.camp_grid[1]) < 6:
                for npc in members_by_group[g2.group_id]:
                    npc.group_id = g1.group_id
                    members_by_group[g1.group_id].append(npc)
                members_by_group[g2.group_id] = []
                if g2.group_id in groups:
                    del groups[g2.group_id]

    for group_id, members in members_by_group.items():
        if not members:
            continue
        group = groups[group_id]
        home_grid = group.build_origin or group.camp_grid
        base_done = group.build_origin is not None and base_complete(world, group.build_origin)
        group.home_grid = home_grid
        group.home_radius = compute_home_radius(group, base_done)
        has_workbench = find_tile_in_radius(world, home_grid, "workbench", radius=2) is not None
        update_group_goals(group, world, len(members))
        leader = members[0]
        for npc in members:
            npc.leader = False
        leader.leader = True
        cohesion_force = pygame.Vector2(0, 0)
        if len(members) > 1:
            center = pygame.Vector2(0, 0)
            for npc in members:
                center += npc.position
            center /= len(members)
            cohesion_force = center - leader.position
            if cohesion_force.length_squared() > 0:
                cohesion_force = cohesion_force.normalize()

        if not manual_control and (leader.job == "wander" or leader.job == "idle"):
            leader.state_timer -= dt
            if leader.state_timer <= 0 or leader.wander_dir.length_squared() == 0:
                leader.wander_dir = random_dir()
                leader.state_timer = random.uniform(2.0, 4.0)
            leader_dir = leader.wander_dir + cohesion_force * 0.4
            if abs(world.to_grid(leader.position)[0] - home_grid[0]) + abs(world.to_grid(leader.position)[1] - home_grid[1]) > group.home_radius:
                home_px = pygame.Vector2((home_grid[0] + 0.5) * TILE_SIZE, (home_grid[1] + 0.5) * TILE_SIZE)
                leader_dir = (home_px - leader.position)
            leader_dir = resolve_move_dir(leader, leader_dir, world)
            steer_npc(leader, leader_dir, 55)
        for npc in members:
            if npc.attack_cooldown > 0:
                npc.attack_cooldown = max(0.0, npc.attack_cooldown - dt)
            npc.hunger = min(1.0, npc.hunger + dt * 0.015)
            if group.stockpile["food"] <= 1 or npc.hunger > 0.7:
                npc.satisfaction = max(0.0, npc.satisfaction - dt * 0.03)
            else:
                npc.satisfaction = min(1.0, npc.satisfaction + dt * 0.02)
            if group.avoid_tiles:
                expired = []
                for key, weight in group.avoid_tiles.items():
                    weight = max(0.0, weight - dt * 0.1)
                    group.avoid_tiles[key] = weight
                    if weight <= 0.05:
                        expired.append(key)
                for key in expired:
                    del group.avoid_tiles[key]
            if npc.weapon is None:
                if group.weapons.get("spear", 0) > 0:
                    group.weapons["spear"] -= 1
                    npc.weapon = "spear"
                elif group.weapons.get("club", 0) > 0:
                    group.weapons["club"] -= 1
                    npc.weapon = "club"
            if npc.combat_target_id is not None:
                target = npc_by_id.get(npc.combat_target_id)
                if target is None or target.hp <= 0:
                    npc.combat_target_id = None
                else:
                    apply_melee_attack(npc, target)
            if npc.path_cooldown > 0:
                npc.path_cooldown = max(0.0, npc.path_cooldown - dt)
            if npc.job_lock_timer > 0:
                npc.job_lock_timer = max(0.0, npc.job_lock_timer - dt)
            if npc.task_cooldowns:
                expired = []
                for key, remaining in npc.task_cooldowns.items():
                    remaining = max(0.0, remaining - dt)
                    npc.task_cooldowns[key] = remaining
                    if remaining <= 0:
                        expired.append(key)
                for key in expired:
                    del npc.task_cooldowns[key]
            moved = npc.position.distance_to(npc.last_pos)
            npc.last_pos = pygame.Vector2(npc.position)
            if npc.target_grid is not None:
                if npc.travel_target != npc.target_grid:
                    npc.travel_target = npc.target_grid
                    npc.travel_timer = 0.0
                else:
                    npc.travel_timer += dt
            elif npc.travel_target is not None:
                npc.travel_total += npc.travel_timer
                npc.travel_samples += 1
                npc.travel_timer = 0.0
                npc.travel_target = None
            if not manual_control and abs(world.to_grid(npc.position)[0] - home_grid[0]) + abs(world.to_grid(npc.position)[1] - home_grid[1]) > group.home_radius + 4:
                if npc.inventory.get("wood", 0) > 0 or npc.inventory.get("food", 0) > 0 or npc.inventory.get("stone", 0) > 0:
                    npc.job = "haul"
                    npc.action_grid = None
                    npc.target_grid = None
                else:
                    npc.job = "return_home"
                    npc.action_grid = home_grid
                    npc.target_grid = find_adjacent_walkable(world, home_grid, world.to_grid(npc.position))
                npc.task_key = None
                npc.task_commit_timer = 0.0
            if npc.recover_timer > 0 and npc.recover_target is not None:
                npc.recover_timer = max(0.0, npc.recover_timer - dt)
                drive_to_target(npc, npc.recover_target, 70)
                target_px = pygame.Vector2(
                    (npc.recover_target[0] + 0.5) * TILE_SIZE,
                    (npc.recover_target[1] + 0.5) * TILE_SIZE,
                )
                if npc.position.distance_to(target_px) < 10 or npc.recover_timer <= 0:
                    if npc.recover_start_grid is not None and world.to_grid(npc.position) == npc.recover_start_grid:
                        escape = find_free_tile_near(world, npc.recover_start_grid, radius=4)
                        if escape is not None:
                            npc.position = pygame.Vector2(
                                (escape[0] + 0.5) * TILE_SIZE,
                                (escape[1] + 0.5) * TILE_SIZE,
                            )
                            npc.velocity = pygame.Vector2(0, 0)
                    npc.recover_timer = 0.0
                    npc.target_grid = npc.recover_return_target
                    npc.action_grid = npc.recover_return_action
                    npc.recover_target = None
                    npc.recover_return_target = None
                    npc.recover_return_action = None
                    npc.recover_start_grid = None
                continue
            if npc.job in {"build", "chop", "gather_food", "haul", "mine", "hunt", "haul_meat", "move"} and moved < 0.15:
                # Don't treat active work as "stuck" or it will cancel tasks mid-action.
                if npc.task_timer <= 0.0:
                    npc.stuck_timer += dt
                else:
                    npc.stuck_timer = 0.0
            elif npc.job in {"eat", "eat_stock"}:
                npc.stuck_timer = 0.0
            else:
                npc.stuck_timer = 0.0
            if npc.job not in task_jobs and npc.task_key is not None:
                npc.task_key = None
                npc.task_commit_timer = 0.0
            if manual_control and npc.job in {"idle", "wander"} and npc.command_queue:
                apply_manual_command(npc, npc.command_queue.pop(0))
            if manual_control and npc.job == "idle" and not npc.command_queue:
                npc.current_command_label = None
            if npc.job in task_jobs:
                if npc.task_key != npc.job:
                    npc.task_key = npc.job
                    npc.task_commit_timer = 20.0
                else:
                    npc.task_commit_timer = max(0.0, npc.task_commit_timer - dt)
                    if npc.task_commit_timer <= 0.0:
                        npc.task_cooldowns[npc.job] = 8.0
                        npc.job = "idle"
                        npc.target_grid = None
                        npc.action_grid = None
                        npc.task_timer = 0.0
                        npc.job_lock_timer = 0.6
            if npc.stuck_timer > 1.2:
                npc.stuck_events += 1
                current_grid = world.to_grid(npc.position)
                group.avoid_tiles[current_grid] = min(1.0, group.avoid_tiles.get(current_grid, 0.0) + 0.6)
                if npc.recover_timer <= 0:
                    escape = find_free_tile_near(world, current_grid, radius=3)
                    if escape is not None:
                        npc.recover_target = escape
                        npc.recover_return_target = npc.target_grid
                        npc.recover_return_action = npc.action_grid
                        npc.recover_start_grid = current_grid
                        npc.recover_timer = 1.0
                        npc.stuck_timer = 0.0
                        continue
                if npc.target_grid is not None:
                    ensure_path_to_target(npc, npc.target_grid)
                    if npc.path:
                        npc.stuck_timer = 0.0
                        continue
                if npc.action_grid is not None:
                    alt = find_adjacent_walkable(world, npc.action_grid, world.to_grid(npc.position))
                    if alt is not None:
                        npc.target_grid = alt
                    else:
                        npc.target_grid = None
                else:
                    npc.target_grid = None
                npc.stuck_timer = 0.0
                npc.action_grid = None
                npc.wander_dir = random_dir()
                npc.state_timer = 0.6
            if debug is not None:
                tile_pos = npc.action_grid or npc.target_grid
                tile = world.get_tile(tile_pos) if tile_pos is not None else "-"
                has_path = "Y" if npc.path else "N"
                path_len = str(len(npc.path)) if npc.path else "0"
                next_step = "-"
                if npc.path and npc.path_index < len(npc.path):
                    next_step = f"{npc.path[npc.path_index][0]},{npc.path[npc.path_index][1]}"
                last_dir = "-"
                if npc.velocity.length_squared() > 0.01:
                    norm = npc.velocity.normalize()
                    last_dir = f"{norm.x:+.1f},{norm.y:+.1f}"
                debug[npc.npc_id] = {
                    "role": "leader" if npc.leader else "member",
                    "job": npc.job,
                    "goal": goal_label(npc.job),
                    "group": str(group_id),
                    "task": f"{npc.task_timer:.1f}",
                    "tgt": fmt_grid(npc.target_grid),
                    "act": fmt_grid(npc.action_grid),
                    "tile": tile,
                    "path": has_path,
                    "plen": path_len,
                    "next": next_step,
                    "dir": last_dir,
                    "commit": f"{npc.task_commit_timer:.0f}",
                    "hp": f"{npc.hp:.0f}",
                    "stk": str(npc.stuck_events),
                    "pf": str(npc.path_failures),
                    "dw": str(npc.door_waits),
                    "avg": f"{(npc.travel_total / npc.travel_samples):.1f}" if npc.travel_samples else "-",
                    "sat": f"{npc.satisfaction:.2f}",
                    "wpn": npc.weapon or "-",
                }
            if npc.job in {"build", "chop", "gather_food", "haul", "hunt", "haul_meat"} and npc.target_grid is None:
                npc.action_grid = None

            if group.is_raider and not manual_control:
                npc.job = "raid"

            if npc.job == "idle" and npc.job_lock_timer == 0 and not manual_control:
                def on_cooldown(job: str) -> bool:
                    return npc.task_cooldowns.get(job, 0.0) > 0.0
                if npc.hunger > 0.6:
                    if group.stockpile["food"] > 0:
                        npc.job = "eat_stock"
                        npc.action_grid = None
                        npc.target_grid = None
                        npc.task_timer = 0.0
                        npc.eat_timer = 0.0
                        continue
                    if not on_cooldown("haul_meat"):
                        if find_nearest_carcass(carcasses, npc.position, TILE_SIZE * 8.0, allow_claimed_by=npc.npc_id) is not None:
                            npc.job = "haul_meat"
                            npc.action_grid = None
                            npc.target_grid = None
                            npc.task_timer = 0.0
                            continue
                assigned = False
                for goal in group.goals:
                    if goal == "build":
                        if group.build_queue and group.stockpile["wood"] >= 2 and not on_cooldown("build"):
                            npc.job = "build"
                            assigned = True
                            break
                    elif goal == "craft":
                        if (
                            base_done
                            and has_workbench
                            and group.tools.get("pickaxe", 0) < 1
                            and group.stockpile["wood"] >= CRAFT_RECIPES["pickaxe"]["wood"]
                            and not on_cooldown("craft_tool")
                        ):
                            npc.job = "craft_tool"
                            assigned = True
                            break
                        if (
                            base_done
                            and has_workbench
                            and (group.weapons["club"] + group.weapons["spear"]) < max(1, len(members) // 2)
                            and not on_cooldown("craft_weapon")
                        ):
                            npc.job = "craft_weapon"
                            assigned = True
                            break
                    elif goal == "wood":
                        if group.stockpile["wood"] < 6 and not on_cooldown("chop"):
                            npc.job = "chop"
                            assigned = True
                            break
                    elif goal == "stone":
                        if (
                            base_done
                            and group.stockpile["stone"] < 6
                            and group.tools.get("pickaxe", 0) > 0
                            and not on_cooldown("mine")
                        ):
                            npc.job = "mine"
                            assigned = True
                            break
                    elif goal == "food":
                        if npc.hunger > 0.6 and group.stockpile["food"] > 0 and not on_cooldown("eat_stock"):
                            npc.job = "eat_stock"
                            assigned = True
                            break
                        if npc.hunger > 0.6 and not on_cooldown("haul_meat"):
                            if find_nearest_carcass(carcasses, npc.position, TILE_SIZE * 8.0, allow_claimed_by=npc.npc_id) is not None:
                                npc.job = "haul_meat"
                                assigned = True
                                break
                        if npc.hunger > 0.6 and not on_cooldown("hunt"):
                            npc.job = "hunt"
                            assigned = True
                            break
                        if group.stockpile["food"] < 4 and not on_cooldown("gather_food"):
                            npc.job = "gather_food"
                            assigned = True
                            break
                if not assigned:
                    npc.job = "wander"

                if raids and npc.group_id in npc_groups:
                    target_group = None
                    for raid in raids:
                        if raid.get("group_id") == npc.group_id and raid.get("defender_group_id") is not None:
                            target_group = npc_groups.get(raid["defender_group_id"])
                            break
                    if target_group is not None:
                        defenders = [n for n in npcs if n.group_id == target_group.group_id and n.hp > 0]
                        if defenders:
                            closest = min(defenders, key=lambda d: d.position.distance_to(npc.position))
                            npc.combat_target_id = closest.npc_id
                            npc.job = "raid"
                if raids and npc.group_id in npc_groups:
                    attacker_group = None
                    for raid in raids:
                        if raid.get("defender_group_id") == npc.group_id and raid.get("group_id") is not None:
                            attacker_group = raid.get("group_id")
                            break
                    if attacker_group is not None:
                        attackers = [n for n in npcs if n.group_id == attacker_group and n.hp > 0]
                        if attackers:
                            closest = min(attackers, key=lambda d: d.position.distance_to(npc.position))
                            npc.combat_target_id = closest.npc_id

            if npc.job == "return_home":
                if npc.action_grid is None:
                    npc.action_grid = home_grid
                if npc.target_grid is None:
                    npc.target_grid = find_adjacent_walkable(world, npc.action_grid, world.to_grid(npc.position))
                if npc.target_grid is None:
                    npc.job = "idle"
                    npc.job_lock_timer = 0.4
                    continue
                target_px = pygame.Vector2((npc.target_grid[0] + 0.5) * TILE_SIZE, (npc.target_grid[1] + 0.5) * TILE_SIZE)
                if npc.position.distance_to(target_px) < 18:
                    npc.job = "idle"
                    npc.target_grid = None
                    npc.action_grid = None
                    npc.job_lock_timer = 0.4
                else:
                    drive_to_target(npc, npc.target_grid, 65)

            if npc.job == "craft_tool":
                bench = find_tile_in_radius(world, home_grid, "workbench", radius=2)
                if bench is None:
                    npc.job = "idle"
                    npc.job_lock_timer = 0.4
                else:
                    npc.action_grid = bench
                    if npc.target_grid is None:
                        npc.target_grid = find_adjacent_walkable(world, bench, world.to_grid(npc.position))
                    action_px = pygame.Vector2((bench[0] + 0.5) * TILE_SIZE, (bench[1] + 0.5) * TILE_SIZE)
                    in_range = npc.position.distance_to(action_px) <= TILE_SIZE * 1.2
                    if in_range:
                        npc.task_timer += dt
                        if npc.task_timer >= 1.4:
                            if group.stockpile["wood"] >= CRAFT_RECIPES["pickaxe"]["wood"]:
                                group.stockpile["wood"] -= CRAFT_RECIPES["pickaxe"]["wood"]
                                group.tools["pickaxe"] = group.tools.get("pickaxe", 0) + 1
                            npc.task_timer = 0.0
                            npc.job = "idle"
                            npc.target_grid = None
                            npc.action_grid = None
                    else:
                        if npc.target_grid is None:
                            npc.job_lock_timer = 0.6
                        else:
                            drive_to_target(npc, npc.target_grid, 55)

            if npc.job == "craft_weapon":
                bench = find_tile_in_radius(world, home_grid, "workbench", radius=2)
                if bench is None:
                    npc.job = "idle"
                    npc.job_lock_timer = 0.4
                else:
                    npc.action_grid = bench
                    if npc.target_grid is None:
                        npc.target_grid = find_adjacent_walkable(world, bench, world.to_grid(npc.position))
                    action_px = pygame.Vector2((bench[0] + 0.5) * TILE_SIZE, (bench[1] + 0.5) * TILE_SIZE)
                    in_range = npc.position.distance_to(action_px) <= TILE_SIZE * 1.2
                    if in_range:
                        npc.task_timer += dt
                        if npc.task_timer >= 1.6:
                            if group.stockpile["stone"] >= 1 and group.stockpile["wood"] >= 1:
                                group.stockpile["stone"] -= 1
                                group.stockpile["wood"] -= 1
                                group.weapons["spear"] += 1
                            elif group.stockpile["wood"] >= 2:
                                group.stockpile["wood"] -= 2
                                group.weapons["club"] += 1
                            npc.task_timer = 0.0
                            npc.job = "idle"
                            npc.target_grid = None
                            npc.action_grid = None
                    else:
                        if npc.target_grid is None:
                            npc.job_lock_timer = 0.6
                        else:
                            drive_to_target(npc, npc.target_grid, 55)
            if npc.job == "hunt":
                if manual_control and npc.hunt_target is None:
                    npc.job = "idle"
                    npc.job_lock_timer = 0.2
                    npc.target_grid = None
                    npc.action_grid = None
                    continue
                if npc.hunt_target is not None and npc.hunt_target not in animals:
                    npc.hunt_target = None
                if abs(world.to_grid(npc.position)[0] - home_grid[0]) + abs(world.to_grid(npc.position)[1] - home_grid[1]) <= 2:
                    door = find_home_door(group, world)
                    if door is not None:
                        npc.target_grid = door
                        npc.action_grid = None
                        npc.task_timer = 0.0
                        drive_to_target(npc, npc.target_grid, 70)
                        continue
                    exit_tile = find_work_zone_exit(group, world, world.to_grid(npc.position))
                    if exit_tile is not None:
                        npc.target_grid = exit_tile
                        npc.action_grid = None
                        npc.task_timer = 0.0
                        drive_to_target(npc, npc.target_grid, 70)
                        continue
                if npc.hunt_target is None:
                    npc.hunt_target = find_hunt_target(npc)
                target = npc.hunt_target
                if target is None:
                    npc.job = "idle"
                    npc.job_lock_timer = 0.4
                    npc.target_grid = None
                    npc.action_grid = None
                else:
                    npc.action_grid = world.to_grid(target.position)
                    npc.target_grid = npc.action_grid
                    if npc.position.distance_to(target.position) < 14:
                        if target in animals:
                            animals.remove(target)
                        new_carcass = Carcass(target.position, bites=3)
                        new_carcass.claimed_by = npc.npc_id
                        carcasses.append(new_carcass)
                        npc.job = "haul_meat"
                        npc.target_grid = None
                        npc.action_grid = None
                        npc.hunt_target = None
                    else:
                        drive_to_target(npc, npc.target_grid, 90)
            if npc.job == "haul_meat":
                if npc.action_grid is None:
                    carcass = find_nearest_carcass(
                        carcasses,
                        npc.position,
                        TILE_SIZE * 10.0,
                        allow_claimed_by=npc.npc_id,
                    )
                    if carcass is None:
                        npc.job = "idle"
                        npc.job_lock_timer = 0.4
                    else:
                        carcass.claimed_by = npc.npc_id
                        npc.eat_target = carcass
                        npc.action_grid = world.to_grid(carcass.position)
                        npc.target_grid = find_adjacent_walkable(
                            world,
                            npc.action_grid,
                            world.to_grid(npc.position),
                            allow_doors=True,
                        )
                        npc.task_timer = 0.0
                else:
                    if npc.eat_target is None or npc.eat_target not in carcasses:
                        npc.job = "idle"
                        npc.action_grid = None
                        npc.target_grid = None
                        npc.job_lock_timer = 0.4
                        continue
                    action_px = pygame.Vector2((npc.action_grid[0] + 0.5) * TILE_SIZE, (npc.action_grid[1] + 0.5) * TILE_SIZE)
                    if npc.position.distance_to(action_px) < 18:
                        food_gain = max(1, npc.eat_target.bites_left)
                        npc.inventory["food"] += food_gain
                        if npc.eat_target in carcasses:
                            carcasses.remove(npc.eat_target)
                        npc.eat_target = None
                        npc.job = "haul"
                        npc.target_grid = None
                        npc.action_grid = None
                    else:
                        if npc.target_grid is None:
                            npc.target_grid = find_adjacent_walkable(
                                world,
                                npc.action_grid,
                                world.to_grid(npc.position),
                                allow_doors=True,
                            )
                        drive_to_target(npc, npc.target_grid or npc.action_grid, 70)
            if npc.job == "eat":
                if npc.eat_target is not None and npc.eat_target not in carcasses:
                    npc.eat_target = None
                carcass = npc.eat_target
                if carcass is None:
                    carcass = find_nearest_carcass(
                        carcasses,
                        npc.position,
                        TILE_SIZE * 2.5,
                        allow_claimed_by=npc.npc_id,
                    )
                    npc.eat_target = carcass
                if carcass is None:
                    npc.job = "idle"
                    npc.job_lock_timer = 0.4
                    npc.eat_timer = 0.0
                else:
                    if carcass.claimed_by is None:
                        carcass.claimed_by = npc.npc_id
                    if npc.position.distance_to(carcass.position) > 18:
                        npc.target_grid = world.to_grid(carcass.position)
                        if npc.target_grid is not None:
                            npc.target_grid = find_adjacent_walkable(
                                world,
                                npc.target_grid,
                                world.to_grid(npc.position),
                                allow_doors=True,
                            ) or npc.target_grid
                        drive_to_target(npc, npc.target_grid, 55)
                        npc.eat_timer = 0.0
                    else:
                        npc.eat_timer += dt
                        if npc.eat_timer >= 1.2:
                            npc.eat_timer = 0.0
                            npc.hunger = max(0.0, npc.hunger - 0.6)
                            carcass.bites_left -= 1
                            if carcass.bites_left <= 0:
                                if carcass in carcasses:
                                    carcasses.remove(carcass)
                                npc.eat_target = None
                            if carcass.claimed_by == npc.npc_id:
                                carcass.claimed_by = None
                            if npc.hunger < 0.3:
                                npc.job = "idle"
                                npc.target_grid = None
                                npc.action_grid = None
                                npc.eat_target = None
            if npc.job == "eat_stock":
                if npc.action_grid is None:
                    target_tile, approach = pick_stockpile_destination(
                        group,
                        world,
                        world.to_grid(npc.position),
                    )
                    npc.action_grid = target_tile
                    npc.target_grid = approach
                if npc.action_grid is None or npc.target_grid is None:
                    npc.job = "idle"
                    npc.job_lock_timer = 0.4
                    continue
                action_px = pygame.Vector2(
                    (npc.action_grid[0] + 0.5) * TILE_SIZE,
                    (npc.action_grid[1] + 0.5) * TILE_SIZE,
                )
                in_range = npc.position.distance_to(action_px) <= TILE_SIZE * 1.2
                if in_range:
                    npc.eat_timer += dt
                    if npc.eat_timer >= 1.2:
                        npc.eat_timer = 0.0
                        if group.stockpile["food"] > 0:
                            group.stockpile["food"] -= 1
                            npc.hunger = max(0.0, npc.hunger - 0.6)
                            npc.satisfaction = min(1.0, npc.satisfaction + 0.1)
                        if npc.hunger < 0.3 or group.stockpile["food"] <= 0:
                            npc.job = "idle"
                            npc.action_grid = None
                            npc.target_grid = None
                else:
                    drive_to_target(npc, npc.target_grid, 55)
            if npc.job == "chop":
                if manual_control and npc.action_grid is None:
                    npc.job = "idle"
                    npc.job_lock_timer = 0.2
                    npc.target_grid = None
                    npc.action_grid = None
                    continue
                if npc.target_grid is None:
                    if npc.action_grid is None:
                        if abs(world.to_grid(npc.position)[0] - home_grid[0]) + abs(world.to_grid(npc.position)[1] - home_grid[1]) <= 2:
                            door = find_home_door(group, world)
                            if door is not None:
                                npc.target_grid = door
                                npc.action_grid = None
                                npc.task_timer = 0.0
                                continue
                            exit_tile = find_work_zone_exit(group, world, world.to_grid(npc.position))
                            if exit_tile is not None:
                                npc.target_grid = exit_tile
                                npc.action_grid = None
                                npc.task_timer = 0.0
                                continue
                        target = find_reachable_target(
                            world,
                            world.to_grid(npc.position),
                            {"tree"},
                            radius=12,
                            home_grid=home_grid,
                            home_radius=group.home_radius,
                        )
                        npc.action_grid = target
                        if target is not None:
                            npc.target_grid = find_adjacent_walkable(world, target, world.to_grid(npc.position))
                    else:
                        npc.target_grid = find_adjacent_walkable(
                            world,
                            npc.action_grid,
                            world.to_grid(npc.position),
                            allow_doors=True,
                        ) or npc.action_grid
                    npc.task_timer = 0.0
                if npc.action_grid is None:
                    if npc.target_grid is not None:
                        target_px = pygame.Vector2(
                            (npc.target_grid[0] + 0.5) * TILE_SIZE,
                            (npc.target_grid[1] + 0.5) * TILE_SIZE,
                        )
                        if npc.position.distance_to(target_px) < 12:
                            npc.target_grid = None
                        else:
                            drive_to_target(npc, npc.target_grid, 60)
                        continue
                    npc.job_lock_timer = 0.6
                else:
                    if world.get_tile(npc.action_grid) != "tree":
                        npc.job = "idle"
                        npc.target_grid = None
                        npc.action_grid = None
                        npc.task_timer = 0.0
                        npc.job_lock_timer = 0.4
                        continue
                    action_px = pygame.Vector2((npc.action_grid[0] + 0.5) * TILE_SIZE, (npc.action_grid[1] + 0.5) * TILE_SIZE)
                    npc_grid = world.to_grid(npc.position)
                    grid_dx = abs(npc_grid[0] - npc.action_grid[0])
                    grid_dy = abs(npc_grid[1] - npc.action_grid[1])
                    in_range = max(grid_dx, grid_dy) <= 1 or npc.position.distance_to(action_px) <= TILE_SIZE * 1.5
                    if debug is not None:
                        debug[npc.npc_id]["in"] = "Y" if in_range else "N"
                    if in_range:
                        npc.task_timer += dt
                        if npc.task_timer >= 1.5:
                            world.set_tile(npc.action_grid, "ground")
                            npc.inventory["wood"] += 2
                            npc.job = "haul"
                            npc.target_grid = pick_stockpile_target(group, world, world.to_grid(npc.position))
                            npc.action_grid = None
                            npc.task_timer = 0.0
                    else:
                        if npc.target_grid is None:
                            npc.target_grid = find_adjacent_walkable(
                                world,
                                npc.action_grid,
                                world.to_grid(npc.position),
                            )
                        if npc.target_grid is None:
                            npc.job_lock_timer = 0.6
                        else:
                            drive_to_target(npc, npc.target_grid, 55)

            if npc.job == "raid":
                if npc.target_grid is None and npc.action_grid is not None:
                    npc.target_grid = find_adjacent_walkable(world, npc.action_grid, world.to_grid(npc.position))
                if npc.target_grid is None:
                    npc.job = "wander"
                    npc.job_lock_timer = 0.4
                else:
                    drive_to_target(npc, npc.target_grid, 65)
            if npc.job == "mine":
                if manual_control and npc.action_grid is None:
                    npc.job = "idle"
                    npc.job_lock_timer = 0.2
                    npc.target_grid = None
                    npc.action_grid = None
                    continue
                if group.tools.get("pickaxe", 0) <= 0:
                    npc.job = "idle"
                    npc.job_lock_timer = 0.4
                elif npc.target_grid is None:
                    if npc.action_grid is None:
                        if abs(world.to_grid(npc.position)[0] - home_grid[0]) + abs(world.to_grid(npc.position)[1] - home_grid[1]) <= 2:
                            door = find_home_door(group, world)
                            if door is not None:
                                npc.target_grid = door
                                npc.action_grid = None
                                npc.task_timer = 0.0
                                continue
                            exit_tile = find_work_zone_exit(group, world, world.to_grid(npc.position))
                            if exit_tile is not None:
                                npc.target_grid = exit_tile
                                npc.action_grid = None
                                npc.task_timer = 0.0
                                continue
                        target = find_reachable_target(
                            world,
                            world.to_grid(npc.position),
                            {"rock"},
                            radius=12,
                            home_grid=home_grid,
                            home_radius=group.home_radius,
                        )
                        npc.action_grid = target
                        if target is not None:
                            npc.target_grid = find_adjacent_walkable(world, target, world.to_grid(npc.position))
                    else:
                        npc.target_grid = find_adjacent_walkable(
                            world,
                            npc.action_grid,
                            world.to_grid(npc.position),
                            allow_doors=True,
                        ) or npc.action_grid
                    npc.task_timer = 0.0
                if npc.action_grid is None:
                    if npc.target_grid is not None:
                        target_px = pygame.Vector2(
                            (npc.target_grid[0] + 0.5) * TILE_SIZE,
                            (npc.target_grid[1] + 0.5) * TILE_SIZE,
                        )
                        if npc.position.distance_to(target_px) < 12:
                            npc.target_grid = None
                        else:
                            drive_to_target(npc, npc.target_grid, 60)
                        continue
                    npc.job_lock_timer = 0.6
                else:
                    if world.get_tile(npc.action_grid) != "rock":
                        npc.job = "idle"
                        npc.target_grid = None
                        npc.action_grid = None
                        npc.task_timer = 0.0
                        npc.job_lock_timer = 0.4
                        continue
                    action_px = pygame.Vector2((npc.action_grid[0] + 0.5) * TILE_SIZE, (npc.action_grid[1] + 0.5) * TILE_SIZE)
                    npc_grid = world.to_grid(npc.position)
                    grid_dx = abs(npc_grid[0] - npc.action_grid[0])
                    grid_dy = abs(npc_grid[1] - npc.action_grid[1])
                    in_range = max(grid_dx, grid_dy) <= 1 or npc.position.distance_to(action_px) <= TILE_SIZE * 1.5
                    if debug is not None:
                        debug[npc.npc_id]["in"] = "Y" if in_range else "N"
                    if in_range:
                        npc.task_timer += dt
                        if npc.task_timer >= 1.8:
                            world.set_tile(npc.action_grid, "ground")
                            npc.inventory["stone"] += 2
                            npc.job = "haul"
                            npc.target_grid = pick_stockpile_target(group, world, world.to_grid(npc.position))
                            npc.action_grid = None
                            npc.task_timer = 0.0
                    else:
                        if npc.target_grid is None:
                            npc.target_grid = find_adjacent_walkable(
                                world,
                                npc.action_grid,
                                world.to_grid(npc.position),
                            )
                        if npc.target_grid is None:
                            npc.job_lock_timer = 0.6
                        else:
                            drive_to_target(npc, npc.target_grid, 55)

            elif npc.job == "gather_food":
                if manual_control and npc.action_grid is None:
                    npc.job = "idle"
                    npc.job_lock_timer = 0.2
                    npc.target_grid = None
                    npc.action_grid = None
                    continue
                if npc.action_grid is None:
                    if abs(world.to_grid(npc.position)[0] - home_grid[0]) + abs(world.to_grid(npc.position)[1] - home_grid[1]) <= 2:
                        door = find_home_door(group, world)
                        if door is not None:
                            npc.target_grid = door
                            npc.action_grid = None
                            npc.task_timer = 0.0
                            continue
                        exit_tile = find_work_zone_exit(group, world, world.to_grid(npc.position))
                        if exit_tile is not None:
                            npc.target_grid = exit_tile
                            npc.action_grid = None
                            npc.task_timer = 0.0
                            continue
                    plant = plants.find_near(npc.position, radius_tiles=5)
                    if plant is not None:
                        npc.action_grid = world.to_grid(plant.position)
                else:
                    plant = plants.plants.get(npc.action_grid)
                if plant is None:
                    npc.job = "idle"
                    npc.job_lock_timer = 0.4
                    npc.action_grid = None
                    npc.target_grid = None
                else:
                    if npc.target_grid is None:
                        npc.target_grid = find_adjacent_walkable(
                            world,
                            npc.action_grid,
                            world.to_grid(npc.position),
                            allow_doors=True,
                        ) or npc.action_grid
                    target_px = plant.position
                    if npc.position.distance_to(target_px) < 16:
                        npc.task_timer += dt
                        if npc.task_timer >= 1.2:
                            plants.consume(plant)
                            npc.inventory["food"] += 1
                            npc.job = "haul"
                            npc.target_grid = pick_stockpile_target(group, world, world.to_grid(npc.position))
                            npc.action_grid = None
                            npc.task_timer = 0.0
                    else:
                        drive_to_target(npc, npc.target_grid, 55)

            elif npc.job == "haul":
                if npc.target_grid is None or npc.action_grid is None:
                    target_tile, approach = pick_stockpile_destination(group, world, world.to_grid(npc.position))
                    npc.action_grid = target_tile
                    npc.target_grid = approach
                if npc.action_grid is None or npc.target_grid is None:
                    npc.job = "idle"
                    npc.job_lock_timer = 0.4
                    continue
                action_px = pygame.Vector2((npc.action_grid[0] + 0.5) * TILE_SIZE, (npc.action_grid[1] + 0.5) * TILE_SIZE)
                in_range = npc.position.distance_to(action_px) <= TILE_SIZE * 1.2
                if npc.inventory["wood"] <= 0 and npc.inventory["food"] <= 0:
                    npc.job = "idle"
                    npc.target_grid = None
                    npc.action_grid = None
                    npc.job_lock_timer = 0.4
                elif in_range:
                    if npc.inventory["wood"] > 0:
                        added = add_to_stockpile(group, "wood", npc.inventory["wood"])
                        npc.inventory["wood"] -= added
                    if npc.inventory["food"] > 0:
                        added = add_to_stockpile(group, "food", npc.inventory["food"])
                        npc.inventory["food"] -= added
                    if npc.inventory.get("stone", 0) > 0:
                        added = add_to_stockpile(group, "stone", npc.inventory["stone"])
                        npc.inventory["stone"] -= added
                    npc.job = "idle"
                    npc.action_grid = None
                else:
                    drive_to_target(npc, npc.target_grid, 55)

            if npc.job == "move":
                if npc.target_grid is None:
                    npc.job = "idle"
                    npc.job_lock_timer = 0.2
                    npc.action_grid = None
                else:
                    target_px = pygame.Vector2(
                        (npc.target_grid[0] + 0.5) * TILE_SIZE,
                        (npc.target_grid[1] + 0.5) * TILE_SIZE,
                    )
                    if npc.position.distance_to(target_px) < 12:
                        npc.job = "idle"
                        npc.target_grid = None
                        npc.action_grid = None
                    else:
                        drive_to_target(npc, npc.target_grid, 70)

            elif npc.job == "build":
                if not group.build_queue:
                    npc.job = "idle"
                    npc.job_lock_timer = 0.4
                else:
                    task = pick_build_task(group, npc.npc_id)
                    if task is None:
                        npc.job = "chop"
                        npc.job_lock_timer = 0.4
                    else:
                        task_pos, task_tile = task
                        current_tile = world.get_tile(task_pos)
                        if current_tile == task_tile or (task_tile == "door" and current_tile == "door_closed"):
                            if (task_pos, task_tile) in group.build_queue:
                                group.build_queue.remove((task_pos, task_tile))
                            group.release(task_pos)
                            npc.job = "idle"
                            npc.target_grid = None
                            npc.action_grid = None
                            npc.task_timer = 0.0
                            npc.job_lock_timer = 0.4
                            continue
                        npc.target_grid = task_pos
                        npc.action_grid = task_pos
                        target_px = pygame.Vector2((task_pos[0] + 0.5) * TILE_SIZE, (task_pos[1] + 0.5) * TILE_SIZE)
                        if npc.position.distance_to(target_px) < 16:
                            npc.task_timer += dt
                            if npc.task_timer >= 1.6:
                                if task_tile == "door":
                                    world.set_tile(task_pos, "door_closed")
                                elif task_tile == "crate":
                                    world.set_tile(task_pos, "crate")
                                    group.storage_tiles.add(task_pos)
                                    for key in group.storage_capacity:
                                        group.storage_capacity[key] += 20
                                elif task_tile in {"stone_wall", "stone_floor"}:
                                    world.set_tile(task_pos, task_tile)
                                else:
                                    world.set_tile(task_pos, task_tile)
                                cost = BUILD_ITEMS.get(task_tile, {"wood": 2})
                                if "wood" in cost:
                                    group.stockpile["wood"] -= cost.get("wood", 0)
                                if "stone" in cost:
                                    group.stockpile["stone"] -= cost.get("stone", 0)
                                if (task_pos, task_tile) in group.build_queue:
                                    group.build_queue.remove((task_pos, task_tile))
                                group.release(task_pos)
                                npc.task_timer = 0.0
                                npc.target_grid = None
                                npc.action_grid = None
                                npc.job = "idle"
                                npc.job_lock_timer = 0.4
                        else:
                            drive_to_target(npc, task_pos, 55)

            else:
                if manual_control and npc.job in {"idle", "wander"}:
                    npc.velocity *= 0.5
                    continue
                target = leader.position
                if npc.position.distance_to(target) > 24:
                    drive_to_target(npc, world.to_grid(target), 50)
                else:
                    npc.state_timer -= dt
                    if npc.state_timer <= 0 or npc.wander_dir.length_squared() == 0:
                        npc.wander_dir = random_dir()
                        npc.state_timer = random.uniform(2.0, 4.0)
                    move_dir = resolve_move_dir(npc, npc.wander_dir, world)
                    steer_npc(npc, move_dir, 40)
