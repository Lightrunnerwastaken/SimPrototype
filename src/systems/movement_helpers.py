import math
import random

import pygame

from src.constants import TILE_SIZE


def random_dir() -> pygame.Vector2:
    angle = random.uniform(0, math.pi * 2.0)
    return pygame.Vector2(math.cos(angle), math.sin(angle))


def resolve_move_dir(entity, desired: pygame.Vector2, world) -> pygame.Vector2:
    if desired.length_squared() == 0:
        return desired

    desired = desired.normalize()
    next_pos = entity.position + desired * TILE_SIZE * 0.6
    if world.tile_at_px(next_pos) != "water" and not world.rect_collides(entity.rect_at(next_pos)):
        return desired

    for angle in (45, -45, 90, -90, 135, -135):
        rotated = desired.rotate(angle)
        next_pos = entity.position + rotated * TILE_SIZE * 0.6
        if world.tile_at_px(next_pos) != "water" and not world.rect_collides(entity.rect_at(next_pos)):
            return rotated

    return pygame.Vector2(0, 0)
