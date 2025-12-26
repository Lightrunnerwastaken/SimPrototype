import pygame


class HeartEffect:
    def __init__(self, position: pygame.Vector2) -> None:
        self.position = pygame.Vector2(position)
        self.timer = 0.8

    def update(self, dt: float) -> None:
        if self.timer <= 0:
            return
        self.timer -= dt
        self.position.y -= 12 * dt

    def draw(self, surface: pygame.Surface, camera) -> None:
        if self.timer <= 0:
            return
        pos = self.position - camera.offset
        pygame.draw.circle(surface, (220, 80, 120), (int(pos.x), int(pos.y)), 4)
        pygame.draw.circle(surface, (220, 80, 120), (int(pos.x + 4), int(pos.y)), 4)
        pygame.draw.polygon(
            surface,
            (220, 80, 120),
            [
                (int(pos.x - 2), int(pos.y + 2)),
                (int(pos.x + 10), int(pos.y + 2)),
                (int(pos.x + 4), int(pos.y + 10)),
            ],
        )
