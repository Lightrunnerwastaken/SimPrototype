import pygame


def get_movement_vector() -> pygame.Vector2:
    keys = pygame.key.get_pressed()
    movement = pygame.Vector2(0, 0)
    if keys[pygame.K_w]:
        movement.y -= 1
    if keys[pygame.K_s]:
        movement.y += 1
    if keys[pygame.K_a]:
        movement.x -= 1
    if keys[pygame.K_d]:
        movement.x += 1

    if movement.length_squared() > 0:
        movement = movement.normalize()
    return movement
