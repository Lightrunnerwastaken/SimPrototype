import pygame

from src.constants import CAMERA_LERP


class Camera:
    def __init__(self, screen_size: tuple[int, int], position_px: pygame.Vector2) -> None:
        self.position = pygame.Vector2(position_px)
        self.screen_size = pygame.Vector2(screen_size)

    @property
    def offset(self) -> pygame.Vector2:
        return self.position - self.screen_size * 0.5

    def update(self, target_position: pygame.Vector2, dt: float) -> None:
        follow_rate = min(1.0, CAMERA_LERP * dt)
        self.position += (target_position - self.position) * follow_rate

    def screen_to_world(self, screen_pos: pygame.Vector2) -> pygame.Vector2:
        return screen_pos + self.offset
