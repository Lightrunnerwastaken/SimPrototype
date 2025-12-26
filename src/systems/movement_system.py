import pygame

from src.constants import PLAYER_SPEED, WATER_SPEED_MULT, TILE_SIZE


def move_entity(entity, move_dir: pygame.Vector2, dt: float, world) -> None:
    if move_dir.length_squared() == 0:
        return

    speed = PLAYER_SPEED
    if world.tile_at_px(entity.position) == "water":
        speed *= WATER_SPEED_MULT
    delta = move_dir * speed * dt
    next_pos = pygame.Vector2(entity.position)

    next_pos.x += delta.x
    if not world.rect_collides(entity.rect_at(next_pos)):
        entity.position.x = next_pos.x

    next_pos.y = entity.position.y + delta.y
    if not world.rect_collides(entity.rect_at(next_pos)):
        entity.position.y = next_pos.y

    entity.is_swimming = world.tile_at_px(entity.position) == "water"
    resolve_stuck(entity, world, allow_water=True)


def move_agent(entity, move_dir: pygame.Vector2, dt: float, world, speed: float, can_swim: bool) -> None:
    if move_dir.length_squared() == 0:
        return

    delta = move_dir * speed * dt
    next_pos = pygame.Vector2(entity.position)

    next_pos.x += delta.x
    if can_swim or world.tile_at_px(next_pos) != "water":
        if not world.rect_collides(entity.rect_at(next_pos)):
            entity.position.x = next_pos.x
        elif delta.y != 0:
            slide = pygame.Vector2(entity.position.x, entity.position.y + delta.y * 0.6)
            if not world.rect_collides(entity.rect_at(slide)):
                entity.position.y = slide.y

    next_pos.y = entity.position.y + delta.y
    if can_swim or world.tile_at_px(next_pos) != "water":
        if not world.rect_collides(entity.rect_at(next_pos)):
            entity.position.y = next_pos.y
        elif delta.x != 0:
            slide = pygame.Vector2(entity.position.x + delta.x * 0.6, entity.position.y)
            if not world.rect_collides(entity.rect_at(slide)):
                entity.position.x = slide.x

    resolve_stuck(entity, world, allow_water=can_swim)


def resolve_stuck(entity, world, max_radius: int = 3, allow_water: bool = False) -> None:
    if not world.rect_collides(entity.rect):
        return

    center = world.to_grid(entity.position)
    for r in range(1, max_radius + 1):
        for y in range(center[1] - r, center[1] + r + 1):
            for x in range(center[0] - r, center[0] + r + 1):
                pos = pygame.Vector2((x + 0.5) * TILE_SIZE, (y + 0.5) * TILE_SIZE)
                if world.rect_collides(entity.rect_at(pos)):
                    continue
                if not allow_water and world.tile_at_px(pos) == "water":
                    continue
                entity.position = pos
                return
