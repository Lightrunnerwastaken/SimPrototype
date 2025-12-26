import random
import pygame

from src.constants import (
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    TILE_SIZE,
    FPS,
    COLORS,
    BUILD_ITEMS,
    DEMOLISH_REFUND,
    DEMOLISH_TIME,
    GATHER_TIME,
    CRAFT_RECIPES,
    PLAYER_HUNGER_DECAY,
    PLAYER_EAT_AMOUNT,
    PLAYER_STARVE_THRESHOLD,
    PLAYER_STARVE_DAMAGE,
    PLAYER_STARVE_COOLDOWN,
    SMELT_TIME_IRON,
    CIV_SPAWN_INTERVAL,
    CIV_TICK_INTERVAL,
    CIV_MIN_SPAWN_DIST,
    CIV_MAX_SPAWN_DIST,
    CIV_MATERIALIZE_DIST,
    CIV_MAX_REGIONS,
    WEAPON_STATS,
)
from src.camera import Camera
from src.world import World
from src.cave_world import CaveWorld
from src.entity import Player, Animal, NPC, Carcass
from src.textures import TextureAtlas
from src.vegetation import PlantManager
from src.systems.input_system import get_movement_vector
from src.systems.movement_system import move_entity
from src.systems.animal_system import update_animals, spawn_animals, spawn_cave_spiders
from src.systems.combat_system import (
    harvest_carcass,
    find_nearest_animal,
    perform_player_swing,
)
from src.systems.npc_system import (
    NPCGroup,
    update_npcs,
    stockpile_capacity,
    find_tile_in_radius,
)
from src.systems.civ_system import (
    CivRegion,
    grid_to_region,
    find_land_in_region,
    simulate_civ,
    simulate_civ_relations,
    materialize_civ,
    seed_player_civ,
    choose_attack_target,
    place_ruins,
)
from src.state import UIState, ActionState
from src.effects import HeartEffect


def can_afford(inventory: dict[str, int], cost: dict[str, int]) -> bool:
    return all(inventory.get(item, 0) >= amount for item, amount in cost.items())


def pay_cost(inventory: dict[str, int], cost: dict[str, int]) -> None:
    for item, amount in cost.items():
        inventory[item] -= amount


def refund_cost(inventory: dict[str, int], refund: dict[str, int]) -> None:
    for item, amount in refund.items():
        inventory[item] = inventory.get(item, 0) + amount


def try_gather(world: World, player: Player) -> None:
    result = world.find_resource_near(player.position, radius=1)
    if result is None:
        return
    grid_pos, tile = result
    if tile == "crate":
        world.set_tile(grid_pos, "ground")
        player.add_item("wood", 2)
        player.add_item("stone", 1)
        return
    if tile == "tree":
        world.set_tile(grid_pos, "ground")
        player.add_item("wood", 2)
    elif tile == "rock":
        world.set_tile(grid_pos, "ground")
        player.add_item("stone", 1)


def find_nearby_crate_grid(
    world: World,
    position_px: pygame.Vector2,
    radius: int = 1,
) -> tuple[int, int] | None:
    center = world.to_grid(position_px)
    for y in range(center[1] - radius, center[1] + radius + 1):
        for x in range(center[0] - radius, center[0] + radius + 1):
            if world.get_tile((x, y)) == "crate":
                return (x, y)
    return None


def transfer_item(
    source: dict[str, int],
    dest: dict[str, int],
    item: str,
    amount: int,
) -> int:
    if amount <= 0:
        return 0
    have = source.get(item, 0)
    if have <= 0:
        return 0
    moved = min(have, amount)
    source[item] = have - moved
    if source[item] <= 0:
        source.pop(item, None)
    dest[item] = dest.get(item, 0) + moved
    return moved


def issue_group_command(
    npcs: list[NPC],
    group_id: int,
    job: str,
    target_grid: tuple[int, int] | None,
    action_grid: tuple[int, int] | None = None,
    hunt_target: Animal | None = None,
    label: str | None = None,
) -> None:
    for npc in npcs:
        if npc.group_id != group_id:
            continue
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
        npc.current_command_label = label
        npc.path = []
        npc.path_index = 0
        npc.path_retries = 0
        npc.path_target = None
        npc.path_cooldown = 0.0


def issue_npc_command(
    npc: NPC,
    job: str,
    target_grid: tuple[int, int] | None,
    action_grid: tuple[int, int] | None = None,
    hunt_target: Animal | None = None,
    label: str | None = None,
) -> None:
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
    npc.current_command_label = label
    npc.path = []
    npc.path_index = 0
    npc.path_retries = 0
    npc.path_target = None
    npc.path_cooldown = 0.0


def infer_manual_command(
    world: World,
    plants: PlantManager,
    animals: list[Animal],
    mouse_world: pygame.Vector2,
) -> tuple[str, tuple[int, int] | None, tuple[int, int] | None, Animal | None, str]:
    grid_pos = world.to_grid(mouse_world)
    tile = world.get_tile(grid_pos)
    clicked_animal = next(
        (a for a in animals if a.rect.collidepoint(mouse_world)),
        None,
    )
    if clicked_animal is not None:
        return ("hunt", None, None, clicked_animal, f"Hunt {clicked_animal.species}")
    plant = plants.plants.get(grid_pos)
    if plant is not None:
        return ("gather_food", None, grid_pos, None, "Gather plant")
    if tile == "tree":
        return ("chop", None, grid_pos, None, "Chop tree")
    if tile == "rock":
        return ("mine", None, grid_pos, None, "Mine rock")
    return ("move", grid_pos, None, None, "Move")


def find_nearest_tile(
    world: World,
    center_grid: tuple[int, int],
    target: str,
    radius: int = 12,
) -> tuple[int, int] | None:
    best = None
    best_dist = None
    for y in range(center_grid[1] - radius, center_grid[1] + radius + 1):
        for x in range(center_grid[0] - radius, center_grid[0] + radius + 1):
            if world.get_tile((x, y)) != target:
                continue
            dist = abs(x - center_grid[0]) + abs(y - center_grid[1])
            if best is None or dist < best_dist:
                best = (x, y)
                best_dist = dist
    return best


def can_place_npc_build(world: World, grid_pos: tuple[int, int], build_item: str) -> bool:
    tile = world.get_tile(grid_pos)
    if build_item == "wall":
        return tile in {"ground", "floor", "sand"}
    if build_item == "stone_wall":
        return tile in {"ground", "floor", "sand", "stone_floor"}
    if build_item == "floor":
        return tile in {"ground", "sand"}
    if build_item == "stone_floor":
        return tile in {"ground", "sand", "floor"}
    if build_item == "road":
        return tile in {"ground", "sand", "floor", "stone_floor"}
    if build_item == "workbench":
        return tile == "floor"
    if build_item == "crate":
        return tile == "floor"
    if build_item == "furnace":
        return tile in {"floor", "stone_floor"}
    if build_item == "door":
        return tile in {"ground", "floor"}
    return False


def queue_build_for_npc(
    npc: NPC,
    group: NPCGroup,
    world: World,
    build_item: str,
    build_pos: tuple[int, int],
    append: bool,
) -> tuple[bool, str]:
    if not can_place_npc_build(world, build_pos, build_item):
        return False, "Can't build here"
    if not append:
        npc.command_queue.clear()
    cost = BUILD_ITEMS.get(build_item, {"wood": 2})
    missing_wood = max(0, cost.get("wood", 0) - group.stockpile.get("wood", 0))
    missing_stone = max(0, cost.get("stone", 0) - group.stockpile.get("stone", 0))
    home = group.home_grid
    tree_jobs = (missing_wood + 1) // 2
    rock_jobs = (missing_stone + 1) // 2
    for _ in range(tree_jobs):
        tree_pos = find_nearest_tile(world, home, "tree", radius=16)
        if tree_pos is None:
            break
        npc.command_queue.append(("chop", None, tree_pos, None, "Chop tree"))
        npc.command_queue.append(("haul", None, None, None, "Haul stock"))
    for _ in range(rock_jobs):
        rock_pos = find_nearest_tile(world, home, "rock", radius=16)
        if rock_pos is None:
            break
        npc.command_queue.append(("mine", None, rock_pos, None, "Mine rock"))
        npc.command_queue.append(("haul", None, None, None, "Haul stock"))
    if (build_pos, build_item) not in group.build_queue:
        group.build_queue.insert(0, (build_pos, build_item))
    npc.command_queue.append(("build", None, None, None, f"Build {build_item}"))
    if npc.job in {"idle", "wander"}:
        issue_npc_command(npc, "idle", None, None, None, None)
    return True, f"Build {build_item}"


def queue_npc_command(
    npc: NPC,
    job: str,
    target_grid: tuple[int, int] | None,
    action_grid: tuple[int, int] | None,
    hunt_target: Animal | None,
    label: str,
    append: bool,
) -> None:
    if not append:
        npc.command_queue.clear()
        issue_npc_command(npc, job, target_grid, action_grid, hunt_target, label)
        return
    npc.command_queue.append((job, target_grid, action_grid, hunt_target, label))


def queue_group_command(
    npcs: list[NPC],
    group_id: int,
    job: str,
    target_grid: tuple[int, int] | None,
    action_grid: tuple[int, int] | None,
    hunt_target: Animal | None,
    label: str,
    append: bool,
) -> None:
    for npc in npcs:
        if npc.group_id != group_id:
            continue
        if not append:
            npc.command_queue.clear()
            issue_npc_command(npc, job, target_grid, action_grid, hunt_target, label)
        else:
            npc.command_queue.append((job, target_grid, action_grid, hunt_target, label))


def can_place_building(world: World, player: Player, grid_pos: tuple[int, int], build_item: str) -> bool:
    tile = world.get_tile(grid_pos)
    if grid_pos == world.to_grid(player.position):
        return False
    if player.inventory.get(build_item, 0) <= 0:
        return False
    if build_item == "wall":
        if tile not in {"ground", "floor", "sand"}:
            return False
    elif build_item == "stone_wall":
        if tile not in {"ground", "floor", "sand", "stone_floor"}:
            return False
    elif build_item == "floor":
        if tile not in {"ground", "sand"}:
            return False
    elif build_item == "stone_floor":
        if tile not in {"ground", "sand", "floor"}:
            return False
    elif build_item == "road":
        if tile not in {"ground", "sand", "floor", "stone_floor"}:
            return False
    elif build_item == "workbench":
        if tile != "floor":
            return False
    elif build_item == "crate":
        if tile != "floor":
            return False
    elif build_item == "furnace":
        if tile not in {"floor", "stone_floor"}:
            return False
    elif build_item == "door":
        if tile not in {"ground", "floor"}:
            return False
    else:
        return False
    return True


def try_place_building(world: World, player: Player, grid_pos: tuple[int, int], build_item: str) -> None:
    if not can_place_building(world, player, grid_pos, build_item):
        return
    if build_item == "door":
        world.set_tile(grid_pos, "door_closed")
    elif build_item == "crate":
        world.set_tile(grid_pos, "crate")
    elif build_item == "furnace":
        world.set_tile(grid_pos, "furnace")
    else:
        world.set_tile(grid_pos, build_item)
    player.inventory[build_item] -= 1


def try_demolish(world: World, player: Player, grid_pos: tuple[int, int]) -> None:
    tile = world.get_tile(grid_pos)
    refund = DEMOLISH_REFUND.get(tile)
    if refund is None:
        return
    world.set_tile(grid_pos, "ground")
    refund_cost(player.inventory, refund)


def can_craft_pickaxe(world: World, player: Player) -> bool:
    if player.inventory.get("pickaxe", 0) > 0:
        return False
    if world.find_tile_near(player.position, "workbench", radius=1) is None:
        return False
    return can_afford(player.inventory, CRAFT_RECIPES["pickaxe"])


def craft_pickaxe(player: Player) -> None:
    cost = CRAFT_RECIPES["pickaxe"]
    if not can_afford(player.inventory, cost):
        return
    pay_cost(player.inventory, cost)
    player.add_item("pickaxe", 1)


def can_craft_build_item(player: Player, item: str) -> bool:
    return can_afford(player.inventory, BUILD_ITEMS[item])


def craft_build_item(player: Player, item: str) -> None:
    cost = BUILD_ITEMS[item]
    if not can_afford(player.inventory, cost):
        return
    pay_cost(player.inventory, cost)
    player.add_item(item, 1)





def find_adjacent_door(world: World, position_px: pygame.Vector2) -> tuple[tuple[int, int], str] | None:
    center = world.to_grid(position_px)
    for y in range(center[1] - 1, center[1] + 2):
        for x in range(center[0] - 1, center[0] + 2):
            tile = world.get_tile((x, y))
            if tile in {"door_closed", "door_open"}:
                return (x, y), tile
    return None












































































def format_cost(cost: dict[str, int]) -> str:
    return " ".join(f"{item}:{amount}" for item, amount in cost.items())


def missing_items(inventory: dict[str, int], cost: dict[str, int]) -> list[str]:
    missing = []
    for item, amount in cost.items():
        have = inventory.get(item, 0)
        if have < amount:
            missing.append(f"{item}:{amount - have}")
    return missing


def draw_hud(
    surface: pygame.Surface,
    font: pygame.font.Font,
    player: Player,
    build_mode: bool,
    build_item: str,
    demolish_active: bool,
    gather_active: bool,
    status_message: str | None,
    inventory_open: bool,
    group_info: str | None,
    smelt_timer: float,
    manual_npc_control: bool,
) -> None:
    pickaxe_label = "Yes" if player.inventory.get("pickaxe", 0) > 0 else "No"
    lines = [
        (
            f"Wood: {player.inventory['wood']}  Stone: {player.inventory['stone']}  "
            f"Food: {player.inventory['food']}  String: {player.inventory.get('string', 0)}  "
            f"Pickaxe: {pickaxe_label}"
        ),
        (
            f"Tab: inventory ({'open' if inventory_open else 'closed'})  "
            f"B: build mode ({'on' if build_mode else 'off'})  R: eat  F6: manual NPC"
        ),
    ]
    if build_mode:
        lines.append(f"Build: {build_item}  Owned: {player.inventory.get(build_item, 0)}")
    if demolish_active:
        lines.append("Demolish: in progress")
    if gather_active:
        lines.append("Gathering: in progress")
    if smelt_timer > 0:
        lines.append(f"Smelting iron: {smelt_timer:.1f}s")
    if manual_npc_control:
        lines.append("Manual NPC control: ON (RMB command)")
    if status_message:
        lines.append(status_message)
    if group_info:
        lines.append(group_info)

    y = 8
    for line in lines:
        text = font.render(line, True, COLORS["ui_text"])
        surface.blit(text, (8, y))
        y += text.get_height() + 4

    bar_w = 160
    bar_h = 10
    bar_x = 8
    bar_y = y + 2
    pygame.draw.rect(surface, (30, 30, 30), (bar_x, bar_y, bar_w, bar_h))
    hp_ratio = 0.0 if player.max_hp <= 0 else max(0.0, min(1.0, player.hp / player.max_hp))
    hp_fill = int(bar_w * hp_ratio)
    pygame.draw.rect(surface, (200, 80, 80), (bar_x, bar_y, hp_fill, bar_h))
    hp_label = font.render("HP", True, COLORS["ui_text"])
    surface.blit(hp_label, (bar_x + bar_w + 8, bar_y - 2))

    bar_y += bar_h + 6
    pygame.draw.rect(surface, (30, 30, 30), (bar_x, bar_y, bar_w, bar_h))
    fill_w = int(bar_w * max(0.0, min(1.0, player.hunger)))
    if player.hunger > 0.6:
        bar_color = (80, 200, 120)
    elif player.hunger > 0.3:
        bar_color = (220, 170, 90)
    else:
        bar_color = (220, 90, 90)
    pygame.draw.rect(surface, bar_color, (bar_x, bar_y, fill_w, bar_h))
    hunger_label = font.render("Hunger", True, COLORS["ui_text"])
    surface.blit(hunger_label, (bar_x + bar_w + 8, bar_y - 2))

    if build_mode:
        tag = font.render(f"BUILD MODE [{build_item}]", True, COLORS["ui_accent"])
        surface.blit(tag, (SCREEN_WIDTH - tag.get_width() - 8, 8))

    return None


def draw_inventory_panel(
    surface: pygame.Surface,
    font: pygame.font.Font,
    player: Player,
    build_item: str,
    hotbar_slots: list[str | None],
    craft_scroll: int,
    near_workbench: bool,
    near_furnace: bool,
    crate_inventory: dict[str, int] | None,
    smelt_active: bool,
) -> dict[str, object]:
    panel_w = 740
    panel_h = 420
    panel_x = 20
    panel_y = 40
    panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    panel.fill((8, 10, 14, 230))
    pygame.draw.rect(panel, (40, 50, 60), panel.get_rect(), 2)
    surface.blit(panel, panel_rect.topleft)

    title = font.render("Inventory", True, COLORS["ui_text"])
    surface.blit(title, (panel_x + 10, panel_y + 8))
    equipped_label = player.weapon or "fists"
    equip_text = font.render(f"Equipped: {equipped_label}", True, COLORS["ui_text"])
    surface.blit(equip_text, (panel_x + 160, panel_y + 10))
    equip_hint = font.render("Right click weapon to equip", True, COLORS["ui_text"])
    surface.blit(equip_hint, (panel_x + 340, panel_y + 10))

    grid_x = panel_x + 10
    grid_y = panel_y + 40
    grid_cols = 6
    grid_rows = 4
    cell = 52
    grid_w = grid_cols * cell
    grid_h = grid_rows * cell
    inventory_area = pygame.Rect(grid_x, grid_y, grid_w, grid_h)
    pygame.draw.rect(surface, (30, 35, 45), inventory_area, 1)

    inv_items = []
    build_items = ["wall", "floor", "stone_wall", "stone_floor", "road", "door", "workbench", "crate", "furnace"]
    resources = ["wood", "stone", "food", "string", "iron_ore", "iron", "pickaxe", "club", "spear"]
    display_items = build_items + resources
    for name in display_items:
        count = player.inventory.get(name, 0)
        if count <= 0:
            continue
        inv_items.append((name, count))

    inventory_rects: list[tuple[pygame.Rect, str]] = []
    for idx, (name, count) in enumerate(inv_items[: grid_cols * grid_rows]):
        cx = idx % grid_cols
        cy = idx // grid_cols
        rect = pygame.Rect(grid_x + cx * cell + 2, grid_y + cy * cell + 2, cell - 4, cell - 4)
        pygame.draw.rect(surface, (24, 28, 34), rect)
        border_color = COLORS["ui_accent"] if name == player.weapon else (60, 70, 80)
        pygame.draw.rect(surface, border_color, rect, 2 if name == player.weapon else 1)
        label = font.render(f"{name[:6]} {count}", True, COLORS["ui_text"])
        surface.blit(label, (rect.x + 4, rect.y + 4))
        inventory_rects.append((rect, name))

    hotbar_y = grid_y + grid_h + 16
    hotbar_rects: list[pygame.Rect] = []
    for i in range(5):
        rect = pygame.Rect(grid_x + i * (cell + 8), hotbar_y, cell, cell)
        pygame.draw.rect(surface, (36, 42, 50), rect)
        pygame.draw.rect(surface, (90, 100, 110), rect, 2 if build_item == hotbar_slots[i] else 1)
        label = font.render(str(i + 1), True, COLORS["ui_text"])
        surface.blit(label, (rect.x + 4, rect.y + 2))
        slot_item = hotbar_slots[i]
        if slot_item:
            item_label = font.render(slot_item[:6], True, COLORS["ui_text"])
            surface.blit(item_label, (rect.x + 4, rect.y + 20))
        hotbar_rects.append(rect)

    craft_x = panel_x + grid_w + 30
    craft_y = panel_y + 40
    craft_w = panel_w - (craft_x - panel_x) - 10
    crate_h = 0
    if crate_inventory is not None:
        crate_h = 118
    craft_h = panel_h - 60 - crate_h
    pygame.draw.rect(surface, (30, 35, 45), (craft_x, craft_y, craft_w, craft_h), 1)
    craft_title = font.render("Crafting", True, COLORS["ui_text"])
    surface.blit(craft_title, (craft_x + 6, craft_y - 22))

    craft_items: list[tuple[str, dict[str, int], str]] = []
    for option in ("wall", "floor", "stone_wall", "stone_floor", "road", "door", "workbench", "crate", "furnace"):
        craft_items.append((option, BUILD_ITEMS[option], "build"))
    if near_workbench:
        craft_items.append(("pickaxe", CRAFT_RECIPES["pickaxe"], "tool"))
        craft_items.append(("club", WEAPON_STATS["club"]["cost"], "weapon"))
        craft_items.append(("spear", WEAPON_STATS["spear"]["cost"], "weapon"))
    if near_furnace:
        craft_items.append(("iron", {"iron_ore": 1}, "smelt"))

    visible_rows = 6 if crate_inventory is not None else 7
    line_h = font.get_linesize() + 6
    max_scroll = max(0, len(craft_items) - visible_rows)
    craft_scroll = max(0, min(craft_scroll, max_scroll))
    craft_buttons: list[tuple[pygame.Rect, str, str, bool]] = []
    for idx in range(visible_rows):
        item_idx = craft_scroll + idx
        if item_idx >= len(craft_items):
            break
        name, cost, kind = craft_items[item_idx]
        missing = missing_items(player.inventory, cost)
        enabled = not missing
        if kind == "smelt" and smelt_active:
            enabled = False
        rect = pygame.Rect(craft_x + 6, craft_y + 6 + idx * line_h, craft_w - 12, line_h - 2)
        pygame.draw.rect(surface, (50, 80, 50) if enabled else (26, 28, 34), rect)
        label = f"{name}  cost {format_cost(cost)}"
        if missing:
            label += "  missing " + " ".join(missing)
        if kind == "smelt" and smelt_active:
            label += "  smelting..."
        surface.blit(font.render(label, True, COLORS["ui_text"]), (rect.x + 6, rect.y + 2))
        craft_buttons.append((rect, "craft", name, enabled))

    crate_rects: list[tuple[pygame.Rect, str]] = []
    crate_area: pygame.Rect | None = None
    if crate_inventory is not None:
        crate_x = craft_x
        crate_y = craft_y + craft_h + 24
        crate_area = pygame.Rect(crate_x, crate_y, craft_w, crate_h - 14)
        pygame.draw.rect(surface, (30, 35, 45), crate_area, 1)
        crate_title = font.render("Crate (drag to move)", True, COLORS["ui_text"])
        surface.blit(crate_title, (crate_x + 6, crate_y - 22))
        crate_cols = 4
        crate_rows = 2
        crate_cell = 44
        for idx, name in enumerate(sorted(crate_inventory.keys())):
            count = crate_inventory.get(name, 0)
            if count <= 0:
                continue
            cx = idx % crate_cols
            cy = idx // crate_cols
            if cy >= crate_rows:
                break
            rect = pygame.Rect(
                crate_x + 6 + cx * crate_cell,
                crate_y + 6 + cy * crate_cell,
                crate_cell - 6,
                crate_cell - 6,
            )
            pygame.draw.rect(surface, (24, 28, 34), rect)
            pygame.draw.rect(surface, (60, 70, 80), rect, 1)
            label = font.render(f"{name[:6]} {count}", True, COLORS["ui_text"])
            surface.blit(label, (rect.x + 3, rect.y + 3))
            crate_rects.append((rect, name))

    return {
        "panel": panel_rect,
        "inventory_area": inventory_area,
        "crate_area": crate_area,
        "inventory": inventory_rects,
        "hotbar": hotbar_rects,
        "craft": craft_buttons,
        "craft_scroll": craft_scroll,
        "crate": crate_rects,
    }


def draw_group_panel(
    surface: pygame.Surface,
    font: pygame.font.Font,
    group: NPCGroup,
    member_count: int,
    has_workbench: bool,
) -> pygame.Rect:
    cap = stockpile_capacity(group)
    needs = group.needs or {}
    needs_summary = " ".join(f"{key}:{needs.get(key, 0.0):.2f}" for key in ("food", "wood", "stone", "build", "craft"))
    items = [
        "Group Overview",
        f"Group g{group.group_id}  members {member_count}",
        f"Goal: {group.current_goal}",
        "Next: " + ", ".join(group.goals[1:3]) if len(group.goals) > 1 else "Next: -",
        "",
        f"Needs {needs_summary}".rstrip(),
        f"Stockpile wood {group.stockpile['wood']}/{cap['wood']}",
        f"Stockpile stone {group.stockpile['stone']}/{cap['stone']}",
        f"Stockpile food {group.stockpile['food']}/{cap['food']}",
        f"Crates {len(group.storage_tiles)}  Workbench {'yes' if has_workbench else 'no'}",
        f"Pickaxe {group.tools.get('pickaxe', 0)}  craftable {'yes' if has_workbench and group.stockpile['wood'] >= CRAFT_RECIPES['pickaxe']['wood'] else 'no'}",
        f"Weapons club {group.weapons.get('club', 0)} spear {group.weapons.get('spear', 0)}",
        f"Build queue {len(group.build_queue)}",
        f"Home {group.home_grid} r:{group.home_radius}",
    ]

    panel_w = 360
    line_h = font.get_linesize() + 6
    panel_h = 16 + len(items) * line_h
    panel_x = SCREEN_WIDTH - panel_w - 20
    panel_y = 20
    panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    panel.fill((8, 10, 14, 220))
    pygame.draw.rect(panel, (40, 50, 60), panel.get_rect(), 2)
    surface.blit(panel, panel_rect.topleft)

    y = panel_y + 10
    for idx, text in enumerate(items):
        color = COLORS["ui_accent"] if idx == 0 else COLORS["ui_text"]
        surface.blit(font.render(text, True, color), (panel_x + 10, y))
        y += line_h

    return panel_rect


def draw_manual_control_panel(
    surface: pygame.Surface,
    font: pygame.font.Font,
    npcs: list[NPC],
    selected_group_id: int | None,
    selected_npc_id: int | None,
    command_mode: str | None,
    build_item: str,
) -> dict[str, object]:
    members = []
    if selected_group_id is not None:
        members = [n for n in npcs if n.group_id == selected_group_id]
        members.sort(key=lambda npc: npc.npc_id)
    items = ["Manual Control"]
    items.append("LMB select NPC / group")
    items.append("RMB command, Shift+RMB queue")
    if command_mode:
        items.append(f"Mode: {command_mode}")
    if selected_group_id is None:
        items.append("No group selected")
    else:
        items.append(f"Group g{selected_group_id} members {len(members)}")
        for npc in members[:8]:
            marker = ">" if npc.npc_id == selected_npc_id else " "
            label = npc.current_command_label or npc.job
            items.append(f"{marker} NPC {npc.npc_id} {label} q:{len(npc.command_queue)}")
        if len(members) > 8:
            items.append(f"... {len(members) - 8} more")
        if selected_npc_id is not None:
            npc = next((n for n in members if n.npc_id == selected_npc_id), None)
            if npc is not None:
                items.append("")
                items.append(f"NPC {npc.npc_id} queue")
                if not npc.command_queue:
                    items.append("  (empty)")
                else:
                    for cmd in npc.command_queue[:5]:
                        items.append(f"  {cmd[4]}")
                    if len(npc.command_queue) > 5:
                        items.append(f"  ... {len(npc.command_queue) - 5} more")
    panel_w = 360
    line_h = font.get_linesize() + 5
    panel_h = 16 + len(items) * line_h + 110
    panel_x = 20
    panel_y = 20
    panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    panel.fill((8, 10, 14, 220))
    pygame.draw.rect(panel, (40, 50, 60), panel.get_rect(), 2)
    surface.blit(panel, panel_rect.topleft)

    y = panel_y + 10
    for idx, text in enumerate(items):
        color = COLORS["ui_accent"] if idx == 0 else COLORS["ui_text"]
        surface.blit(font.render(text, True, color), (panel_x + 10, y))
        y += line_h

    y += 4
    commands = [
        ("move", "Move"),
        ("chop", "Chop"),
        ("mine", "Mine"),
        ("gather_food", "Gather"),
        ("hunt", "Hunt"),
        ("build", "Build"),
    ]
    buttons: list[tuple[pygame.Rect, str]] = []
    btn_w = 100
    btn_h = 24
    for idx, (cmd, label) in enumerate(commands):
        col = idx % 3
        row = idx // 3
        rect = pygame.Rect(panel_x + 10 + col * (btn_w + 8), y + row * (btn_h + 6), btn_w, btn_h)
        active = cmd == command_mode
        pygame.draw.rect(surface, (60, 80, 100) if active else (30, 35, 45), rect)
        pygame.draw.rect(surface, (120, 140, 160), rect, 1)
        surface.blit(font.render(label, True, COLORS["ui_text"]), (rect.x + 6, rect.y + 4))
        buttons.append((rect, cmd))

    y += 2 * (btn_h + 6) + 6
    build_items = ["wall", "floor", "door", "workbench", "crate", "furnace", "stone_wall", "stone_floor", "road"]
    build_rects: list[tuple[pygame.Rect, str]] = []
    if command_mode == "build":
        surface.blit(font.render("Build:", True, COLORS["ui_text"]), (panel_x + 10, y))
        y += line_h
        for idx, name in enumerate(build_items):
            rect = pygame.Rect(panel_x + 10 + (idx % 3) * 110, y + (idx // 3) * (btn_h + 4), 104, btn_h)
            active = name == build_item
            pygame.draw.rect(surface, (70, 90, 70) if active else (26, 30, 34), rect)
            pygame.draw.rect(surface, (100, 120, 140), rect, 1)
            surface.blit(font.render(name[:10], True, COLORS["ui_text"]), (rect.x + 6, rect.y + 4))
            build_rects.append((rect, name))

    return {
        "panel": panel_rect,
        "buttons": buttons,
        "build_items": build_rects,
    }


def draw_village_debug_panel(
    surface: pygame.Surface,
    font: pygame.font.Font,
    world: World,
    npcs: list[NPC],
    groups: dict[int, NPCGroup],
    selected_group_id: int | None,
    selected_npc_id: int | None,
    npc_debug: dict[int, dict[str, str]],
) -> dict[str, object]:
    panel_w = 520
    panel_h = SCREEN_HEIGHT - 80
    panel_x = 20
    panel_y = 40
    panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    panel.fill((10, 12, 18, 235))
    pygame.draw.rect(panel, (50, 60, 75), panel.get_rect(), 2)
    surface.blit(panel, panel_rect.topleft)

    title = font.render("Village Debug", True, COLORS["ui_accent"])
    surface.blit(title, (panel_x + 10, panel_y + 8))

    list_x = panel_x + 10
    list_y = panel_y + 36
    list_w = 200
    list_h = panel_h - 46
    pygame.draw.rect(surface, (25, 30, 40), (list_x, list_y, list_w, list_h), 1)

    detail_x = list_x + list_w + 10
    detail_y = list_y
    detail_w = panel_w - (detail_x - panel_x) - 10
    detail_h = list_h
    pygame.draw.rect(surface, (25, 30, 40), (detail_x, detail_y, detail_w, detail_h), 1)

    group_entries: list[tuple[pygame.Rect, int]] = []
    npc_entries: list[tuple[pygame.Rect, int]] = []

    groups_sorted = sorted(groups.values(), key=lambda g: g.group_id)
    y = list_y + 6
    header = font.render("Groups", True, COLORS["ui_text"])
    surface.blit(header, (list_x + 6, y))
    y += font.get_linesize() + 6
    for group in groups_sorted:
        members = [n for n in npcs if n.group_id == group.group_id]
        label = f"g{group.group_id} ({len(members)}) {group.current_goal}"
        rect = pygame.Rect(list_x + 6, y, list_w - 12, font.get_linesize() + 4)
        bg = (50, 70, 90) if selected_group_id == group.group_id else (20, 25, 32)
        pygame.draw.rect(surface, bg, rect)
        surface.blit(font.render(label, True, COLORS["ui_text"]), (rect.x + 4, rect.y + 2))
        group_entries.append((rect, group.group_id))
        y += rect.height + 2

        if selected_group_id == group.group_id:
            for npc in sorted(members, key=lambda n: n.npc_id):
                hunger = npc.hunger
                npc_label = f"#{npc.npc_id} {npc.job} h:{hunger:.1f} s:{npc.satisfaction:.2f}"
                nrect = pygame.Rect(list_x + 12, y, list_w - 18, font.get_linesize() + 4)
                bg = (70, 90, 110) if selected_npc_id == npc.npc_id else (16, 20, 26)
                pygame.draw.rect(surface, bg, nrect)
                surface.blit(font.render(npc_label, True, COLORS["ui_text"]), (nrect.x + 4, nrect.y + 2))
                npc_entries.append((nrect, npc.npc_id))
                y += nrect.height + 2

    # Details panel
    dx = detail_x + 8
    dy = detail_y + 8
    if selected_group_id is not None and selected_group_id in groups:
        group = groups[selected_group_id]
        members = [n for n in npcs if n.group_id == group.group_id]
        cap = stockpile_capacity(group)
        lines = [
            f"Group g{group.group_id}",
            f"Members {len(members)}",
            f"Goal {group.current_goal}",
            "Next " + ", ".join(group.goals[1:3]) if len(group.goals) > 1 else "Next -",
        ]
        for line in lines:
            surface.blit(font.render(line, True, COLORS["ui_text"]), (dx, dy))
            dy += font.get_linesize() + 2

        needs = group.needs or {}
        needs_line = " ".join(f"{k}:{needs.get(k, 0.0):.2f}" for k in ("food", "wood", "stone", "build", "craft"))
        surface.blit(font.render(f"Needs {needs_line}", True, COLORS["ui_text"]), (dx, dy))
        dy += font.get_linesize() + 6

        stock = f"W {group.stockpile['wood']}/{cap['wood']}  S {group.stockpile['stone']}/{cap['stone']}  F {group.stockpile['food']}/{cap['food']}"
        surface.blit(font.render(stock, True, COLORS["ui_text"]), (dx, dy))
        dy += font.get_linesize() + 6

        # Mini map of home
        map_w, map_h = 15, 11
        cell = 8
        map_rect = pygame.Rect(dx, dy, map_w * cell, map_h * cell)
        pygame.draw.rect(surface, (20, 22, 28), map_rect)
        hx, hy = group.home_grid
        start_x = hx - map_w // 2
        start_y = hy - map_h // 2
        for yy in range(map_h):
            for xx in range(map_w):
                gx = start_x + xx
                gy = start_y + yy
                tile = world.get_tile((gx, gy))
                if tile == "water":
                    color = (40, 90, 140)
                elif tile == "wall" or tile == "stone_wall":
                    color = (120, 90, 65)
                elif tile in {"floor", "stone_floor"}:
                    color = (120, 110, 95)
                elif tile in {"door_closed", "door_open"}:
                    color = (170, 130, 90)
                elif tile == "workbench":
                    color = (170, 120, 80)
                elif tile == "crate":
                    color = (150, 110, 70)
                else:
                    color = (60, 90, 60)
                surface.fill(color, (map_rect.x + xx * cell, map_rect.y + yy * cell, cell, cell))
        pygame.draw.rect(surface, (60, 70, 90), map_rect, 1)
        dy += map_rect.height + 8

    if selected_npc_id is not None:
        npc = next((n for n in npcs if n.npc_id == selected_npc_id), None)
        if npc is not None:
            info = npc_debug.get(npc.npc_id, {})
            surface.blit(font.render(f"NPC #{npc.npc_id}", True, COLORS["ui_accent"]), (dx, dy))
            dy += font.get_linesize() + 4
            detail_lines = [
                f"Job {npc.job}",
                f"Hunger {npc.hunger:.2f}",
                f"Satisfaction {npc.satisfaction:.2f}",
                f"HP {npc.hp:.0f}",
                f"Task {info.get('goal', '-')}",
                f"Tgt {info.get('tgt', '-')}",
                f"Act {info.get('act', '-')}",
                f"Next {info.get('next', '-')}",
            ]
            for line in detail_lines:
                surface.blit(font.render(line, True, COLORS["ui_text"]), (dx, dy))
                dy += font.get_linesize() + 2

            bar_w = 140
            bar_h = 6
            bar_x = dx
            bar_y = dy + 2
            pygame.draw.rect(surface, (30, 30, 30), (bar_x, bar_y, bar_w, bar_h))
            fill = int(bar_w * max(0.0, min(1.0, 1.0 - npc.hunger)))
            pygame.draw.rect(surface, (220, 160, 80), (bar_x, bar_y, fill, bar_h))
    return {
        "panel": panel_rect,
        "group_entries": group_entries,
        "npc_entries": npc_entries,
    }


def draw_civ_debug_panel(
    surface: pygame.Surface,
    font: pygame.font.Font,
    event_log: list[str],
    raid_log: list[str],
) -> pygame.Rect:
    items = ["Civ Events (latest)"]
    for entry in event_log[-4:]:
        items.append(entry)
    items.append("")
    items.append("Raids (latest)")
    for entry in raid_log[-3:]:
        items.append(entry)
    panel_w = 360
    line_h = font.get_linesize() + 6
    panel_h = 16 + len(items) * line_h
    panel_x = 20
    panel_y = SCREEN_HEIGHT - panel_h - 20
    panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    panel.fill((8, 10, 14, 220))
    pygame.draw.rect(panel, (40, 50, 60), panel.get_rect(), 2)
    surface.blit(panel, panel_rect.topleft)

    y = panel_y + 10
    for idx, text in enumerate(items):
        color = COLORS["ui_accent"] if idx == 0 else COLORS["ui_text"]
        surface.blit(font.render(text, True, color), (panel_x + 10, y))
        y += line_h

    return panel_rect


def draw_minimap(
    surface: pygame.Surface,
    world: World,
    player: Player,
    camera: Camera,
    size: int,
    tile_radius: int,
) -> None:
    map_surf = pygame.Surface((size, size))
    map_surf.fill((10, 12, 16))
    center = world.to_grid(player.position)
    scale = size / (tile_radius * 2 + 1)

    for dy in range(-tile_radius, tile_radius + 1):
        for dx in range(-tile_radius, tile_radius + 1):
            gx = center[0] + dx
            gy = center[1] + dy
            tile = world.get_tile((gx, gy))
            if tile == "water":
                color = (40, 90, 140)
            elif tile == "sand":
                color = (170, 160, 120)
            elif tile == "tree":
                color = (30, 110, 40)
            elif tile == "rock":
                color = (130, 135, 145)
            elif tile == "hill":
                color = (70, 120, 70)
            elif tile == "mountain":
                color = (110, 115, 125)
            elif tile == "scree":
                color = (85, 90, 95)
            elif tile == "cave_entrance":
                color = (90, 95, 105)
            elif tile.startswith("cave_mouth"):
                color = (70, 75, 80)
            elif tile == "wall":
                color = (120, 90, 65)
            elif tile == "door_closed":
                color = (130, 95, 70)
            elif tile == "door_open":
                color = (150, 120, 90)
            elif tile == "workbench":
                color = (170, 120, 80)
            elif tile == "furnace":
                color = (140, 120, 110)
            elif tile == "floor":
                color = (140, 105, 70)
            else:
                color = (60, 90, 60)

            px = int((dx + tile_radius) * scale)
            py = int((dy + tile_radius) * scale)
            map_surf.fill(color, (px, py, int(scale) + 1, int(scale) + 1))

    player_pos = (
        int(size * 0.5),
        int(size * 0.5),
    )
    pygame.draw.circle(map_surf, (240, 220, 90), player_pos, 3)
    pygame.draw.rect(map_surf, (30, 35, 45), map_surf.get_rect(), 2)

    surface.blit(map_surf, (SCREEN_WIDTH - size - 10, SCREEN_HEIGHT - size - 10))


def draw_world_map(
    surface: pygame.Surface,
    world: World,
    player: Player,
    center: pygame.Vector2,
    size: int,
    tile_radius: int,
    civ_regions: dict[tuple[int, int], CivRegion] | None = None,
    civ_debug: bool = False,
    font: pygame.font.Font | None = None,
) -> tuple[pygame.Rect, float]:
    map_surf = pygame.Surface((size, size))
    map_surf.fill((8, 10, 14))
    scale = size / (tile_radius * 2 + 1)

    center_x = int(center.x)
    center_y = int(center.y)
    for dy in range(-tile_radius, tile_radius + 1):
        for dx in range(-tile_radius, tile_radius + 1):
            gx = center_x + dx
            gy = center_y + dy
            tile = world.get_tile((gx, gy))
            if tile == "water":
                color = (40, 90, 140)
            elif tile == "sand":
                color = (170, 160, 120)
            elif tile == "tree":
                color = (30, 110, 40)
            elif tile == "rock":
                color = (130, 135, 145)
            elif tile == "hill":
                color = (70, 120, 70)
            elif tile == "mountain":
                color = (110, 115, 125)
            elif tile == "scree":
                color = (85, 90, 95)
            elif tile == "cave_entrance":
                color = (90, 95, 105)
            elif tile.startswith("cave_mouth"):
                color = (70, 75, 80)
            elif tile == "wall":
                color = (120, 90, 65)
            elif tile == "door_closed":
                color = (130, 95, 70)
            elif tile == "door_open":
                color = (150, 120, 90)
            elif tile == "workbench":
                color = (170, 120, 80)
            elif tile == "furnace":
                color = (140, 120, 110)
            elif tile == "floor":
                color = (140, 105, 70)
            else:
                color = (60, 90, 60)

            px = int((dx + tile_radius) * scale)
            py = int((dy + tile_radius) * scale)
            map_surf.fill(color, (px, py, int(scale) + 1, int(scale) + 1))

    player_grid = world.to_grid(player.position)
    rel_x = player_grid[0] - center_x
    rel_y = player_grid[1] - center_y
    if abs(rel_x) <= tile_radius and abs(rel_y) <= tile_radius:
        px = int((rel_x + tile_radius) * scale + scale * 0.5)
        py = int((rel_y + tile_radius) * scale + scale * 0.5)
        pygame.draw.circle(map_surf, (240, 220, 90), (px, py), 4)

    if civ_regions:
        for civ in civ_regions.values():
            rel_x = civ.origin[0] - center_x
            rel_y = civ.origin[1] - center_y
            if abs(rel_x) > tile_radius or abs(rel_y) > tile_radius:
                continue
            px = int((rel_x + tile_radius) * scale + scale * 0.5)
            py = int((rel_y + tile_radius) * scale + scale * 0.5)
            if civ.materialized:
                color = (230, 210, 120)
            elif civ.stage == 0:
                color = (110, 115, 125)
            elif civ.stage == 1:
                color = (80, 140, 90)
            elif civ.stage == 2:
                color = (160, 150, 80)
            else:
                color = (190, 120, 90)
            pygame.draw.circle(map_surf, color, (px, py), 3)
            if civ_debug and font:
                proj = civ.project if civ.project else "-"
                rel = civ.war_state[0].upper()
                label = f"s{civ.stage} p{civ.population} {rel} {civ.focus} {proj} e:{civ.last_event}"
                text = font.render(label, True, (220, 220, 220))
                map_surf.blit(text, (px + 4, py - 6))

    pygame.draw.rect(map_surf, (30, 35, 45), map_surf.get_rect(), 2)
    map_size = pygame.Vector2(map_surf.get_size())
    map_pos = pygame.Vector2(
        (SCREEN_WIDTH - map_size.x) * 0.5,
        (SCREEN_HEIGHT - map_size.y) * 0.5,
    )
    surface.blit(map_surf, map_pos)

    label = "Map (M to close)"
    label_font = font or pygame.font.Font(None, 24)
    text = label_font.render(label, True, COLORS["ui_text"])
    surface.blit(text, (map_pos.x + 8, map_pos.y + 8))

    return pygame.Rect(map_pos.x, map_pos.y, map_size.x, map_size.y), scale


def draw_cave_darkness(surface: pygame.Surface, player: Player, camera: Camera) -> None:
    overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 210))
    center = (
        int(player.position.x - camera.offset.x),
        int(player.position.y - camera.offset.y),
    )
    pygame.draw.circle(overlay, (0, 0, 0, 0), center, 140)
    pygame.draw.circle(overlay, (0, 0, 0, 40), center, 200)
    surface.blit(overlay, (0, 0))



class Game:
    def run(self) -> None:
        pygame.init()
        screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("Rimworld-ish MVP (2D)")
        clock = pygame.time.Clock()
        font = pygame.font.Font(None, 24)

        overworld = World()
        player = Player(overworld.spawn_px)
        camera = Camera((SCREEN_WIDTH, SCREEN_HEIGHT), player.position)
        textures = TextureAtlas()
        ui = UIState()
        actions = ActionState()
        animals: list[Animal] = []
        animal_spawn_timer = 0.0
        cave_animals: list[Animal] = []
        cave_animal_spawn_timer = 0.0
        plants = PlantManager()
        plant_spawn_timer = 0.0
        carcasses: list[Carcass] = []
        cave_carcasses: list[Carcass] = []
        hearts: list[HeartEffect] = []
        crate_inventories: dict[tuple[int, int], dict[str, int]] = {}
        npcs: list[NPC] = []
        npc_spawn_timer = 0.0
        npc_group_id = 0
        npc_id_counter = 0
        npc_groups: dict[int, NPCGroup] = {}
        npc_debug: dict[int, dict[str, str]] = {}
        civ_regions: dict[tuple[int, int], CivRegion] = {}
        civ_relations: dict[frozenset[tuple[int, int]], str] = {}
        civ_event_log: list[str] = []
        raids: list[dict[str, object]] = []
        civ_raid_log: list[str] = []
        civ_spawn_timer = 0.0
        civ_tick_timer = 0.0
        civ_spawning_enabled = False
        in_cave = False
        cave_world: CaveWorld | None = None
        cave_return_px = pygame.Vector2(0, 0)
        cave_entry_timer = 0.0
        ui_state: dict[str, object] = {}
        debug_ui_state: dict[str, object] = {}
        manual_ui_state: dict[str, object] = {}

        seed_player_civ(overworld, overworld.to_grid(player.position), civ_regions)

        running = True
        while running:
            dt = clock.tick(FPS) / 1000.0
            ui_consumed = False
            active_crate_grid = None
            active_crate_inventory = None
            active_animals = cave_animals if in_cave else animals
            active_carcasses = cave_carcasses if in_cave else carcasses
            if ui.inventory_open and not in_cave:
                active_crate_grid = find_nearby_crate_grid(overworld, player.position, radius=1)
                if active_crate_grid is not None:
                    active_crate_inventory = crate_inventories.setdefault(active_crate_grid, {})

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_b:
                        if not in_cave:
                            ui.build_mode = not ui.build_mode
                    elif event.key == pygame.K_f:
                        if in_cave:
                            if cave_entry_timer == 0 and cave_world and cave_world.tile_at_px(player.position) == "cave_exit":
                                in_cave = False
                                cave_world = None
                                player.position = pygame.Vector2(cave_return_px)
                                camera.position = pygame.Vector2(player.position)
                        else:
                            if overworld.tile_at_px(player.position) == "cave_entrance":
                                cave_return_px = pygame.Vector2(player.position)
                                entrance_grid = overworld.to_grid(player.position)
                                cave_seed = (
                                    overworld.seed
                                    ^ (entrance_grid[0] * 92837111 + entrance_grid[1] * 689287499)
                                ) & 0xFFFFFFFF
                                cave_world = CaveWorld(cave_seed, exit_grid=(0, 1))
                                in_cave = True
                                player.position = pygame.Vector2(TILE_SIZE * 0.5, TILE_SIZE * 1.5)
                                camera.position = pygame.Vector2(player.position)
                                cave_entry_timer = 0.6
                                actions.gather_target = None
                                actions.gather_tile = None
                                actions.gather_timer = 0.0
                                ui.build_mode = False
                                ui.inventory_open = False
                                ui.map_open = False
                    elif event.key == pygame.K_m:
                        if not in_cave:
                            ui.map_open = not ui.map_open
                            if ui.map_open:
                                gx, gy = overworld.to_grid(player.position)
                                ui.map_center = pygame.Vector2(gx, gy)
                            ui.map_dragging = False
                    elif event.key == pygame.K_TAB:
                        if not in_cave:
                            ui.inventory_open = not ui.inventory_open
                    elif event.key == pygame.K_F3:
                        ui.debug_view = not ui.debug_view
                    elif event.key == pygame.K_F4:
                        ui.npc_debug_view = not ui.npc_debug_view
                    elif event.key == pygame.K_F5:
                        ui.civ_debug_view = not ui.civ_debug_view
                    elif event.key == pygame.K_F6:
                        ui.manual_npc_control = not ui.manual_npc_control
                        if ui.manual_npc_control:
                            for npc in npcs:
                                npc.job = "idle"
                                npc.job_lock_timer = 0.0
                                npc.task_timer = 0.0
                                npc.task_key = None
                                npc.task_commit_timer = 0.0
                                npc.target_grid = None
                                npc.action_grid = None
                                npc.hunt_target = None
                                npc.eat_target = None
                                npc.path = []
                                npc.path_index = 0
                                npc.path_retries = 0
                                npc.path_target = None
                                npc.path_cooldown = 0.0
                                npc.command_queue.clear()
                                npc.current_command_label = None
                    elif event.key in (pygame.K_EQUALS, pygame.K_KP_PLUS):
                        ui.minimap_zoom = min(3, ui.minimap_zoom + 1)
                    elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                        ui.minimap_zoom = max(1, ui.minimap_zoom - 1)
                    elif ui.map_open and event.key == pygame.K_ESCAPE:
                        ui.map_open = False
                    if ui.map_open:
                        continue
                    elif event.key == pygame.K_e:
                        if actions.gather_target is None:
                            if in_cave and cave_world:
                                result = cave_world.find_resource_near(player.position, radius=1)
                                if result is None:
                                    actions.status_message = "No resource nearby"
                                    actions.status_timer = 1.2
                                else:
                                    grid_pos, tile = result
                                    if tile == "iron_ore" and player.inventory.get("pickaxe", 0) <= 0:
                                        actions.status_message = "Need pickaxe to mine ore"
                                        actions.status_timer = 1.5
                                    else:
                                        actions.gather_target = grid_pos
                                        actions.gather_tile = tile
                                        actions.gather_timer = 0.0
                            else:
                                door = find_adjacent_door(overworld, player.position)
                                if door is not None:
                                    door_pos, door_tile = door
                                    if door_tile == "door_closed":
                                        overworld.set_tile(door_pos, "door_open")
                                    else:
                                        overworld.set_tile(door_pos, "door_closed")
                                    continue
                                if harvest_carcass(player, active_carcasses):
                                    actions.status_message = "Harvested meat"
                                    actions.status_timer = 1.0
                                    continue
                                result = overworld.find_resource_near(player.position, radius=1)
                                if result is None:
                                    actions.status_message = "No resource nearby"
                                    actions.status_timer = 1.2
                                else:
                                    grid_pos, tile = result
                                    if tile == "rock" and player.inventory.get("pickaxe", 0) <= 0:
                                        actions.status_message = "Need pickaxe to mine rock"
                                        actions.status_timer = 1.5
                                    else:
                                        actions.gather_target = grid_pos
                                        actions.gather_tile = tile
                                        actions.gather_timer = 0.0
                    elif event.key == pygame.K_c:
                        if in_cave:
                            continue
                        if player.inventory.get("pickaxe", 0) > 0:
                            actions.status_message = "Pickaxe already crafted"
                            actions.status_timer = 1.2
                        elif can_craft_pickaxe(overworld, player):
                            craft_pickaxe(player)
                        else:
                            actions.status_message = "Need workbench + wood:4"
                            actions.status_timer = 1.2
                    elif event.key == pygame.K_r:
                        if player.inventory.get("food", 0) <= 0:
                            actions.status_message = "No food to eat"
                            actions.status_timer = 1.2
                        elif player.hunger >= 0.99:
                            actions.status_message = "Already full"
                            actions.status_timer = 1.0
                        else:
                            player.inventory["food"] -= 1
                            player.hunger = min(1.0, player.hunger + PLAYER_EAT_AMOUNT)
                            actions.status_message = "Ate food"
                            actions.status_timer = 1.0
                    elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5):
                        idx = event.key - pygame.K_1
                        if 0 <= idx < len(ui.hotbar_slots) and ui.hotbar_slots[idx]:
                            ui.build_item = ui.hotbar_slots[idx]
                            if not ui.build_mode:
                                ui.build_mode = True
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if ui.map_open:
                        if event.button == 1 and ui.map_rect.collidepoint(event.pos):
                            ui.map_dragging = True
                            ui.map_last_mouse = pygame.Vector2(event.pos)
                        continue
                    if ui.npc_debug_view and debug_ui_state.get("panel") and debug_ui_state["panel"].collidepoint(event.pos):
                        for rect, gid in debug_ui_state.get("group_entries", []):
                            if rect.collidepoint(event.pos):
                                ui.selected_group_id = gid
                                ui.selected_npc_id = None
                                ui_consumed = True
                                break
                        if not ui_consumed:
                            for rect, nid in debug_ui_state.get("npc_entries", []):
                                if rect.collidepoint(event.pos):
                                    ui.selected_npc_id = nid
                                    ui_consumed = True
                                    break
                        if ui_consumed:
                            continue
                    if ui.inventory_open and event.button == 1:
                        if ui_state.get("panel") and ui_state["panel"].collidepoint(event.pos):
                            if not ui_consumed:
                                for rect, name in ui_state.get("inventory", []):
                                    if rect.collidepoint(event.pos):
                                        ui.dragging_item = ("inventory", name)
                                        ui_consumed = True
                                        break
                            if not ui_consumed and active_crate_inventory is not None:
                                for rect, name in ui_state.get("crate", []):
                                    if rect.collidepoint(event.pos):
                                        ui.dragging_item = ("crate", name)
                                        ui_consumed = True
                                        break
                            if not ui_consumed:
                                for rect, action, value, enabled in ui_state.get("craft", []):
                                    if rect.collidepoint(event.pos):
                                        if enabled:
                                            if value in BUILD_ITEMS:
                                                craft_build_item(player, value)
                                                ui.build_item = value
                                                ui.build_mode = True
                                            elif value == "pickaxe":
                                                craft_pickaxe(player)
                                            elif value in WEAPON_STATS:
                                                cost = WEAPON_STATS[value]["cost"]
                                                if can_afford(player.inventory, cost):
                                                    pay_cost(player.inventory, cost)
                                                    player.add_item(value, 1)
                                            elif value == "iron":
                                                cost = {"iron_ore": 1}
                                                if actions.smelt_timer > 0:
                                                    actions.status_message = "Furnace busy"
                                                    actions.status_timer = 1.0
                                                elif can_afford(player.inventory, cost):
                                                    pay_cost(player.inventory, cost)
                                                    actions.smelt_timer = SMELT_TIME_IRON
                                        else:
                                            actions.status_message = "Not enough resources"
                                            actions.status_timer = 1.2
                                        ui_consumed = True
                                        break
                        if ui.inventory_open:
                            continue
                    if ui.inventory_open and event.button == 3:
                        if ui_state.get("panel") and ui_state["panel"].collidepoint(event.pos):
                            for rect, name in ui_state.get("inventory", []):
                                if rect.collidepoint(event.pos) and name in WEAPON_STATS:
                                    player.weapon = None if player.weapon == name else name
                                    ui_consumed = True
                                    break
                        if ui.inventory_open:
                            continue
                    if event.button == 1 and not ui.inventory_open:
                        mouse_world = camera.screen_to_world(pygame.Vector2(event.pos))
                        clicked_group = None
                        clicked_npc = None
                        for npc in npcs:
                            if npc.rect.collidepoint(mouse_world):
                                clicked_group = npc.group_id
                                clicked_npc = npc
                                break
                        if clicked_group is None and ui.group_panel_rect.collidepoint(event.pos):
                            clicked_group = ui.selected_group_id
                        ui.selected_group_id = clicked_group
                        if clicked_npc is not None:
                            ui.selected_npc_id = clicked_npc.npc_id
                        elif not ui.npc_debug_view:
                            ui.selected_npc_id = None
                        if clicked_group is None and not ui.build_mode:
                            attacked = perform_player_swing(
                                player,
                                active_animals,
                                active_carcasses,
                                mouse_world,
                            )
                            if attacked:
                                actions.status_message = "Attack"
                                actions.status_timer = 0.4
                    if ui.inventory_open:
                        continue
                    if ui_consumed:
                        continue
                    if ui.manual_npc_control and event.button == 1:
                        panel = manual_ui_state.get("panel")
                        if panel is not None and panel.collidepoint(event.pos):
                            for rect, cmd in manual_ui_state.get("buttons", []):
                                if rect.collidepoint(event.pos):
                                    ui.manual_command_mode = cmd
                                    ui_consumed = True
                                    break
                            if not ui_consumed and ui.manual_command_mode == "build":
                                for rect, name in manual_ui_state.get("build_items", []):
                                    if rect.collidepoint(event.pos):
                                        ui.manual_build_item = name
                                        ui_consumed = True
                                        break
                            if ui_consumed:
                                continue
                    if event.button == 3 and ui.manual_npc_control and not ui.build_mode and not in_cave:
                        append_command = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
                        selected_npc = None
                        if ui.selected_npc_id is not None:
                            selected_npc = next((n for n in npcs if n.npc_id == ui.selected_npc_id), None)
                            if selected_npc is None:
                                ui.selected_npc_id = None
                        if selected_npc is None and ui.selected_group_id is None:
                            actions.status_message = "Select a group or NPC"
                            actions.status_timer = 1.2
                        else:
                            mouse_world = camera.screen_to_world(pygame.Vector2(event.pos))
                            if ui.manual_command_mode:
                                mode = ui.manual_command_mode
                                grid_pos = overworld.to_grid(mouse_world)
                                tile = overworld.get_tile(grid_pos)
                                command_job = mode
                                command_label = mode
                                target_grid = None
                                action_grid = None
                                hunt_target = None
                                if mode == "move":
                                    target_grid = grid_pos
                                    command_label = "Move"
                                elif mode == "chop":
                                    if tile != "tree":
                                        actions.status_message = "Target a tree"
                                        actions.status_timer = 1.0
                                        ui_consumed = True
                                        continue
                                    action_grid = grid_pos
                                    command_label = "Chop tree"
                                elif mode == "mine":
                                    if tile != "rock":
                                        actions.status_message = "Target a rock"
                                        actions.status_timer = 1.0
                                        ui_consumed = True
                                        continue
                                    action_grid = grid_pos
                                    command_label = "Mine rock"
                                elif mode == "gather_food":
                                    if grid_pos not in plants.plants:
                                        actions.status_message = "Target a plant"
                                        actions.status_timer = 1.0
                                        ui_consumed = True
                                        continue
                                    action_grid = grid_pos
                                    command_label = "Gather plant"
                                elif mode == "hunt":
                                    hunt_target = next((a for a in animals if a.rect.collidepoint(mouse_world)), None)
                                    if hunt_target is None:
                                        actions.status_message = "Target an animal"
                                        actions.status_timer = 1.0
                                        ui_consumed = True
                                        continue
                                    command_label = f"Hunt {hunt_target.species}"
                                elif mode == "build":
                                    build_item = ui.manual_build_item
                                    if selected_npc is None:
                                        leader = next((n for n in npcs if n.group_id == ui.selected_group_id and n.leader), None)
                                        selected_npc = leader
                                    if selected_npc is None:
                                        actions.status_message = "Select an NPC"
                                        actions.status_timer = 1.0
                                        ui_consumed = True
                                        continue
                                    group = npc_groups.get(selected_npc.group_id)
                                    if group is None:
                                        actions.status_message = "No group"
                                        actions.status_timer = 1.0
                                        ui_consumed = True
                                        continue
                                    ok, msg = queue_build_for_npc(
                                        selected_npc,
                                        group,
                                        overworld,
                                        build_item,
                                        grid_pos,
                                        append_command,
                                    )
                                    actions.status_message = f"NPC: {msg}"
                                    actions.status_timer = 1.0
                                    ui_consumed = True
                                    continue
                                if selected_npc is not None:
                                    queue_npc_command(
                                        selected_npc,
                                        command_job,
                                        target_grid,
                                        action_grid,
                                        hunt_target,
                                        command_label,
                                        append_command,
                                    )
                                    actions.status_message = f"NPC: {command_label}"
                                else:
                                    queue_group_command(
                                        npcs,
                                        ui.selected_group_id,
                                        command_job,
                                        target_grid,
                                        action_grid,
                                        hunt_target,
                                        command_label,
                                        append_command,
                                    )
                                    actions.status_message = f"Group: {command_label}"
                            else:
                                job, target_grid, action_grid, hunt_target, label = infer_manual_command(
                                    overworld,
                                    plants,
                                    animals,
                                    mouse_world,
                                )
                                if selected_npc is not None:
                                    queue_npc_command(
                                        selected_npc,
                                        job,
                                        target_grid,
                                        action_grid,
                                        hunt_target,
                                        label,
                                        append_command,
                                    )
                                    actions.status_message = f"NPC: {label}"
                                else:
                                    queue_group_command(
                                        npcs,
                                        ui.selected_group_id,
                                        job,
                                        target_grid,
                                        action_grid,
                                        hunt_target,
                                        label,
                                        append_command,
                                    )
                                    actions.status_message = f"Group: {label}"
                            actions.status_timer = 0.8
                        ui_consumed = True
                    if ui_consumed:
                        continue
                    if event.button == 1 and ui.build_mode and not in_cave:
                        mouse_world = camera.screen_to_world(pygame.Vector2(pygame.mouse.get_pos()))
                        grid_pos = overworld.to_grid(mouse_world)
                        try_place_building(overworld, player, grid_pos, ui.build_item)
                        if ui.build_item == "crate" and overworld.get_tile(grid_pos) == "crate":
                            crate_inventories.setdefault(grid_pos, {})
                    elif event.button == 3 and ui.build_mode and not in_cave:
                        mouse_world = camera.screen_to_world(pygame.Vector2(pygame.mouse.get_pos()))
                        grid_pos = overworld.to_grid(mouse_world)
                        tile = overworld.get_tile(grid_pos)
                        if tile in DEMOLISH_REFUND:
                            actions.demolish_target = grid_pos
                            actions.demolish_timer = 0.0
                            actions.demolish_tile = tile
                elif event.type == pygame.MOUSEBUTTONUP:
                    if ui.inventory_open and event.button == 1 and ui.dragging_item:
                        source, name = ui.dragging_item
                        for idx, rect in enumerate(ui_state.get("hotbar", [])):
                            if rect.collidepoint(event.pos):
                                if source == "inventory" and name in BUILD_ITEMS:
                                    ui.hotbar_slots[idx] = name
                                ui.dragging_item = None
                                ui_consumed = True
                                break
                        if ui.dragging_item and active_crate_inventory is not None:
                            crate_area = ui_state.get("crate_area")
                            if crate_area and crate_area.collidepoint(event.pos):
                                if source == "inventory":
                                    transfer_item(
                                        player.inventory,
                                        active_crate_inventory,
                                        name,
                                        player.inventory.get(name, 0),
                                    )
                                    ui.dragging_item = None
                                    ui_consumed = True
                            inv_area = ui_state.get("inventory_area")
                            if ui.dragging_item and inv_area and inv_area.collidepoint(event.pos):
                                if source == "crate":
                                    transfer_item(
                                        active_crate_inventory,
                                        player.inventory,
                                        name,
                                        active_crate_inventory.get(name, 0),
                                    )
                                    ui.dragging_item = None
                                    ui_consumed = True
                        if ui.dragging_item and ui_state.get("panel") and not ui_state["panel"].collidepoint(event.pos):
                            ui.dragging_item = None
                    if ui.map_open and event.button == 1:
                        ui.map_dragging = False
                elif event.type == pygame.MOUSEMOTION:
                    if ui.map_open and ui.map_dragging:
                        delta = pygame.Vector2(event.pos) - ui.map_last_mouse
                        ui.map_last_mouse = pygame.Vector2(event.pos)
                        if ui.map_scale > 0:
                            ui.map_center.x -= delta.x / ui.map_scale
                            ui.map_center.y -= delta.y / ui.map_scale
                elif event.type == pygame.MOUSEWHEEL:
                    if ui.inventory_open:
                        ui.crafting_scroll = max(0, ui.crafting_scroll - event.y)

            current_world = cave_world if in_cave else overworld
            move_dir = get_movement_vector() if not ui.map_open else pygame.Vector2(0, 0)
            move_entity(player, move_dir, dt, current_world)
            camera.update(player.position, dt)
            if player.attack_cooldown > 0:
                player.attack_cooldown = max(0.0, player.attack_cooldown - dt)
            if player.attack_timer > 0:
                player.attack_timer = max(0.0, player.attack_timer - dt)
            if player.damage_cooldown > 0:
                player.damage_cooldown = max(0.0, player.damage_cooldown - dt)
            if player.weapon and player.inventory.get(player.weapon, 0) <= 0:
                player.weapon = None
            player.hunger = max(0.0, player.hunger - dt * PLAYER_HUNGER_DECAY)

            if in_cave and cave_entry_timer > 0:
                cave_entry_timer = max(0.0, cave_entry_timer - dt)

            if actions.status_timer > 0:
                actions.status_timer = max(0.0, actions.status_timer - dt)
                if actions.status_timer == 0:
                    actions.status_message = None

            if actions.status_message is None:
                if not in_cave and overworld.tile_at_px(player.position) == "cave_entrance":
                    actions.status_message = "Press F to enter cave"
                    actions.status_timer = 0.1
                elif in_cave and cave_world and cave_entry_timer == 0 and cave_world.tile_at_px(player.position) == "cave_exit":
                    actions.status_message = "Press F to leave cave"
                    actions.status_timer = 0.1
            if actions.smelt_timer > 0:
                actions.smelt_timer = max(0.0, actions.smelt_timer - dt)
                if actions.smelt_timer == 0:
                    player.add_item("iron", 1)
                    actions.status_message = "Iron smelted"
                    actions.status_timer = 1.0

            if not ui.map_open and not in_cave:
                animal_spawn_timer += dt
                if animal_spawn_timer >= 2.0:
                    animal_spawn_timer = 0.0
                    animals = [
                        a for a in animals if (a.position - player.position).length() < TILE_SIZE * 50
                    ]
                    spawn_animals(animals, player, overworld, "deer", 3)
                    spawn_animals(animals, player, overworld, "rabbit", 3)
                    spawn_animals(animals, player, overworld, "wolf", 3)
                update_animals(animals, player, overworld, plants, carcasses, hearts, dt)
                if player.hunger <= PLAYER_STARVE_THRESHOLD and player.hp > 0:
                    nearest_wolf = find_nearest_animal(
                        [a for a in animals if a.species == "wolf"],
                        player.position,
                        TILE_SIZE * 1.1,
                    )
                    if nearest_wolf is not None and player.damage_cooldown <= 0:
                        player.hp = max(0.0, player.hp - PLAYER_STARVE_DAMAGE)
                        player.damage_cooldown = PLAYER_STARVE_COOLDOWN
                        if player.hp == 0:
                            actions.status_message = "You died"
                            actions.status_timer = 2.0
            if not ui.map_open and in_cave and cave_world:
                cave_animal_spawn_timer += dt
                if cave_animal_spawn_timer >= 2.4:
                    cave_animal_spawn_timer = 0.0
                    cave_animals = [
                        a for a in cave_animals if (a.position - player.position).length() < TILE_SIZE * 40
                    ]
                    spawn_cave_spiders(cave_animals, player, cave_world, 4)
                update_animals(cave_animals, player, cave_world, plants, cave_carcasses, hearts, dt)

            if not ui.map_open and not in_cave:
                plant_spawn_timer += dt
                if plant_spawn_timer >= 4.0:
                    plant_spawn_timer = 0.0
                    center = overworld.to_grid(player.position)
                    plants.try_spawn(
                        overworld,
                        center,
                        radius=22,
                        attempts=14,
                        kinds=["grass_a", "grass_b", "berry", "flower", "young_tree"],
                    )
                plants.update(dt, max_updates=30)

                if civ_spawning_enabled:
                    civ_spawn_timer += dt
                    if civ_spawn_timer >= CIV_SPAWN_INTERVAL:
                        civ_spawn_timer = 0.0
                        if len(civ_regions) < CIV_MAX_REGIONS:
                            center = overworld.to_grid(player.position)
                            for _ in range(12):
                                dx = random.randint(-CIV_MAX_SPAWN_DIST, CIV_MAX_SPAWN_DIST)
                                dy = random.randint(-CIV_MAX_SPAWN_DIST, CIV_MAX_SPAWN_DIST)
                                dist = abs(dx) + abs(dy)
                                if dist < CIV_MIN_SPAWN_DIST or dist > CIV_MAX_SPAWN_DIST:
                                    continue
                                candidate = (center[0] + dx, center[1] + dy)
                                region = grid_to_region(candidate)
                                if region in civ_regions:
                                    continue
                                origin = find_land_in_region(overworld, region)
                                if origin is None:
                                    continue
                                civ_regions[region] = CivRegion(origin)
                                break

                civ_tick_timer += dt
                if civ_tick_timer >= CIV_TICK_INTERVAL:
                    civ_tick_timer = 0.0
                    for civ in civ_regions.values():
                        if civ.materialized:
                            continue
                        simulate_civ(civ, overworld)
                    simulate_civ_relations(civ_regions, civ_relations, civ_event_log, raids, civ_raid_log)
                    if len(civ_event_log) > 24:
                        civ_event_log[:] = civ_event_log[-24:]
                    if len(civ_raid_log) > 24:
                        civ_raid_log[:] = civ_raid_log[-24:]

                center = overworld.to_grid(player.position)
                for civ in civ_regions.values():
                    if civ.materialized:
                        continue
                    dist = abs(civ.origin[0] - center[0]) + abs(civ.origin[1] - center[1])
                    if dist <= CIV_MATERIALIZE_DIST:
                        npc_group_id, npc_id_counter = materialize_civ(
                            civ,
                            overworld,
                            npcs,
                            npc_groups,
                            npc_group_id,
                            npc_id_counter,
                        )
                for civ_key, civ in list(civ_regions.items()):
                    if not civ.materialized:
                        continue
                    for group_id, group in npc_groups.items():
                        if group.build_origin == civ.origin:
                            member_count = len([n for n in npcs if n.group_id == group_id])
                            if member_count <= 0:
                                civ.last_event = "wiped"
                                civ.materialized = False
                                civ.population = 0
                                civ.wiped = True
                                place_ruins(overworld, civ.origin)
                                civ_regions.pop(civ_key, None)
                            break

                for civ_key, civ in list(civ_regions.items()):
                    if civ.wiped and not civ.materialized:
                        place_ruins(overworld, civ.origin)
                        civ_regions.pop(civ_key, None)

                for raid in list(raids):
                    if raid.get("spawned"):
                        if raid.get("completed"):
                            continue
                        if raid.get("group_id") is None or raid.get("defender_group_id") is None:
                            raid["completed"] = True
                            continue
                        raider_group = npc_groups.get(raid["group_id"])
                        defender_group = npc_groups.get(raid["defender_group_id"])
                        if raider_group is None or defender_group is None:
                            raid["completed"] = True
                            continue
                        raiders = [n for n in npcs if n.group_id == raid["group_id"] and n.hp > 0]
                        defenders = [n for n in npcs if n.group_id == raid["defender_group_id"] and n.hp > 0]
                        if not defenders:
                            raid["phase"] = "loot"
                        if not raiders:
                            raid["completed"] = True
                            continue
                        target = choose_attack_target(defender_group, overworld)
                        for npc in npcs:
                            if npc.group_id != raid["group_id"]:
                                continue
                            if npc.hp <= 0:
                                continue
                            npc.target_grid = target
                            npc.action_grid = target
                        if raid.get("phase") == "loot":
                            if not raid.get("loot_applied"):
                                loot_amount = int(raid.get("loot", 0))
                                defender_group.stockpile["food"] = max(0, defender_group.stockpile["food"] - loot_amount)
                                raider_group.stockpile["food"] += loot_amount
                                raid["loot_applied"] = True
                            raid["phase"] = "retreat"
                        if raid.get("phase") == "retreat":
                            for npc in raiders:
                                npc.target_grid = raid["start"]
                                npc.action_grid = raid["start"]
                            if all(
                                abs(overworld.to_grid(n.position)[0] - raid["start"][0]) + abs(overworld.to_grid(n.position)[1] - raid["start"][1]) < 2
                                for n in raiders
                            ):
                                raid["completed"] = True
                        continue
                if raids:
                    raids[:] = [r for r in raids if not r.get("completed")]
                    target = raid["target"]
                    dist = abs(target[0] - center[0]) + abs(target[1] - center[1])
                    if dist > CIV_MATERIALIZE_DIST:
                        continue
                    raid["spawned"] = True
                    group_id = npc_group_id
                    npc_group_id += 1
                    group = NPCGroup(group_id, raid["start"])
                    group.build_origin = raid["start"]
                    group.is_raider = True
                    group.stockpile = {"wood": 0, "stone": 0, "food": 0}
                    group.tools["pickaxe"] = 0
                    group.weapons["spear"] = 2
                    group.weapons["club"] = 1
                    npc_groups[group_id] = group
                    target_group_id = None
                    nearest_dist = None
                    for gid, g in npc_groups.items():
                        if gid == group_id:
                            continue
                        home = g.build_origin or g.camp_grid
                        d = abs(home[0] - target[0]) + abs(home[1] - target[1])
                        if nearest_dist is None or d < nearest_dist:
                            target_group_id = gid
                            nearest_dist = d
                    raid["defender_group_id"] = target_group_id
                    for _i in range(raid["size"]):
                        offset = pygame.Vector2(random.uniform(-10, 10), random.uniform(-10, 10))
                        npc = NPC(npc_id_counter, group_id, pygame.Vector2((raid["start"][0] + 0.5) * TILE_SIZE, (raid["start"][1] + 0.5) * TILE_SIZE) + offset)
                        npc.job = "raid"
                        npcs.append(npc)
                        npc_id_counter += 1
                    raid["group_id"] = group_id
                    defender_group = npc_groups.get(raid.get("defender_group_id"))
                    if defender_group is None:
                        raid["completed"] = True

                npc_debug.clear()
                update_npcs(
                    npcs,
                    npc_groups,
                    overworld,
                    plants,
                    animals,
                    carcasses,
                    dt,
                    ui.manual_npc_control,
                    raids,
                    npc_debug if ui.npc_debug_view else None,
                )
                npcs = [n for n in npcs if n.hp > 0]
                for group_id, group in list(npc_groups.items()):
                    members = [n for n in npcs if n.group_id == group_id]
                    if not members:
                        del npc_groups[group_id]

            if actions.gather_target is not None and actions.gather_tile is not None:
                if move_dir.length_squared() > 0:
                    actions.gather_target = None
                    actions.gather_tile = None
                    actions.gather_timer = 0.0
                else:
                    gather_world = cave_world if in_cave else overworld
                    if gather_world is None:
                        actions.gather_target = None
                        actions.gather_tile = None
                        actions.gather_timer = 0.0
                    else:
                        target_center = pygame.Vector2(
                            (actions.gather_target[0] + 0.5) * TILE_SIZE,
                            (actions.gather_target[1] + 0.5) * TILE_SIZE,
                        )
                        if player.position.distance_to(target_center) > TILE_SIZE * 1.5:
                            actions.gather_target = None
                            actions.gather_tile = None
                            actions.gather_timer = 0.0
                        elif gather_world.get_tile(actions.gather_target) != actions.gather_tile:
                            actions.gather_target = None
                            actions.gather_tile = None
                            actions.gather_timer = 0.0
                        else:
                            actions.gather_timer += dt
                            if actions.gather_timer >= GATHER_TIME[actions.gather_tile]:
                                if actions.gather_tile == "tree":
                                    gather_world.set_tile(actions.gather_target, "ground")
                                    player.add_item("wood", 2)
                                elif actions.gather_tile == "rock":
                                    gather_world.set_tile(actions.gather_target, "ground")
                                    player.add_item("stone", 1)
                                elif actions.gather_tile == "crate":
                                    gather_world.set_tile(actions.gather_target, "ground")
                                    player.add_item("wood", 2)
                                    player.add_item("stone", 1)
                                    crate_inventory = crate_inventories.pop(actions.gather_target, {})
                                    for name, count in crate_inventory.items():
                                        if count > 0:
                                            player.add_item(name, count)
                                elif actions.gather_tile == "iron_ore":
                                    gather_world.set_tile(actions.gather_target, "cave_floor")
                                    player.add_item("iron_ore", 1)
                                actions.gather_target = None
                                actions.gather_tile = None
                                actions.gather_timer = 0.0

            if actions.demolish_target is not None and not in_cave:
                if not ui.build_mode:
                    actions.demolish_target = None
                    actions.demolish_tile = None
                else:
                    tile = overworld.get_tile(actions.demolish_target)
                    if tile not in DEMOLISH_REFUND:
                        actions.demolish_target = None
                        actions.demolish_tile = None
                    else:
                        actions.demolish_timer += dt
                        if actions.demolish_timer >= DEMOLISH_TIME:
                            if actions.demolish_tile == "crate":
                                crate_inventory = crate_inventories.pop(actions.demolish_target, {})
                                for name, count in crate_inventory.items():
                                    if count > 0:
                                        player.add_item(name, count)
                            try_demolish(overworld, player, actions.demolish_target)
                            actions.demolish_target = None
                            actions.demolish_tile = None

            screen.fill(COLORS["bg"])
            if in_cave:
                cave_world.draw(screen, camera, textures)
                for animal in active_animals:
                    animal.draw(screen, camera, textures)
                    if animal.eat_timer > 0:
                        rect = animal.rect.move(-int(camera.offset.x), -int(camera.offset.y))
                        bar_w = rect.width
                        bar_h = 4
                        bar_x = rect.x
                        bar_y = rect.y - 6
                        pygame.draw.rect(screen, (30, 30, 30), (bar_x, bar_y, bar_w, bar_h))
                        progress = min(1.0, animal.eat_timer / 1.2)
                        pygame.draw.rect(screen, (80, 200, 120), (bar_x, bar_y, int(bar_w * progress), bar_h))
                for carcass in active_carcasses:
                    rect = carcass.rect().move(-int(camera.offset.x), -int(camera.offset.y))
                    screen.blit(textures.carcass(), rect)
                player.draw(screen, camera, textures, pygame.time.get_ticks())
                draw_cave_darkness(screen, player, camera)
            else:
                overworld.draw(screen, camera, textures, pygame.time.get_ticks(), ui.debug_view)
                plants.draw(screen, camera, textures)
                for carcass in active_carcasses:
                    rect = carcass.rect().move(-int(camera.offset.x), -int(camera.offset.y))
                    screen.blit(textures.carcass(), rect)
                for npc in npcs:
                    npc.draw(screen, camera, textures)
                    if npc.eat_timer > 0:
                        rect = npc.rect.move(-int(camera.offset.x), -int(camera.offset.y))
                        bar_w = rect.width
                        bar_h = 4
                        bar_x = rect.x
                        bar_y = rect.y - 6
                        pygame.draw.rect(screen, (30, 30, 30), (bar_x, bar_y, bar_w, bar_h))
                        progress = min(1.0, npc.eat_timer / 1.2)
                        pygame.draw.rect(screen, (220, 160, 80), (bar_x, bar_y, int(bar_w * progress), bar_h))
                    if ui.npc_debug_view:
                        screen_pos = npc.position - camera.offset
                        info = npc_debug.get(npc.npc_id, {})
                        role = info.get("role", "member")
                        group = info.get("group", "?")
                        goal = info.get("goal")
                        task = info.get("task")
                        tgt = info.get("tgt")
                        act = info.get("act")
                        in_range = info.get("in")
                        tile = info.get("tile")
                        path = info.get("path")
                        plen = info.get("plen")
                        dir_tag = info.get("dir")
                        commit = info.get("commit")
                        hp = info.get("hp")
                        wpn = info.get("wpn")
                        extra = []
                        if goal is not None:
                            extra.append(f"goal:{goal}")
                        if task is not None:
                            extra.append(f"t:{task}")
                        if in_range is not None:
                            extra.append(f"in:{in_range}")
                        if act is not None:
                            extra.append(f"a:{act}")
                        if tgt is not None:
                            extra.append(f"g:{tgt}")
                        if tile is not None:
                            extra.append(f"tile:{tile}")
                        if path is not None:
                            extra.append(f"path:{path}")
                        if plen is not None:
                            extra.append(f"plen:{plen}")
                        if dir_tag is not None:
                            extra.append(f"dir:{dir_tag}")
                        if commit is not None:
                            extra.append(f"c:{commit}")
                        if info.get("next") is not None:
                            extra.append(f"n:{info.get('next')}")
                        if info.get("avg") is not None:
                            extra.append(f"avg:{info.get('avg')}")
                        if info.get("stk") is not None:
                            extra.append(f"stk:{info.get('stk')}")
                        if info.get("pf") is not None:
                            extra.append(f"pf:{info.get('pf')}")
                        if info.get("dw") is not None:
                            extra.append(f"dw:{info.get('dw')}")
                        if info.get("sat") is not None:
                            extra.append(f"sat:{info.get('sat')}")
                        if hp is not None:
                            extra.append(f"hp:{hp}")
                        if wpn is not None:
                            extra.append(f"wpn:{wpn}")
                        extra_text = " ".join(extra)
                        tag = f"{role} g{group} {npc.job} w:{npc.inventory['wood']} s:{npc.inventory['stone']} f:{npc.inventory['food']} {extra_text}".rstrip()
                        label = font.render(tag, True, (220, 220, 220))
                        screen.blit(label, (screen_pos.x + 8, screen_pos.y - 16))
                        target_grid = npc.action_grid or npc.target_grid
                        if target_grid is not None:
                            target_px = pygame.Vector2(
                                (target_grid[0] + 0.5) * TILE_SIZE,
                                (target_grid[1] + 0.5) * TILE_SIZE,
                            )
                            target_screen = target_px - camera.offset
                            pygame.draw.line(screen, (220, 200, 120), screen_pos, target_screen, 1)
                            pygame.draw.circle(screen, (220, 200, 120), (int(target_screen.x), int(target_screen.y)), 3, 1)
                for heart in list(hearts):
                    heart.update(dt)
                    heart.draw(screen, camera)
                    if heart.timer <= 0:
                        hearts.remove(heart)
                for animal in active_animals:
                    animal.draw(screen, camera, textures)
                    if animal.eat_timer > 0:
                        rect = animal.rect.move(-int(camera.offset.x), -int(camera.offset.y))
                        bar_w = rect.width
                        bar_h = 4
                        bar_x = rect.x
                        bar_y = rect.y - 6
                        pygame.draw.rect(screen, (30, 30, 30), (bar_x, bar_y, bar_w, bar_h))
                        progress = min(1.0, animal.eat_timer / 1.2)
                        pygame.draw.rect(screen, (80, 200, 120), (bar_x, bar_y, int(bar_w * progress), bar_h))
                player.draw(screen, camera, textures, pygame.time.get_ticks())

            if ui.build_mode and not in_cave:
                mouse_world = camera.screen_to_world(pygame.Vector2(pygame.mouse.get_pos()))
                grid_pos = overworld.to_grid(mouse_world)
                rect = overworld.grid_rect(grid_pos)
                rect.move_ip(-int(camera.offset.x), -int(camera.offset.y))
                can_place = can_place_building(overworld, player, grid_pos, ui.build_item)
                cursor_color = (80, 200, 80) if can_place else (200, 80, 80)
                pygame.draw.rect(screen, cursor_color, rect, 2)

            if actions.gather_target is not None and actions.gather_tile is not None:
                gather_world = cave_world if in_cave else overworld
                if gather_world is not None:
                    rect = gather_world.grid_rect(actions.gather_target)
                    rect.move_ip(-int(camera.offset.x), -int(camera.offset.y))
                    pygame.draw.rect(screen, (80, 160, 220), rect, 2)
                    bar_w = max(4, rect.width - 6)
                    bar_h = 6
                    bar_x = rect.x + 3
                    bar_y = rect.y + rect.height - bar_h - 3
                    pygame.draw.rect(screen, (30, 30, 30), (bar_x, bar_y, bar_w, bar_h))
                    progress = min(1.0, actions.gather_timer / GATHER_TIME[actions.gather_tile])
                    pygame.draw.rect(screen, (80, 160, 220), (bar_x, bar_y, int(bar_w * progress), bar_h))

            if actions.demolish_target is not None and not in_cave:
                rect = overworld.grid_rect(actions.demolish_target)
                rect.move_ip(-int(camera.offset.x), -int(camera.offset.y))
                pygame.draw.rect(screen, (200, 120, 60), rect, 2)
                bar_w = max(4, rect.width - 6)
                bar_h = 6
                bar_x = rect.x + 3
                bar_y = rect.y + rect.height - bar_h - 3
                pygame.draw.rect(screen, (40, 40, 40), (bar_x, bar_y, bar_w, bar_h))
                progress = min(1.0, actions.demolish_timer / DEMOLISH_TIME)
                pygame.draw.rect(screen, (200, 180, 60), (bar_x, bar_y, int(bar_w * progress), bar_h))

            if ui.npc_debug_view and not in_cave and npc_groups:
                for group in npc_groups.values():
                    home_grid = group.home_grid
                    r = group.home_radius
                    top_left = pygame.Vector2((home_grid[0] - r) * TILE_SIZE, (home_grid[1] - r) * TILE_SIZE)
                    size = pygame.Vector2((r * 2 + 1) * TILE_SIZE, (r * 2 + 1) * TILE_SIZE)
                    rect = pygame.Rect(
                        int(top_left.x - camera.offset.x),
                        int(top_left.y - camera.offset.y),
                        int(size.x),
                        int(size.y),
                    )
                    pygame.draw.rect(screen, (90, 120, 170), rect, 1)

            group_info = None
            if npc_groups:
                nearest = None
                nearest_dist = None
                for group in npc_groups.values():
                    home_grid = group.build_origin or group.camp_grid
                    home_px = pygame.Vector2((home_grid[0] + 0.5) * TILE_SIZE, (home_grid[1] + 0.5) * TILE_SIZE)
                    dist = player.position.distance_to(home_px)
                    if nearest is None or dist < nearest_dist:
                        nearest = group
                        nearest_dist = dist
                if nearest is not None:
                    cap = stockpile_capacity(nearest)
                    crates = len(nearest.storage_tiles)
                    pickaxes = nearest.tools.get("pickaxe", 0)
                    group_info = (
                        f"Group g{nearest.group_id} stock "
                        f"W:{nearest.stockpile['wood']}/{cap['wood']} "
                        f"S:{nearest.stockpile['stone']}/{cap['stone']} "
                        f"F:{nearest.stockpile['food']}/{cap['food']} "
                        f"crates:{crates} pickaxe:{pickaxes}"
                    )
            draw_hud(
                screen,
                font,
                player,
                ui.build_mode,
                ui.build_item,
                actions.demolish_target is not None,
                actions.gather_target is not None,
                actions.status_message,
                ui.inventory_open,
                group_info,
                actions.smelt_timer,
                ui.manual_npc_control,
            )

            if ui.manual_npc_control and not ui.inventory_open and not ui.map_open and not ui.build_mode and not in_cave:
                mouse_pos = pygame.Vector2(pygame.mouse.get_pos())
                mouse_world = camera.screen_to_world(mouse_pos)
                if ui.manual_command_mode:
                    if ui.manual_command_mode == "build":
                        label = f"Build {ui.manual_build_item}"
                    else:
                        label = ui.manual_command_mode
                else:
                    _job, _tgt, _act, _hunt, label = infer_manual_command(
                        overworld,
                        plants,
                        animals,
                        mouse_world,
                    )
                selected_label = None
                if ui.selected_npc_id is not None:
                    selected_label = f"NPC {ui.selected_npc_id}"
                elif ui.selected_group_id is not None:
                    selected_label = f"Group g{ui.selected_group_id}"
                if selected_label is None:
                    hint = "RMB: select NPC or group"
                else:
                    hint = f"RMB: {label} ({selected_label})  Shift: queue"
                hint_surf = font.render(hint, True, COLORS["ui_text"])
                pad = 6
                hint_rect = hint_surf.get_rect()
                hint_rect.topleft = (int(mouse_pos.x + 12), int(mouse_pos.y + 12))
                bg_rect = pygame.Rect(
                    hint_rect.x - pad,
                    hint_rect.y - pad,
                    hint_rect.width + pad * 2,
                    hint_rect.height + pad * 2,
                )
                pygame.draw.rect(screen, (8, 10, 14), bg_rect)
                pygame.draw.rect(screen, (60, 70, 80), bg_rect, 1)
                screen.blit(hint_surf, hint_rect)

            ui.group_panel_rect = pygame.Rect(0, 0, 0, 0)
            if not ui.npc_debug_view and ui.selected_group_id is not None and ui.selected_group_id in npc_groups:
                group = npc_groups[ui.selected_group_id]
                member_count = len([n for n in npcs if n.group_id == ui.selected_group_id])
                home_grid = group.build_origin or group.camp_grid
                has_workbench = find_tile_in_radius(overworld, home_grid, "workbench", radius=2) is not None
                ui.group_panel_rect = draw_group_panel(screen, font, group, member_count, has_workbench)
            if ui.npc_debug_view and not in_cave:
                debug_ui_state = draw_village_debug_panel(
                    screen,
                    font,
                    overworld,
                    npcs,
                    npc_groups,
                    ui.selected_group_id,
                    ui.selected_npc_id,
                    npc_debug,
                )
            else:
                debug_ui_state = {}
            if ui.manual_npc_control:
                manual_ui_state = draw_manual_control_panel(
                    screen,
                    font,
                    npcs,
                    ui.selected_group_id,
                    ui.selected_npc_id,
                    ui.manual_command_mode,
                    ui.manual_build_item,
                )
            else:
                manual_ui_state = {}
            if ui.civ_debug_view and civ_event_log:
                draw_civ_debug_panel(screen, font, civ_event_log, civ_raid_log)

            if ui.inventory_open and not in_cave:
                near_workbench = overworld.find_tile_near(player.position, "workbench", radius=1) is not None
                near_furnace = overworld.find_tile_near(player.position, "furnace", radius=1) is not None
                ui_state = draw_inventory_panel(
                    screen,
                    font,
                    player,
                    ui.build_item,
                    ui.hotbar_slots,
                    ui.crafting_scroll,
                    near_workbench,
                    near_furnace,
                    active_crate_inventory,
                    actions.smelt_timer > 0,
                )
                ui.crafting_scroll = int(ui_state.get("craft_scroll", ui.crafting_scroll))
            else:
                ui_state = {}

            if not in_cave:
                zoom_tiles = {1: 12, 2: 20, 3: 30}[ui.minimap_zoom]
                zoom_size = {1: 120, 2: 160, 3: 200}[ui.minimap_zoom]
                draw_minimap(screen, overworld, player, camera, zoom_size, zoom_tiles)
                if ui.map_open:
                    map_size = min(SCREEN_WIDTH - 40, SCREEN_HEIGHT - 40)
                    ui.map_rect, ui.map_scale = draw_world_map(
                        screen,
                        overworld,
                        player,
                        ui.map_center,
                        map_size,
                        70,
                        civ_regions,
                        ui.civ_debug_view,
                        font,
                    )
            pygame.display.flip()

        pygame.quit()


def main() -> None:
    Game().run()


if __name__ == "__main__":
    main()
