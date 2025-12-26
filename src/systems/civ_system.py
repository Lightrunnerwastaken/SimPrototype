import random

import pygame

from src.constants import TILE_SIZE, REGION_SIZE, CIV_MIN_SPAWN_DIST, CIV_MAX_SPAWN_DIST
from src.entity import NPC
from src.world import World
from src.systems.npc_system import NPCGroup
from dataclasses import dataclass, field


@dataclass
class CivRegion:
    origin: tuple[int, int]
    stage: int = 0
    population: int = 3
    stockpile: dict[str, int] = field(default_factory=lambda: {"wood": 4, "food": 2, "stone": 0})
    tools: dict[str, int] = field(default_factory=lambda: {"pickaxe": 0})
    crates: int = 0
    last_event: str = "spawn"
    materialized: bool = False
    focus: str = "growth"
    project: str | None = None
    project_cost: dict[str, int] = field(default_factory=dict)
    project_progress: float = 0.0
    project_duration: float = 0.0
    project_active: bool = False
    focus_timer: float = 0.0
    project_cooldowns: dict[str, float] = field(default_factory=dict)
    built_roads: bool = False
    built_water_post: bool = False
    known_techs: set[str] = field(default_factory=set)
    research_points: float = 0.0
    current_research: str | None = None
    allies: set[tuple[int, int]] = field(default_factory=set)
    last_trade: str = "-"
    hostility: dict[tuple[int, int], float] = field(default_factory=dict)
    raid_timer: float = 0.0
    last_raid: str = "-"
    war_state: str = "neutral"
    weapons: dict[str, int] = field(default_factory=lambda: {"club": 0, "spear": 0})
    wiped: bool = False


def grid_to_region(grid_pos: tuple[int, int]) -> tuple[int, int]:
    return grid_pos[0] // REGION_SIZE, grid_pos[1] // REGION_SIZE

def region_bounds(region: tuple[int, int]) -> tuple[int, int, int, int]:
    rx, ry = region
    start_x = rx * REGION_SIZE
    start_y = ry * REGION_SIZE
    return start_x, start_y, start_x + REGION_SIZE - 1, start_y + REGION_SIZE - 1

def region_clear(world: World, origin: tuple[int, int], radius: int) -> bool:
    ox, oy = origin
    for y in range(oy - radius, oy + radius + 1):
        for x in range(ox - radius, ox + radius + 1):
            tile = world.get_tile((x, y))
            if tile in {"water", "mountain"}:
                return False
    return True

def find_land_in_region(world: World, region: tuple[int, int], attempts: int = 40) -> tuple[int, int] | None:
    start_x, start_y, end_x, end_y = region_bounds(region)
    for _ in range(attempts):
        gx = random.randint(start_x, end_x)
        gy = random.randint(start_y, end_y)
        tile = world.get_tile((gx, gy))
        if tile in {"water", "mountain"}:
            continue
        if region_clear(world, (gx, gy), radius=2):
            return (gx, gy)
    return None

def find_land_near(world: World, center: tuple[int, int], radius: int = 10) -> tuple[int, int] | None:
    cx, cy = center
    for r in range(3, radius + 1):
        for _ in range(20):
            gx = cx + random.randint(-r, r)
            gy = cy + random.randint(-r, r)
            tile = world.get_tile((gx, gy))
            if tile in {"water", "mountain"}:
                continue
            if region_clear(world, (gx, gy), radius=2):
                return (gx, gy)
    return None

def find_water_near(world: World, center: tuple[int, int], radius: int = 8) -> tuple[int, int] | None:
    cx, cy = center
    best = None
    best_dist = None
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            if world.get_tile((x, y)) != "water":
                continue
            dist = abs(x - cx) + abs(y - cy)
            if best is None or dist < best_dist:
                best = (x, y)
                best_dist = dist
    return best

def environment_scores(world: World, origin: tuple[int, int], radius: int = 10) -> dict[str, float]:
    counts = {"water": 0, "tree": 0, "rock": 0}
    total = 0
    cx, cy = origin
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            total += 1
            tile = world.get_tile((x, y))
            if tile == "water":
                counts["water"] += 1
            elif tile == "tree":
                counts["tree"] += 1
            elif tile == "rock":
                counts["rock"] += 1
    if total == 0:
        return {"water": 0.0, "wood": 0.0, "stone": 0.0}
    return {
        "water": counts["water"] / total,
        "wood": counts["tree"] / total,
        "stone": counts["rock"] / total,
    }

def place_path(world: World, start: tuple[int, int], end: tuple[int, int], tile: str = "road") -> None:
    x, y = start
    ex, ey = end
    step_x = 1 if ex >= x else -1
    step_y = 1 if ey >= y else -1
    while x != ex:
        if world.get_tile((x, y)) in {"ground", "sand", "floor", "stone_floor"}:
            world.set_tile((x, y), tile)
        x += step_x
    while y != ey:
        if world.get_tile((x, y)) in {"ground", "sand", "floor", "stone_floor"}:
            world.set_tile((x, y), tile)
        y += step_y

def place_water_outpost(world: World, origin: tuple[int, int], water_tile: tuple[int, int]) -> None:
    ox, oy = origin
    wx, wy = water_tile
    out_x = ox + (1 if wx > ox else -1)
    out_y = oy + (1 if wy > oy else -1)
    if world.get_tile((out_x, out_y)) in {"water", "mountain"}:
        return
    world.set_tile((out_x, out_y), "floor")
    world.set_tile((out_x, out_y + 1), "crate")

def place_ruins(world: World, origin: tuple[int, int]) -> None:
    ox, oy = origin
    for y in range(oy - 1, oy + 2):
        for x in range(ox - 1, ox + 2):
            tile = world.get_tile((x, y))
            if tile in {"water", "mountain"}:
                continue
            if x == ox and y == oy:
                world.set_tile((x, y), "crate")
            elif x == ox - 1 or x == ox + 1 or y == oy - 1 or y == oy + 1:
                world.set_tile((x, y), "stone_floor")
            else:
                world.set_tile((x, y), "stone_floor")
    for pos in ((ox + 1, oy), (ox - 1, oy), (ox, oy + 1), (ox, oy - 1)):
        if world.get_tile(pos) not in {"water", "mountain"}:
            world.set_tile(pos, "crate")

def civ_distance(a: CivRegion, b: CivRegion) -> int:
    return abs(a.origin[0] - b.origin[0]) + abs(a.origin[1] - b.origin[1])

def simulate_civ_relations(
    civ_regions: dict[tuple[int, int], CivRegion],
    relations: dict[frozenset[tuple[int, int]], str],
    event_log: list[str],
    raids: list[dict[str, object]],
    raid_log: list[str],
) -> None:
    tech_values = {
        "basic_tools": 2,
        "roads": 2,
        "waterworks": 3,
        "masonry": 3,
    }
    severity = {"neutral": 0, "ally": 1, "rival": 2, "war": 3}
    state: dict[tuple[int, int], str] = {key: "neutral" for key in civ_regions}
    regions = list(civ_regions.items())
    for i in range(len(regions)):
        key_a, civ_a = regions[i]
        for j in range(i + 1, len(regions)):
            key_b, civ_b = regions[j]
            if civ_distance(civ_a, civ_b) > REGION_SIZE * 8:
                continue
            pair_key = frozenset((key_a, key_b))
            relation = relations.get(pair_key, "neutral")
            if relation == "neutral":
                chance = 0.03
                if civ_a.focus == "trade" or civ_b.focus == "trade":
                    chance += 0.05
                roll = random.random()
                if roll < chance:
                    relations[pair_key] = "ally"
                    civ_a.allies.add(key_b)
                    civ_b.allies.add(key_a)
                    msg = f"alliance g{key_a}->{key_b}"
                    event_log.append(msg)
                    civ_a.last_event = "ally"
                    civ_b.last_event = "ally"
                elif roll > 0.98:
                    relations[pair_key] = "rival"
                    msg = f"rivalry g{key_a}->{key_b}"
                    event_log.append(msg)
                    civ_a.last_event = "rival"
                    civ_b.last_event = "rival"
            elif relation == "ally":
                if random.random() < 0.25:
                    techs_a = civ_a.known_techs - civ_b.known_techs
                    techs_b = civ_b.known_techs - civ_a.known_techs
                    if techs_a:
                        tech = random.choice(list(techs_a))
                        cost = tech_values.get(tech, 2)
                        if civ_b.stockpile["wood"] >= cost:
                            civ_b.stockpile["wood"] -= cost
                            civ_a.stockpile["wood"] += cost
                            civ_b.known_techs.add(tech)
                            msg = f"knowledge {key_a}->{key_b} {tech} w:{cost}"
                            event_log.append(msg)
                            civ_a.last_trade = tech
                            civ_b.last_trade = tech
                    elif techs_b:
                        tech = random.choice(list(techs_b))
                        cost = tech_values.get(tech, 2)
                        if civ_a.stockpile["wood"] >= cost:
                            civ_a.stockpile["wood"] -= cost
                            civ_b.stockpile["wood"] += cost
                            civ_a.known_techs.add(tech)
                            msg = f"knowledge {key_b}->{key_a} {tech} w:{cost}"
                            event_log.append(msg)
                            civ_a.last_trade = tech
                            civ_b.last_trade = tech
            elif relation == "rival":
                civ_a.hostility[key_b] = civ_a.hostility.get(key_b, 0.0) + 0.6
                civ_b.hostility[key_a] = civ_b.hostility.get(key_a, 0.0) + 0.6
                if civ_a.hostility[key_b] > 6.0:
                    relations[pair_key] = "war"
                    msg = f"war g{key_a}->{key_b}"
                    event_log.append(msg)
                    civ_a.last_event = "war"
                    civ_b.last_event = "war"
            elif relation == "war":
                civ_a.raid_timer += 1.0
                civ_b.raid_timer += 1.0
                if civ_a.raid_timer >= 4.0:
                    civ_a.raid_timer = 0.0
                    resolve_raid(civ_a, civ_b, event_log, raid_log, key_a, key_b, raids)
                if civ_b.raid_timer >= 4.0:
                    civ_b.raid_timer = 0.0
                    resolve_raid(civ_b, civ_a, event_log, raid_log, key_b, key_a, raids)
            if severity[relation] > severity[state[key_a]]:
                state[key_a] = relation
            if severity[relation] > severity[state[key_b]]:
                state[key_b] = relation
    for key, civ in civ_regions.items():
        civ.war_state = state.get(key, "neutral")

def resolve_raid(
    attacker: CivRegion,
    defender: CivRegion,
    event_log: list[str],
    raid_log: list[str],
    attacker_key: tuple[int, int],
    defender_key: tuple[int, int],
    raids: list[dict[str, object]] | None = None,
) -> None:
    attacker_power = attacker.population + attacker.tools.get("pickaxe", 0)
    attacker_power += attacker.weapons.get("spear", 0) + attacker.weapons.get("club", 0) * 0.5
    defender_power = defender.population
    if "masonry" in defender.known_techs:
        defender_power += 2
    if defender.built_roads:
        defender_power += 1
    roll = random.random() + attacker_power * 0.05 - defender_power * 0.04
    onscreen = attacker.materialized or defender.materialized
    if roll > 0.5 and defender.stockpile["food"] > 0:
        steal = min(defender.stockpile["food"], random.randint(1, 3))
        if not onscreen:
            defender.stockpile["food"] -= steal
            attacker.stockpile["food"] += steal
        attacker.last_event = "raid_success"
        defender.last_event = "raid_loss"
        attacker.last_raid = f"raid g{attacker_key}->{defender_key} food:{steal} p:{attacker_power:.1f}/{defender_power:.1f}"
        defender.last_raid = f"raided by g{attacker_key}"
        event_log.append(attacker.last_raid)
        raid_log.append(attacker.last_raid)
        if raids is not None:
            raids.append(
                {
                    "start": attacker.origin,
                    "target": defender.origin,
                    "size": max(2, min(attacker.population, 5)),
                    "defender_id": None,
                    "spawned": False,
                    "loot": steal,
                    "phase": "attack",
                    "loot_applied": not onscreen,
                    "completed": False,
                }
            )
    else:
        if not onscreen:
            if attacker.population > 2 and random.random() < 0.3:
                attacker.population -= 1
        attacker.last_event = "raid_fail"
        defender.last_event = "defended"
        attacker.last_raid = f"raid_fail g{attacker_key}->{defender_key} p:{attacker_power:.1f}/{defender_power:.1f}"
        defender.last_raid = f"defended g{defender_key}"
        event_log.append(attacker.last_raid)
        raid_log.append(attacker.last_raid)

def choose_attack_target(group: NPCGroup, world: World) -> tuple[int, int]:
    if group.storage_tiles:
        for pos in group.storage_tiles:
            if world.get_tile(pos) == "crate":
                return pos
    if group.build_origin is not None:
        return group.build_origin
    return group.camp_grid

def simulate_civ(civ: CivRegion, world: World) -> None:
    if civ.population <= 0:
        civ.wiped = True
        return
    if civ.focus_timer > 0:
        civ.focus_timer = max(0.0, civ.focus_timer - 1.0)

    if civ.project_cooldowns:
        expired = []
        for key, remaining in civ.project_cooldowns.items():
            remaining = max(0.0, remaining - 1.0)
            civ.project_cooldowns[key] = remaining
            if remaining <= 0:
                expired.append(key)
        for key in expired:
            del civ.project_cooldowns[key]

    if civ.focus_timer == 0:
        scores = environment_scores(world, civ.origin, radius=10)
        if civ.stockpile["food"] < civ.population * 2:
            civ.focus = "survival"
        elif civ.stage < 2:
            civ.focus = "growth"
        elif scores["water"] > 0.08:
            civ.focus = "trade"
        elif scores["stone"] > scores["wood"]:
            civ.focus = "industry"
        else:
            civ.focus = random.choices(
                ["growth", "industry", "trade", "fortify"],
                weights=[0.25, 0.25, 0.3, 0.2],
            )[0]
        civ.focus_timer = random.uniform(3.0, 6.0)

    def tech_defs() -> dict[str, dict[str, object]]:
        return {
            "basic_tools": {"cost": 6, "prereqs": []},
            "masonry": {"cost": 8, "prereqs": ["basic_tools"]},
            "roads": {"cost": 6, "prereqs": ["basic_tools"]},
            "waterworks": {"cost": 7, "prereqs": ["basic_tools"]},
        }

    def project_defs() -> list[dict[str, object]]:
        return [
            {"name": "build_shelter", "min_stage": 0, "max_stage": 0, "cost": {"wood": 6}, "duration": 3.0},
            {"name": "build_workbench", "min_stage": 1, "max_stage": 1, "cost": {"wood": 6}, "duration": 2.5},
            {"name": "craft_pickaxe", "min_stage": 2, "max_stage": 5, "cost": {"wood": 4}, "duration": 1.5},
            {"name": "build_crate", "min_stage": 1, "max_stage": 5, "cost": {"wood": 2}, "duration": 1.0},
            {"name": "upgrade_stone", "min_stage": 2, "max_stage": 3, "cost": {"stone": 8}, "duration": 4.0},
            {"name": "expand_base", "min_stage": 3, "max_stage": 4, "cost": {"stone": 12, "wood": 4}, "duration": 4.0},
            {"name": "build_depot", "min_stage": 2, "max_stage": 5, "cost": {"wood": 4}, "duration": 2.0},
            {"name": "build_outpost", "min_stage": 4, "max_stage": 5, "cost": {"stone": 8, "wood": 4}, "duration": 3.5},
            {"name": "build_roads", "min_stage": 2, "max_stage": 5, "cost": {"wood": 4}, "duration": 2.0},
            {"name": "build_water_post", "min_stage": 2, "max_stage": 5, "cost": {"wood": 4}, "duration": 2.0},
        ]

    def project_weight(name: str, focus: str) -> float:
        if focus == "survival":
            return 2.0 if name in {"build_crate"} else 1.0
        if focus == "growth":
            return 2.0 if name in {"build_shelter", "expand_base", "build_outpost"} else 1.0
        if focus == "industry":
            return 2.0 if name in {"craft_pickaxe", "upgrade_stone"} else 1.0
        if focus == "trade":
            return 2.0 if name in {"build_depot", "build_crate", "build_roads", "build_water_post"} else 1.0
        if focus == "fortify":
            return 2.0 if name in {"upgrade_stone", "expand_base"} else 1.0
        return 1.0

    if civ.project is None:
        candidates: list[dict[str, object]] = []
        for proj in project_defs():
            min_stage = int(proj["min_stage"])
            max_stage = int(proj["max_stage"])
            if civ.stage < min_stage or civ.stage > max_stage:
                continue
            if str(proj["name"]) in civ.project_cooldowns:
                continue
            if proj["name"] == "craft_pickaxe" and civ.tools.get("pickaxe", 0) > 0:
                continue
            if proj["name"] == "craft_pickaxe" and "basic_tools" not in civ.known_techs:
                continue
            if proj["name"] == "build_crate" and civ.crates >= 2:
                continue
            if proj["name"] == "build_roads" and civ.built_roads:
                continue
            if proj["name"] == "build_water_post" and civ.built_water_post:
                continue
            if proj["name"] == "upgrade_stone" and "masonry" not in civ.known_techs:
                continue
            if proj["name"] == "build_roads" and "roads" not in civ.known_techs:
                continue
            if proj["name"] == "build_water_post" and "waterworks" not in civ.known_techs:
                continue
            if proj["name"] == "build_water_post":
                if find_water_near(world, civ.origin, radius=10) is None:
                    continue
            candidates.append(proj)
        if candidates:
            weights = [project_weight(str(p["name"]), civ.focus) for p in candidates]
            choice = random.choices(candidates, weights=weights)[0]
            civ.project = str(choice["name"])
            civ.project_cost = dict(choice["cost"])
            civ.project_duration = float(choice["duration"])
            civ.project_progress = 0.0
            civ.project_active = False

    def allocate_workforce() -> dict[str, float]:
        weights = {"wood": 0.25, "food": 0.25, "stone": 0.2, "build": 0.2, "craft": 0.05, "research": 0.05}
        if civ.focus == "survival":
            weights.update({"food": 0.5, "wood": 0.2, "stone": 0.1, "build": 0.15, "craft": 0.03, "research": 0.02})
        elif civ.focus == "growth":
            weights.update({"wood": 0.35, "food": 0.25, "stone": 0.1, "build": 0.22, "craft": 0.05, "research": 0.03})
        elif civ.focus == "industry":
            weights.update({"wood": 0.2, "food": 0.2, "stone": 0.35, "build": 0.2, "craft": 0.05, "research": 0.0})
        elif civ.focus == "trade":
            weights.update({"wood": 0.3, "food": 0.3, "stone": 0.15, "build": 0.18, "craft": 0.05, "research": 0.02})
        elif civ.focus == "fortify":
            weights.update({"wood": 0.1, "food": 0.2, "stone": 0.4, "build": 0.25, "craft": 0.03, "research": 0.02})

        if civ.project is not None:
            needs = civ.project_cost
            if needs.get("stone", 0) > civ.stockpile["stone"]:
                weights["stone"] += 0.15
            if needs.get("wood", 0) > civ.stockpile["wood"]:
                weights["wood"] += 0.15
            weights["build"] += 0.1
        if civ.stage < 2:
            weights["research"] = 0.0
        elif civ.current_research is not None:
            weights["research"] = max(weights["research"], 0.06)

        total = sum(weights.values())
        for key in weights:
            weights[key] /= total
        return weights

    workforce = allocate_workforce()
    gather_scale = max(1, int(civ.population * 0.5))
    civ.stockpile["wood"] += int(gather_scale * workforce["wood"])
    civ.stockpile["food"] += int(gather_scale * workforce["food"])
    if civ.stage >= 2 or civ.tools.get("pickaxe", 0) > 0:
        civ.stockpile["stone"] += int(gather_scale * workforce["stone"])
        if workforce["stone"] > 0:
            civ.last_event = "gather_stone"
    elif workforce["wood"] > 0:
        civ.last_event = "gather_wood"

    food_consumption = max(1, civ.population // 3)
    civ.stockpile["food"] = max(0, civ.stockpile["food"] - food_consumption)
    if civ.stockpile["food"] == 0 and random.random() < 0.1 and civ.population > 2:
        civ.population -= 1
        civ.last_event = "population_loss"

    if civ.project is not None:
        if not civ.project_active:
            if all(civ.stockpile.get(item, 0) >= amount for item, amount in civ.project_cost.items()):
                for item, amount in civ.project_cost.items():
                    civ.stockpile[item] -= amount
                civ.project_active = True
                civ.last_event = f"start_{civ.project}"
        if civ.project_active:
            civ.project_progress += max(0.3, civ.population * workforce["build"] * 0.6)
            if civ.project_progress >= civ.project_duration:
                name = civ.project
                if name == "build_shelter":
                    civ.stage = 1
                elif name == "build_workbench":
                    civ.stage = 2
                elif name == "craft_pickaxe":
                    civ.tools["pickaxe"] = civ.tools.get("pickaxe", 0) + 1
                elif name == "build_crate":
                    civ.crates += 1
                elif name == "upgrade_stone":
                    civ.stage = 3
                elif name == "expand_base":
                    civ.stage = 4
                elif name == "build_depot":
                    civ.crates += 2
                elif name == "build_outpost":
                    civ.stage = 5
                elif name == "build_roads":
                    civ.last_event = "complete_build_roads"
                    civ.built_roads = True
                elif name == "build_water_post":
                    civ.last_event = "complete_build_water_post"
                    civ.built_water_post = True
                else:
                    civ.last_event = f"complete_{name}"
                civ.project_cooldowns[name] = 8.0
                civ.project = None
                civ.project_cost = {}
                civ.project_progress = 0.0
                civ.project_duration = 0.0
                civ.project_active = False

    if civ.stage >= 2 and random.random() < 0.2:
        trade_roll = random.random()
        if trade_roll < 0.4 and civ.stockpile["wood"] >= 2:
            civ.stockpile["wood"] -= 2
            civ.stockpile["food"] += 2
            civ.last_event = "trade_food"
        elif trade_roll < 0.8 and civ.stockpile["food"] >= 2:
            civ.stockpile["food"] -= 2
            civ.stockpile["wood"] += 2
            civ.last_event = "trade_wood"
        elif civ.stockpile["stone"] >= 2:
            civ.stockpile["stone"] -= 2
            civ.stockpile["wood"] += 1
            civ.last_event = "trade_stone"

    if civ.population < 10 and civ.stockpile["food"] > civ.population * 3 and random.random() < 0.2:
        civ.population += 1
        civ.last_event = "population_growth"

    if civ.wiped:
        civ.last_event = "wiped"

    if civ.stage >= 2:
        researchers = max(0, int(civ.population * workforce["research"]))
        civ.research_points += researchers * 0.6
        if civ.current_research is None:
            techs = tech_defs()
            candidates = []
            for tech_name, tech in techs.items():
                if tech_name in civ.known_techs:
                    continue
                prereqs = tech["prereqs"]
                if any(req not in civ.known_techs for req in prereqs):
                    continue
                candidates.append(tech_name)
            if candidates:
                if civ.focus == "industry" and "masonry" in candidates:
                    civ.current_research = "masonry"
                elif civ.focus == "trade" and "waterworks" in candidates:
                    civ.current_research = "waterworks"
                elif "basic_tools" in candidates:
                    civ.current_research = "basic_tools"
                else:
                    civ.current_research = random.choice(candidates)
        if civ.current_research is not None:
            tech = tech_defs()[civ.current_research]
            if civ.research_points >= tech["cost"]:
                civ.research_points -= tech["cost"]
                civ.known_techs.add(civ.current_research)
                civ.last_event = f"research_{civ.current_research}"
                civ.current_research = None

    if civ.stage >= 2 and random.random() < 0.35:
        if civ.stockpile["stone"] >= 1 and civ.stockpile["wood"] >= 1:
            civ.stockpile["stone"] -= 1
            civ.stockpile["wood"] -= 1
            civ.weapons["spear"] += 1
            civ.last_event = "craft_spear"
        elif civ.stockpile["wood"] >= 2:
            civ.stockpile["wood"] -= 2
            civ.weapons["club"] += 1
            civ.last_event = "craft_club"

def place_civ_layout(world: World, civ: CivRegion) -> None:
    cx, cy = civ.origin
    if civ.stage >= 1:
        min_x, max_x = cx - 3, cx + 3
        min_y, max_y = cy - 2, cy + 2
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                if world.get_tile((x, y)) in {"water", "mountain"}:
                    continue
                if x == cx and y == max_y:
                    world.set_tile((x, y), "door_closed")
                elif x == cx and y == cy - 1:
                    world.set_tile((x, y), "workbench" if civ.stage >= 2 else "floor")
                elif x == cx and y == cy:
                    world.set_tile((x, y), "crate" if civ.crates > 0 else "floor")
                elif x == min_x or x == max_x or y == min_y or y == max_y:
                    world.set_tile((x, y), "wall")
                else:
                    world.set_tile((x, y), "floor")
    if civ.stage >= 3:
        min_x, max_x = cx - 3, cx + 3
        min_y, max_y = cy - 2, cy + 2
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                if world.get_tile((x, y)) in {"water", "mountain"}:
                    continue
                if x == cx and y == max_y:
                    world.set_tile((x, y), "door_closed")
                    continue
                if x == min_x or x == max_x or y == min_y or y == max_y:
                    world.set_tile((x, y), "stone_wall")
                else:
                    world.set_tile((x, y), "stone_floor")
        world.set_tile((cx, cy), "crate" if civ.crates > 0 else "stone_floor")
        world.set_tile((cx, cy - 1), "workbench")
        if civ.crates > 1:
            extra = (cx + 1, cy)
            if world.get_tile(extra) not in {"water", "mountain"}:
                world.set_tile(extra, "crate")
        outer_min_x, outer_max_x = min_x - 1, max_x + 1
        outer_min_y, outer_max_y = min_y - 1, max_y + 1
        for y in range(outer_min_y, outer_max_y + 1):
            for x in range(outer_min_x, outer_max_x + 1):
                if min_x <= x <= max_x and min_y <= y <= max_y:
                    continue
                if world.get_tile((x, y)) in {"water", "mountain"}:
                    continue
                if x == cx and y == outer_max_y:
                    world.set_tile((x, y), "door_closed")
                    continue
                if x == outer_min_x or x == outer_max_x or y == outer_min_y or y == outer_max_y:
                    world.set_tile((x, y), "stone_wall")
                else:
                    world.set_tile((x, y), "stone_floor")
    if civ.stage >= 2:
        for offset in ((4, 0), (-4, 0), (0, 4), (0, -4)):
            ox, oy = cx + offset[0], cy + offset[1]
            if region_clear(world, (ox, oy), radius=2):
                for y in range(oy - 1, oy + 2):
                    for x in range(ox - 1, ox + 2):
                        if world.get_tile((x, y)) in {"water", "mountain"}:
                            continue
                        if x == ox and y == oy + 1:
                            world.set_tile((x, y), "door_closed")
                        elif x == ox and y == oy:
                            if civ.stage >= 3:
                                world.set_tile((x, y), "stone_floor")
                            else:
                                world.set_tile((x, y), "floor")
                        elif x == ox - 1 or x == ox + 1 or y == oy - 1 or y == oy + 1:
                            wall_tile = "stone_wall" if civ.stage >= 3 else "wall"
                            world.set_tile((x, y), wall_tile)
                        else:
                            world.set_tile((x, y), "floor")
                if civ.crates > 1:
                    crate_pos = (ox, oy)
                    world.set_tile(crate_pos, "crate")
                break
    if civ.stage >= 2:
        for offset in ((7, 0), (-7, 0), (0, 7), (0, -7)):
            ox, oy = cx + offset[0], cy + offset[1]
            if not region_clear(world, (ox, oy), radius=2):
                continue
            floor_tile = "stone_floor" if civ.stage >= 3 else "floor"
            wall_tile = "stone_wall" if civ.stage >= 3 else "wall"
            for y in range(oy - 1, oy + 2):
                for x in range(ox - 1, ox + 2):
                    if world.get_tile((x, y)) in {"water", "mountain"}:
                        continue
                    if x == ox - 1 or x == ox + 1 or y == oy - 1 or y == oy + 1:
                        world.set_tile((x, y), wall_tile)
                    else:
                        world.set_tile((x, y), floor_tile)
            crates_to_place = max(1, civ.crates)
            for i in range(min(3, crates_to_place)):
                pos = (ox, oy + i)
                if world.get_tile(pos) not in {"water", "mountain"}:
                    world.set_tile(pos, "crate")
            break

def materialize_civ(
    civ: CivRegion,
    world: World,
    npcs: list[NPC],
    npc_groups: dict[int, NPCGroup],
    npc_group_id: int,
    npc_id_counter: int,
) -> tuple[int, int]:
    place_civ_layout(world, civ)
    group_id = npc_group_id
    npc_group_id += 1
    group = NPCGroup(group_id, civ.origin)
    group.build_origin = civ.origin
    group.expanded = civ.stage >= 3
    group.stockpile = civ.stockpile.copy()
    group.tools = civ.tools.copy()
    group.weapons = civ.weapons.copy()
    npc_groups[group_id] = group
    group.build_origin = civ.origin
    for i in range(min(12, civ.population)):
        offset = pygame.Vector2(random.uniform(-10, 10), random.uniform(-10, 10))
        npcs.append(NPC(npc_id_counter, group_id, pygame.Vector2((civ.origin[0] + 0.5) * TILE_SIZE, (civ.origin[1] + 0.5) * TILE_SIZE) + offset))
        npc_id_counter += 1
    civ.materialized = True
    if civ.built_roads:
        place_path(world, civ.origin, group.camp_grid, tile="road")
    if civ.built_water_post:
        water_tile = find_water_near(world, civ.origin, radius=10)
        if water_tile is not None:
            place_water_outpost(world, civ.origin, water_tile)
    return npc_group_id, npc_id_counter

def seed_initial_civs(
    world: World,
    center: tuple[int, int],
    civ_regions: dict[tuple[int, int], CivRegion],
    count: int = 3,
) -> None:
    attempts = 0
    while len(civ_regions) < count and attempts < 80:
        attempts += 1
        dx = random.randint(-CIV_MAX_SPAWN_DIST, CIV_MAX_SPAWN_DIST)
        dy = random.randint(-CIV_MAX_SPAWN_DIST, CIV_MAX_SPAWN_DIST)
        dist = abs(dx) + abs(dy)
        if dist < CIV_MIN_SPAWN_DIST or dist > CIV_MAX_SPAWN_DIST:
            continue
        candidate = (center[0] + dx, center[1] + dy)
        region = grid_to_region(candidate)
        if region in civ_regions:
            continue
        origin = find_land_in_region(world, region)
        if origin is None:
            continue
        stage = random.choice([2, 3, 4])
        civ = CivRegion(origin)
        civ.stage = stage
        civ.population = random.randint(4, 10)
        if stage >= 2:
            civ.known_techs.add("basic_tools")
        if stage >= 3:
            civ.known_techs.add("masonry")
        if stage >= 4:
            civ.known_techs.add(random.choice(["roads", "waterworks"]))
        civ.tools["pickaxe"] = 1 if stage >= 2 else 0
        if stage >= 3:
            civ.weapons["spear"] = 2
            civ.weapons["club"] = 1
        civ.crates = 2 if stage >= 3 else 1
        civ.stockpile["wood"] = 6 + stage * 2
        civ.stockpile["food"] = 4 + stage * 2
        civ.stockpile["stone"] = 4 + stage * 3
        civ.focus = random.choice(["growth", "industry", "trade"])
        civ.last_event = "seeded"
        civ_regions[region] = civ

def seed_player_civ(
    world: World,
    center: tuple[int, int],
    civ_regions: dict[tuple[int, int], CivRegion],
) -> None:
    civ_regions.clear()
    origin = find_land_near(world, center, radius=12)
    if origin is None:
        region = grid_to_region(center)
        origin = find_land_in_region(world, region) or center
    region = grid_to_region(origin)
    civ = CivRegion(origin)
    civ.stage = 1
    civ.population = 5
    civ.stockpile["wood"] = 4
    civ.stockpile["food"] = 4
    civ.stockpile["stone"] = 0
    civ.tools["pickaxe"] = 0
    civ.crates = 1
    civ.focus = "growth"
    civ.last_event = "spawned"
    civ_regions[region] = civ
