import random
import pygame

from src.constants import TILE_SIZE


def _speckle(surface: pygame.Surface, rng: random.Random, color: tuple[int, int, int], count: int) -> None:
    for _ in range(count):
        size = rng.randint(1, 3)
        x = rng.randint(0, TILE_SIZE - size)
        y = rng.randint(0, TILE_SIZE - size)
        pygame.draw.rect(surface, color, (x, y, size, size))


def _planks(surface: pygame.Surface, rng: random.Random, base: tuple[int, int, int]) -> None:
    surface.fill(base)
    for y in range(0, TILE_SIZE, 6):
        shade = (base[0] + rng.randint(-10, 10), base[1] + rng.randint(-10, 10), base[2] + rng.randint(-10, 10))
        pygame.draw.rect(surface, shade, (0, y, TILE_SIZE, 4))
    for _ in range(3):
        x = rng.randint(3, TILE_SIZE - 4)
        pygame.draw.line(surface, (60, 40, 25), (x, 2), (x, TILE_SIZE - 2), 1)


def _outline(surface: pygame.Surface, color: tuple[int, int, int]) -> None:
    pygame.draw.rect(surface, color, surface.get_rect(), 1)


class TextureAtlas:
    def __init__(self) -> None:
        self._tiles: dict[str, pygame.Surface] = {}
        self._ground_variants = [
            self._make_ground(101),
            self._make_ground(102),
            self._make_ground(103),
        ]
        self._tiles["floor"] = self._make_floor()
        self._tiles["sand"] = self._make_sand()
        self._water_frames = [
            self._make_water(808),
            self._make_water(809),
            self._make_water(810),
            self._make_water(811),
        ]
        self._tiles["hill"] = self._make_hill()
        self._tiles["mountain"] = self._make_mountain()
        self._tiles["scree"] = self._make_scree()
        self._tiles["cave_floor"] = self._make_cave_floor()
        self._tiles["cave_wall"] = self._make_cave_wall()
        self._tiles["cave_entrance"] = self._make_cave_entrance()
        self._tiles["cave_mouth_n"] = self._make_cave_mouth("n")
        self._tiles["cave_mouth_s"] = self._make_cave_mouth("s")
        self._tiles["cave_mouth_e"] = self._make_cave_mouth("e")
        self._tiles["cave_mouth_w"] = self._make_cave_mouth("w")
        self._tiles["cave_exit"] = self._make_cave_exit()
        self._tiles["tree"] = self._make_tree()
        self._tiles["rock"] = self._make_rock()
        self._tiles["iron_ore"] = self._make_iron_ore()
        self._tiles["wall"] = self._make_wall()
        self._tiles["workbench"] = self._make_workbench()
        self._tiles["crate"] = self._make_crate()
        self._tiles["furnace"] = self._make_furnace()
        self._tiles["stone_wall"] = self._make_stone_wall()
        self._tiles["stone_floor"] = self._make_stone_floor()
        self._tiles["road"] = self._make_road()
        self._tiles["door_closed"] = self._make_door_closed()
        self._tiles["door_open"] = self._make_door_open()
        self.player = self._make_player()
        self._animals = {
            "deer": self._make_animal((160, 120, 80), (90, 60, 40)),
            "rabbit": self._make_animal((210, 200, 190), (140, 130, 120)),      
            "wolf": self._make_animal((120, 130, 140), (70, 80, 90)),
            "spider": self._make_spider(),
        }
        self._npcs = {
            "human": self._make_npc((90, 140, 190), (50, 90, 140)),
        }
        self._carcass = self._make_carcass()
        self._plants = {
            "grass_a": self._make_plant((70, 120, 70)),
            "grass_b": self._make_plant((85, 135, 75)),
            "berry": self._make_plant((120, 160, 90)),
            "berry_bush": self._make_plant((100, 140, 80), (180, 60, 80)),
            "flower": self._make_plant((160, 120, 150)),
            "young_tree": self._make_plant((80, 130, 80)),
        }
        self._edges: dict[tuple[str, str, str], pygame.Surface] = {}
        for direction in ("n", "s", "e", "w"):
            self._edges[("ground", "sand", direction)] = self._make_edge((175, 165, 120, 190), direction)
            self._edges[("sand", "water", direction)] = self._make_edge((70, 120, 170, 210), direction)

    def tile(self, name: str) -> pygame.Surface:
        if name == "ground":
            return self._ground_variants[0]
        if name == "water":
            return self._water_frames[0]
        return self._tiles[name]

    def animal(self, name: str) -> pygame.Surface:
        return self._animals[name]

    def carcass(self) -> pygame.Surface:
        return self._carcass

    def npc(self, name: str) -> pygame.Surface:
        return self._npcs[name]

    def plant(self, name: str, stage: int) -> pygame.Surface:
        return self._plants[name][stage]

    def tile_at(self, name: str, grid_pos: tuple[int, int], time_ms: int) -> pygame.Surface:
        if name == "ground":
            x, y = grid_pos
            idx = ((x * 92837111) ^ (y * 689287499)) % len(self._ground_variants)
            return self._ground_variants[idx]
        if name == "water":
            x, y = grid_pos
            frame = ((time_ms // 220) + x + y) % len(self._water_frames)
            return self._water_frames[frame]
        return self._tiles[name]

    def edge(self, tile_from: str, tile_to: str, direction: str) -> pygame.Surface:
        return self._edges[(tile_from, tile_to, direction)]

    def _make_ground(self, seed: int) -> pygame.Surface:
        rng = random.Random(seed)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((50, 85, 50))
        _speckle(surface, rng, (45, 70, 45), 18)
        _speckle(surface, rng, (70, 100, 70), 10)
        return surface

    def _make_floor(self) -> pygame.Surface:
        rng = random.Random(202)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        _planks(surface, rng, (140, 105, 70))
        _outline(surface, (70, 50, 35))
        return surface

    def _make_hill(self) -> pygame.Surface:
        rng = random.Random(909)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((55, 95, 55))
        _speckle(surface, rng, (45, 80, 45), 16)
        _speckle(surface, rng, (70, 110, 70), 8)
        return surface

    def _make_sand(self) -> pygame.Surface:
        rng = random.Random(707)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((160, 150, 110))
        _speckle(surface, rng, (175, 165, 120), 14)
        _speckle(surface, rng, (145, 135, 100), 10)
        return surface

    def _make_water(self, seed: int) -> pygame.Surface:
        rng = random.Random(seed)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((40, 80, 120))
        for _ in range(4):
            x = rng.randint(2, TILE_SIZE - 8)
            y = rng.randint(2, TILE_SIZE - 6)
            pygame.draw.arc(surface, (70, 120, 170), (x, y, 10, 6), 0.0, 3.14, 1)
        _speckle(surface, rng, (35, 70, 110), 6)
        return surface

    def _make_edge(self, color: tuple[int, int, int, int], direction: str) -> pygame.Surface:
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        thickness = 6
        if direction == "n":
            pygame.draw.rect(surface, color, (0, 0, TILE_SIZE, thickness))
        elif direction == "s":
            pygame.draw.rect(surface, color, (0, TILE_SIZE - thickness, TILE_SIZE, thickness))
        elif direction == "w":
            pygame.draw.rect(surface, color, (0, 0, thickness, TILE_SIZE))
        elif direction == "e":
            pygame.draw.rect(surface, color, (TILE_SIZE - thickness, 0, thickness, TILE_SIZE))
        return surface

    def _make_tree(self) -> pygame.Surface:
        rng = random.Random(303)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((35, 95, 45))
        _speckle(surface, rng, (25, 80, 35), 12)
        _speckle(surface, rng, (50, 120, 60), 10)
        trunk = pygame.Rect(TILE_SIZE // 2 - 2, TILE_SIZE // 2 + 6, 4, 8)
        pygame.draw.rect(surface, (100, 70, 40), trunk)
        _outline(surface, (20, 50, 25))
        return surface

    def _make_rock(self) -> pygame.Surface:
        rng = random.Random(404)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((110, 115, 125))
        _speckle(surface, rng, (90, 95, 105), 14)
        _speckle(surface, rng, (130, 135, 145), 10)
        _outline(surface, (70, 75, 85))
        return surface

    def _make_iron_ore(self) -> pygame.Surface:
        rng = random.Random(409)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((95, 100, 110))
        _speckle(surface, rng, (75, 80, 90), 10)
        _speckle(surface, rng, (150, 90, 50), 8)
        _speckle(surface, rng, (170, 110, 60), 6)
        _outline(surface, (60, 65, 75))
        return surface

    def _make_mountain(self) -> pygame.Surface:
        rng = random.Random(1009)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((95, 100, 110))
        _speckle(surface, rng, (80, 85, 95), 16)
        _speckle(surface, rng, (120, 125, 135), 10)
        _outline(surface, (60, 65, 75))
        return surface

    def _make_spider(self) -> pygame.Surface:
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        body_color = (30, 30, 35)
        leg_color = (45, 45, 50)
        cx = TILE_SIZE // 2
        cy = TILE_SIZE // 2 + 2
        pygame.draw.circle(surface, body_color, (cx, cy), 5)
        pygame.draw.circle(surface, body_color, (cx + 4, cy - 2), 3)
        for dx, dy in [(-6, -4), (-6, -1), (-6, 2), (-5, 5), (6, -4), (6, -1), (6, 2), (5, 5)]:
            pygame.draw.line(surface, leg_color, (cx, cy), (cx + dx, cy + dy), 2)
        return surface

    def _make_scree(self) -> pygame.Surface:
        rng = random.Random(1013)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((80, 85, 90))
        _speckle(surface, rng, (60, 65, 70), 14)
        _speckle(surface, rng, (100, 105, 110), 12)
        _speckle(surface, rng, (120, 125, 130), 6)
        return surface

    def _make_cave_floor(self) -> pygame.Surface:
        rng = random.Random(1401)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((45, 45, 50))
        _speckle(surface, rng, (55, 55, 60), 10)
        return surface

    def _make_cave_wall(self) -> pygame.Surface:
        rng = random.Random(1402)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((30, 30, 35))
        _speckle(surface, rng, (60, 60, 70), 12)
        _outline(surface, (20, 20, 25))
        return surface

    def _make_cave_entrance(self) -> pygame.Surface:
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((90, 95, 105))
        pygame.draw.rect(surface, (70, 75, 85), (2, 2, TILE_SIZE - 4, TILE_SIZE - 4))
        pygame.draw.circle(surface, (20, 20, 24), (TILE_SIZE // 2, TILE_SIZE // 2 + 2), TILE_SIZE // 3)
        pygame.draw.rect(surface, (25, 25, 30), (TILE_SIZE // 2 - 6, TILE_SIZE // 2, 12, 10))
        _outline(surface, (50, 55, 65))
        return surface

    def _make_cave_mouth(self, direction: str) -> pygame.Surface:
        rng = random.Random(1204 + ord(direction))
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((75, 80, 85))
        _speckle(surface, rng, (65, 70, 75), 6)
        _speckle(surface, rng, (90, 95, 100), 6)
        if direction in {"n", "s"}:
            mouth_rect = pygame.Rect(5, TILE_SIZE // 2 - 2, TILE_SIZE - 10, TILE_SIZE // 2 + 4)
            pygame.draw.ellipse(surface, (25, 25, 30), mouth_rect)
            pygame.draw.rect(surface, (20, 20, 24), (6, TILE_SIZE // 2 + 2, TILE_SIZE - 12, 5))
        else:
            mouth_rect = pygame.Rect(TILE_SIZE // 2 - 2, 5, TILE_SIZE // 2 + 4, TILE_SIZE - 10)
            pygame.draw.ellipse(surface, (25, 25, 30), mouth_rect)
            pygame.draw.rect(surface, (20, 20, 24), (TILE_SIZE // 2 + 2, 6, 5, TILE_SIZE - 12))
        if direction == "n":
            pygame.draw.rect(surface, (55, 60, 65), (0, 0, TILE_SIZE, TILE_SIZE // 3), 1)
        elif direction == "s":
            pygame.draw.rect(surface, (55, 60, 65), (0, TILE_SIZE - TILE_SIZE // 3, TILE_SIZE, TILE_SIZE // 3), 1)
        elif direction == "w":
            pygame.draw.rect(surface, (55, 60, 65), (0, 0, TILE_SIZE // 3, TILE_SIZE), 1)
        else:
            pygame.draw.rect(surface, (55, 60, 65), (TILE_SIZE - TILE_SIZE // 3, 0, TILE_SIZE // 3, TILE_SIZE), 1)
        _outline(surface, (45, 50, 55))
        return surface

    def _make_cave_exit(self) -> pygame.Surface:
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((45, 45, 50))
        pygame.draw.rect(surface, (80, 60, 40), (6, 6, TILE_SIZE - 12, TILE_SIZE - 12))
        _outline(surface, (20, 20, 25))
        return surface

    def _make_wall(self) -> pygame.Surface:
        rng = random.Random(505)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((110, 80, 55))
        for y in range(0, TILE_SIZE, 6):
            pygame.draw.rect(surface, (95, 70, 50), (0, y, TILE_SIZE, 4))
        _speckle(surface, rng, (125, 95, 70), 8)
        _outline(surface, (60, 45, 30))
        return surface

    def _make_stone_wall(self) -> pygame.Surface:
        rng = random.Random(706)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((120, 125, 135))
        _speckle(surface, rng, (140, 145, 155), 10)
        _speckle(surface, rng, (95, 100, 110), 8)
        for y in range(0, TILE_SIZE, 7):
            pygame.draw.rect(surface, (100, 105, 115), (0, y, TILE_SIZE, 3))
        _outline(surface, (70, 75, 85))
        return surface

    def _make_stone_floor(self) -> pygame.Surface:
        rng = random.Random(707)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((135, 140, 150))
        _speckle(surface, rng, (155, 160, 170), 12)
        _speckle(surface, rng, (115, 120, 130), 10)
        _outline(surface, (80, 85, 95))
        return surface

    def _make_road(self) -> pygame.Surface:
        rng = random.Random(910)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((110, 95, 75))
        _speckle(surface, rng, (130, 115, 90), 10)
        pygame.draw.rect(surface, (95, 80, 60), (2, 2, TILE_SIZE - 4, TILE_SIZE - 4), 1)
        return surface

    def _make_workbench(self) -> pygame.Surface:
        rng = random.Random(606)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((130, 95, 65))
        pygame.draw.rect(surface, (95, 70, 50), (2, 6, TILE_SIZE - 4, TILE_SIZE - 12))
        pygame.draw.rect(surface, (160, 120, 85), (4, 8, TILE_SIZE - 8, 6))
        pygame.draw.rect(surface, (80, 60, 45), (6, TILE_SIZE - 8, TILE_SIZE - 12, 4))
        _speckle(surface, rng, (150, 110, 80), 6)
        _outline(surface, (60, 45, 30))
        return surface

    def _make_furnace(self) -> pygame.Surface:
        rng = random.Random(612)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((120, 125, 130))
        _speckle(surface, rng, (140, 145, 150), 8)
        _speckle(surface, rng, (95, 100, 110), 6)
        pygame.draw.rect(surface, (40, 40, 45), (6, 10, TILE_SIZE - 12, TILE_SIZE - 14))
        pygame.draw.rect(surface, (180, 110, 60), (10, TILE_SIZE - 10, TILE_SIZE - 20, 4))
        _outline(surface, (70, 75, 85))
        return surface

    def _make_crate(self) -> pygame.Surface:
        rng = random.Random(614)
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        _planks(surface, rng, (150, 110, 70))
        pygame.draw.rect(surface, (95, 70, 45), (4, 4, TILE_SIZE - 8, TILE_SIZE - 8), 2)
        pygame.draw.line(surface, (95, 70, 45), (5, 5), (TILE_SIZE - 5, TILE_SIZE - 5), 1)
        pygame.draw.line(surface, (95, 70, 45), (5, TILE_SIZE - 5), (TILE_SIZE - 5, 5), 1)
        return surface

    def _make_player(self) -> pygame.Surface:
        surface = pygame.Surface((int(TILE_SIZE * 0.6), int(TILE_SIZE * 0.6)))
        surface.fill((230, 210, 80))
        _outline(surface, (120, 110, 45))
        return surface

    def _make_npc(self, base: tuple[int, int, int], outline: tuple[int, int, int]) -> pygame.Surface:
        size = int(TILE_SIZE * 0.55)
        surface = pygame.Surface((size, size))
        surface.fill(base)
        _outline(surface, outline)
        return surface

    def _make_door_closed(self) -> pygame.Surface:
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((110, 80, 55))
        pygame.draw.rect(surface, (75, 55, 40), (4, 2, TILE_SIZE - 8, TILE_SIZE - 4))
        pygame.draw.rect(surface, (60, 45, 35), (8, 4, TILE_SIZE - 16, TILE_SIZE - 8))
        _outline(surface, (50, 35, 25))
        return surface

    def _make_door_open(self) -> pygame.Surface:
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((120, 90, 65))
        pygame.draw.rect(surface, (60, 45, 35), (2, 2, 6, TILE_SIZE - 4))
        pygame.draw.rect(surface, (80, 60, 45), (6, 6, 4, TILE_SIZE - 12))
        _outline(surface, (50, 35, 25))
        return surface

    def _make_animal(self, base: tuple[int, int, int], outline: tuple[int, int, int]) -> pygame.Surface:
        size = int(TILE_SIZE * 0.5)
        surface = pygame.Surface((size, size))
        surface.fill(base)
        _outline(surface, outline)
        return surface

    def _make_carcass(self) -> pygame.Surface:
        size = int(TILE_SIZE * 0.6)
        surface = pygame.Surface((size, size))
        surface.fill((120, 60, 50))
        _outline(surface, (60, 30, 25))
        return surface

    def _make_plant(
        self,
        base: tuple[int, int, int],
        accent: tuple[int, int, int] | None = None,
    ) -> list[pygame.Surface]:
        stages = []
        sizes = [6, 10, 13, 16]
        for i, size in enumerate(sizes):
            surface = pygame.Surface((size, size), pygame.SRCALPHA)
            color = (min(base[0] + i * 8, 255), min(base[1] + i * 8, 255), min(base[2] + i * 6, 255))
            pygame.draw.circle(surface, color, (size // 2, size // 2), size // 2)
            if accent and i >= 2:
                pygame.draw.circle(surface, accent, (size // 2, size // 2), max(2, size // 6))
            stages.append(surface)
        return stages
