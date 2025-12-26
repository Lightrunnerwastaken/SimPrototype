import random

import pygame

from src.constants import TILE_SIZE, WEAPON_STATS
from src.entity import Player, Animal, Carcass


def find_nearest_carcass(
    carcasses: list[Carcass],
    position_px: pygame.Vector2,
    radius_px: float,
    allow_claimed_by: int | None = None,
) -> Carcass | None:
    nearest = None
    nearest_dist = None
    for carcass in carcasses:
        if carcass.claimed_by is not None and carcass.claimed_by != allow_claimed_by:
            continue
        dist = carcass.position.distance_to(position_px)
        if dist <= radius_px and (nearest is None or dist < nearest_dist):
            nearest = carcass
            nearest_dist = dist
    return nearest


def harvest_carcass(player: Player, carcasses: list[Carcass]) -> bool:
    carcass = find_nearest_carcass(carcasses, player.position, TILE_SIZE * 1.2)
    if carcass is None:
        return False
    food_gain = max(1, carcass.bites_left)
    player.add_item("food", food_gain)
    carcasses.remove(carcass)
    return True


def find_nearest_animal(
    animals: list[Animal],
    position_px: pygame.Vector2,
    radius_px: float,
) -> Animal | None:
    nearest = None
    nearest_dist = None
    for animal in animals:
        dist = animal.position.distance_to(position_px)
        if dist <= radius_px and (nearest is None or dist < nearest_dist):
            nearest = animal
            nearest_dist = dist
    return nearest


def perform_player_swing(
    player: Player,
    animals: list[Animal],
    carcasses: list[Carcass],
    target_px: pygame.Vector2,
) -> bool:
    attack_dir = target_px - player.position
    if attack_dir.length_squared() == 0:
        attack_dir = pygame.Vector2(1, 0)
    attack_dir = attack_dir.normalize()
    player.last_attack_dir = attack_dir

    weapon = player.weapon
    if weapon is not None and player.inventory.get(weapon, 0) <= 0:
        weapon = None
        player.weapon = None
    stats = WEAPON_STATS.get(weapon, {})
    max_range = stats.get("range", TILE_SIZE * 1.05)
    min_dot = stats.get("min_dot", 0.45)
    swing_time = stats.get("swing", 0.18)
    cooldown = stats.get("cooldown", 0.35)
    player.attack_timer = swing_time

    if player.attack_cooldown > 0:
        return False
    target = None
    target_dist = None
    for animal in animals:
        delta = animal.position - player.position
        dist = delta.length()
        if dist > max_range or dist == 0:
            continue
        dir_to = delta.normalize()
        if dir_to.dot(attack_dir) < min_dot:
            continue
        if target is None or dist < target_dist:
            target = animal
            target_dist = dist

    if target is None:
        player.attack_cooldown = 0.25
        return False

    damage = stats.get("damage", 2)
    target.hp -= damage
    target.hit_timer = 0.2
    player.attack_cooldown = cooldown
    if target.hp <= 0:
        if target.species == "spider" and random.random() < 0.5:
            player.add_item("string", 1)
        animals.remove(target)
        carcasses.append(Carcass(target.position, bites=3))
    return True
