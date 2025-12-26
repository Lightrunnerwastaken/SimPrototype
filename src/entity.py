import math
import pygame

from src.constants import TILE_SIZE, COLORS


class Player:
    def __init__(self, position_px: pygame.Vector2) -> None:
        self.position = pygame.Vector2(position_px)
        self.size = pygame.Vector2(TILE_SIZE * 0.6, TILE_SIZE * 0.6)
        self.inventory = {
            "wood": 0,
            "stone": 0,
            "food": 0,
            "iron_ore": 0,
            "iron": 0,
            "string": 0,
        }
        self.is_swimming = False
        self.max_hp = 20.0
        self.hp = 20.0
        self.hunger = 1.0
        self.attack_cooldown = 0.0
        self.attack_timer = 0.0
        self.last_attack_dir = pygame.Vector2(1, 0)
        self.weapon: str | None = None
        self.damage_cooldown = 0.0

    def add_item(self, item: str, amount: int) -> None:
        self.inventory[item] = self.inventory.get(item, 0) + amount

    def rect_at(self, position_px: pygame.Vector2) -> pygame.Rect:
        return pygame.Rect(
            position_px.x - self.size.x * 0.5,
            position_px.y - self.size.y * 0.5,
            self.size.x,
            self.size.y,
        )

    @property
    def rect(self) -> pygame.Rect:
        return self.rect_at(self.position)

    def draw(self, surface: pygame.Surface, camera, textures, time_ms: int) -> None:
        rect = self.rect.move(-int(camera.offset.x), -int(camera.offset.y))
        if self.is_swimming:
            bob = int(math.sin(time_ms / 180.0) * 2)
            rect.move_ip(0, bob + 3)
            ripple = pygame.Rect(rect.x - 2, rect.y + rect.height - 4, rect.width + 4, 6)
            pygame.draw.ellipse(surface, (90, 140, 190), ripple, 1)
            surface.blit(textures.player, rect)
            pygame.draw.rect(surface, COLORS["player"], rect, 1)
        else:
            surface.blit(textures.player, rect)
            pygame.draw.rect(surface, COLORS["player"], rect, 1)
        if self.attack_timer > 0:
            center = pygame.Vector2(rect.centerx, rect.centery)
            swing_dir = self.last_attack_dir
            if swing_dir.length_squared() == 0:
                swing_dir = pygame.Vector2(1, 0)
            swing_dir = swing_dir.normalize()
            if self.weapon == "spear":
                tip = center + swing_dir * (rect.width + 16)
                pygame.draw.line(
                    surface,
                    (240, 210, 120),
                    (int(center.x), int(center.y)),
                    (int(tip.x), int(tip.y)),
                    3,
                )
                pygame.draw.circle(surface, (240, 210, 120), (int(tip.x), int(tip.y)), 3)
            elif self.weapon == "club":
                radius = rect.width + 8
                angle = math.atan2(swing_dir.y, swing_dir.x)
                angle += math.pi
                arc_rect = pygame.Rect(
                    int(center.x - radius),
                    int(center.y - radius),
                    int(radius * 2),
                    int(radius * 2),
                )
                pygame.draw.arc(surface, (220, 170, 90), arc_rect, angle - 1.1, angle + 1.1, 3)
                tip = center + swing_dir * (rect.width + 6)
                pygame.draw.line(
                    surface,
                    (220, 170, 90),
                    (int(center.x), int(center.y)),
                    (int(tip.x), int(tip.y)),
                    4,
                )
            else:
                tip = center + swing_dir * (rect.width + 6)
                pygame.draw.line(
                    surface,
                    (240, 200, 90),
                    (int(center.x), int(center.y)),
                    (int(tip.x), int(tip.y)),
                    2,
                )


class Animal:
    def __init__(self, species: str, position_px: pygame.Vector2) -> None:
        self.species = species
        self.position = pygame.Vector2(position_px)
        self.size = pygame.Vector2(TILE_SIZE * 0.5, TILE_SIZE * 0.5)
        if species == "spider":
            self.max_hp = 6.0
        elif species in {"deer", "wolf"}:
            self.max_hp = 8.0
        else:
            self.max_hp = 5.0
        self.hp = self.max_hp
        self.hit_timer = 0.0
        self.attack_cooldown = 0.0
        self.wander_dir = pygame.Vector2(0, 0)
        self.state_timer = 0.0
        self.hunger = 0.0
        self.satisfaction = 0.75
        self.eat_timer = 0.0
        self.mate_cooldown = 0.0
        self.eat_target = None
        self.velocity = pygame.Vector2(0, 0)
        self.flee_dir = pygame.Vector2(0, 0)
        self.flee_timer = 0.0
        self.chase_target = None
        self.chase_timer = 0.0
        self.contest_timer = 0.0

    def rect_at(self, position_px: pygame.Vector2) -> pygame.Rect:
        return pygame.Rect(
            position_px.x - self.size.x * 0.5,
            position_px.y - self.size.y * 0.5,
            self.size.x,
            self.size.y,
        )

    @property
    def rect(self) -> pygame.Rect:
        return self.rect_at(self.position)

    def draw(self, surface: pygame.Surface, camera, textures) -> None:
        rect = self.rect.move(-int(camera.offset.x), -int(camera.offset.y))
        surface.blit(textures.animal(self.species), rect)
        if self.hit_timer > 0:
            pygame.draw.rect(surface, (220, 80, 80), rect, 2)


class Carcass:
    def __init__(self, position: pygame.Vector2, bites: int = 3) -> None:
        self.position = pygame.Vector2(position)
        self.bites_left = bites
        self.eat_timer = 0.0
        self.decay_timer = 25.0
        self.claimed_by: int | None = None

    def rect(self) -> pygame.Rect:
        size = TILE_SIZE * 0.6
        return pygame.Rect(
            self.position.x - size * 0.5,
            self.position.y - size * 0.5,
            size,
            size,
        )


class NPC:
    def __init__(self, npc_id: int, group_id: int, position_px: pygame.Vector2) -> None:
        self.npc_id = npc_id
        self.group_id = group_id
        self.position = pygame.Vector2(position_px)
        self.size = pygame.Vector2(TILE_SIZE * 0.55, TILE_SIZE * 0.55)
        self.velocity = pygame.Vector2(0, 0)
        self.wander_dir = pygame.Vector2(0, 0)
        self.state_timer = 0.0
        self.leader = False
        self.job = "idle"
        self.max_hp = 12.0
        self.hp = 12.0
        self.weapon: str | None = None
        self.attack_cooldown = 0.0
        self.combat_target_id: int | None = None
        self.hunger = 0.0
        self.satisfaction = 0.75
        self.eat_timer = 0.0
        self.hunt_target = None
        self.eat_target = None
        self.stuck_events = 0
        self.path_failures = 0
        self.door_waits = 0
        self.travel_timer = 0.0
        self.travel_total = 0.0
        self.travel_samples = 0
        self.travel_target: tuple[int, int] | None = None
        self.avoid_tiles: dict[tuple[int, int], float] = {}
        self.target_grid: tuple[int, int] | None = None
        self.action_grid: tuple[int, int] | None = None
        self.task_timer = 0.0
        self.task_key: str | None = None
        self.task_commit_timer = 0.0
        self.task_cooldowns: dict[str, float] = {}
        self.inventory = {"wood": 0, "food": 0, "stone": 0}
        self.job_lock_timer = 0.0
        self.last_pos = pygame.Vector2(position_px)
        self.stuck_timer = 0.0
        self.path: list[tuple[int, int]] = []
        self.path_index = 0
        self.path_retries = 0
        self.path_cooldown = 0.0
        self.path_target: tuple[int, int] | None = None
        self.recover_target: tuple[int, int] | None = None
        self.recover_timer = 0.0
        self.recover_return_target: tuple[int, int] | None = None
        self.recover_return_action: tuple[int, int] | None = None
        self.recover_start_grid: tuple[int, int] | None = None

    def rect_at(self, position_px: pygame.Vector2) -> pygame.Rect:
        return pygame.Rect(
            position_px.x - self.size.x * 0.5,
            position_px.y - self.size.y * 0.5,
            self.size.x,
            self.size.y,
        )

    @property
    def rect(self) -> pygame.Rect:
        return self.rect_at(self.position)

    def draw(self, surface: pygame.Surface, camera, textures) -> None:
        rect = self.rect.move(-int(camera.offset.x), -int(camera.offset.y))
        surface.blit(textures.npc("human"), rect)
