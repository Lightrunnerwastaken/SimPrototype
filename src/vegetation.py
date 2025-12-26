import random
import pygame

from src.constants import TILE_SIZE


class Plant:
    def __init__(self, kind: str, position_px: pygame.Vector2) -> None:
        self.kind = kind
        self.position = pygame.Vector2(position_px)
        self.stage = 0
        self.timer = random.uniform(4.0, 7.0)
        self.matured = False

    def advance(self) -> None:
        if self.stage < 3:
            self.stage += 1
            self.timer = random.uniform(6.0, 14.0)
        if self.stage == 3:
            self.matured = True


class PlantManager:
    def __init__(self) -> None:
        self.plants: dict[tuple[int, int], Plant] = {}
        self._keys: list[tuple[int, int]] = []
        self._update_index = 0

    def _key(self, grid_pos: tuple[int, int]) -> tuple[int, int]:
        return grid_pos

    def try_spawn(
        self,
        world,
        center_grid: tuple[int, int],
        radius: int,
        attempts: int,
        kinds: list[str],
    ) -> None:
        for _ in range(attempts):
            dx = random.randint(-radius, radius)
            dy = random.randint(-radius, radius)
            gx = center_grid[0] + dx
            gy = center_grid[1] + dy
            key = self._key((gx, gy))
            if key in self.plants:
                continue
            tile = world.get_tile((gx, gy))
            if tile not in {"ground", "hill"}:
                continue
            height, moisture, _boundary, _conv = world.debug_fields((gx, gy))
            if moisture < 0.35 or height < 0.34 or height > 0.78:
                continue
            kind = random.choice(kinds)
            pos = pygame.Vector2((gx + 0.5) * TILE_SIZE, (gy + 0.5) * TILE_SIZE)
            plant = Plant(kind, pos)
            self.plants[key] = plant
            self._keys.append(key)

    def update(self, dt: float, max_updates: int = 40) -> None:
        if not self._keys:
            return
        count = min(max_updates, len(self._keys))
        for _ in range(count):
            if self._update_index >= len(self._keys):
                self._update_index = 0
            key = self._keys[self._update_index]
            plant = self.plants.get(key)
            self._update_index += 1
            if plant is None:
                continue
            plant.timer -= dt
            if plant.timer <= 0:
                if plant.stage < 3:
                    plant.advance()
                else:
                    if plant.matured:
                        plant.matured = False
                        if random.random() < 0.35:
                            self._try_spawn_from_parent(plant)
                    plant.timer = random.uniform(6.0, 14.0)

    def _try_spawn_from_parent(self, plant: Plant) -> None:
        base_key = (int(plant.position.x // TILE_SIZE), int(plant.position.y // TILE_SIZE))
        for _attempt in range(8):
            dx = random.randint(-2, 2)
            dy = random.randint(-2, 2)
            if dx == 0 and dy == 0:
                continue
            key = (base_key[0] + dx, base_key[1] + dy)
            if key in self.plants:
                continue
            if random.random() < 0.25:
                kind = "berry_bush"
            elif plant.kind.startswith("grass") and random.random() < 0.5:
                kind = random.choice(["grass_a", "grass_b"])
            else:
                kind = plant.kind
            pos = pygame.Vector2((key[0] + 0.5) * TILE_SIZE, (key[1] + 0.5) * TILE_SIZE)
            self.plants[key] = Plant(kind, pos)
            self._keys.append(key)
            break

    def draw(self, surface: pygame.Surface, camera, textures) -> None:
        for plant in self.plants.values():
            rect = pygame.Rect(
                plant.position.x - TILE_SIZE * 0.25 - camera.offset.x,
                plant.position.y - TILE_SIZE * 0.25 - camera.offset.y,
                TILE_SIZE * 0.5,
                TILE_SIZE * 0.5,
            )
            surface.blit(textures.plant(plant.kind, plant.stage), rect)

    def find_near(self, position_px: pygame.Vector2, radius_tiles: int = 2) -> Plant | None:
        center = (int(position_px.x // TILE_SIZE), int(position_px.y // TILE_SIZE))
        best = None
        best_dist = None
        for y in range(center[1] - radius_tiles, center[1] + radius_tiles + 1):
            for x in range(center[0] - radius_tiles, center[0] + radius_tiles + 1):
                plant = self.plants.get((x, y))
                if plant is None:
                    continue
                dist = plant.position.distance_to(position_px)
                if best is None or dist < best_dist:
                    best = plant
                    best_dist = dist
        return best

    def consume(self, plant: Plant) -> None:
        key = (int(plant.position.x // TILE_SIZE), int(plant.position.y // TILE_SIZE))
        if key in self.plants:
            del self.plants[key]
        if key in self._keys:
            self._keys.remove(key)
