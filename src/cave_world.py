import pygame

from src.constants import TILE_SIZE


class CaveWorld:
    def __init__(self, seed: int, exit_grid: tuple[int, int]) -> None:
        self.seed = seed
        self.tiles: dict[tuple[int, int], str] = {}
        self.chunk_size = 16
        self._chunk_cache: dict[tuple[int, int], pygame.Surface] = {}
        self._chunk_dirty: set[tuple[int, int]] = set()
        self.exit_grid = exit_grid

    def _hash(self, x: int, y: int, offset: int) -> int:
        return (x * 374761393 + y * 668265263 + self.seed * 1442695049 + offset) & 0xFFFFFFFF

    def _value_noise(self, x: float, y: float, scale: float, offset: int) -> float:
        fx = x / scale
        fy = y / scale
        x0 = int(fx)
        y0 = int(fy)
        x1 = x0 + 1
        y1 = y0 + 1

        sx = fx - x0
        sy = fy - y0

        n00 = self._hash(x0, y0, offset) / 0xFFFFFFFF
        n10 = self._hash(x1, y0, offset) / 0xFFFFFFFF
        n01 = self._hash(x0, y1, offset) / 0xFFFFFFFF
        n11 = self._hash(x1, y1, offset) / 0xFFFFFFFF

        ix0 = n00 * (1.0 - sx) + n10 * sx
        ix1 = n01 * (1.0 - sx) + n11 * sx
        return ix0 * (1.0 - sy) + ix1 * sy

    def _generate_tile(self, grid_pos: tuple[int, int]) -> str:
        if grid_pos == self.exit_grid:
            return "cave_exit"
        x, y = grid_pos
        n1 = self._value_noise(x, y, 24.0, 901)
        n2 = self._value_noise(x, y, 9.0, 1201)
        density = n1 * 0.65 + n2 * 0.35
        if density > 0.58:
            return "cave_wall"
        ore_noise = self._value_noise(x, y, 12.0, 1501)
        if ore_noise > 0.78 and density > 0.46:
            return "iron_ore"
        return "cave_floor"

    def get_tile(self, grid_pos: tuple[int, int]) -> str:
        tile = self.tiles.get(grid_pos)
        if tile is None:
            tile = self._generate_tile(grid_pos)
            self.tiles[grid_pos] = tile
        return tile

    def set_tile(self, grid_pos: tuple[int, int], tile: str) -> None:
        self.tiles[grid_pos] = tile
        self._mark_chunks_dirty(grid_pos)

    def is_blocking(self, tile: str) -> bool:
        return tile in {"cave_wall", "iron_ore"}

    def tile_at_px(self, position_px: pygame.Vector2) -> str:
        return self.get_tile(self.to_grid(position_px))

    def to_grid(self, position_px: pygame.Vector2) -> tuple[int, int]:
        return int(position_px.x // TILE_SIZE), int(position_px.y // TILE_SIZE)

    def grid_rect(self, grid_pos: tuple[int, int]) -> pygame.Rect:
        x, y = grid_pos
        return pygame.Rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE)

    def rect_collides(self, rect: pygame.Rect) -> bool:
        min_x = int(rect.left // TILE_SIZE)
        max_x = int((rect.right - 1) // TILE_SIZE)
        min_y = int(rect.top // TILE_SIZE)
        max_y = int((rect.bottom - 1) // TILE_SIZE)
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                if self.is_blocking(self.get_tile((x, y))):
                    return True
        return False

    def find_resource_near(self, position_px: pygame.Vector2, radius: int = 1) -> tuple[tuple[int, int], str] | None:
        center = self.to_grid(position_px)
        best = None
        best_dist = None
        for y in range(center[1] - radius, center[1] + radius + 1):
            for x in range(center[0] - radius, center[0] + radius + 1):
                tile = self.get_tile((x, y))
                if tile not in {"iron_ore"}:
                    continue
                tile_center = pygame.Vector2((x + 0.5) * TILE_SIZE, (y + 0.5) * TILE_SIZE)
                dist = tile_center.distance_to(position_px)
                if best is None or dist < best_dist:
                    best = ((x, y), tile)
                    best_dist = dist
        return best

    def _chunk_key(self, grid_pos: tuple[int, int]) -> tuple[int, int]:
        gx, gy = grid_pos
        return gx // self.chunk_size, gy // self.chunk_size

    def _mark_chunks_dirty(self, grid_pos: tuple[int, int]) -> None:
        cx, cy = self._chunk_key(grid_pos)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                self._chunk_dirty.add((cx + dx, cy + dy))

    def _build_chunk(self, chunk_key: tuple[int, int], textures) -> pygame.Surface:
        cx, cy = chunk_key
        size_px = self.chunk_size * TILE_SIZE
        surface = pygame.Surface((size_px, size_px))
        base_x = cx * self.chunk_size
        base_y = cy * self.chunk_size

        for y in range(base_y, base_y + self.chunk_size):
            for x in range(base_x, base_x + self.chunk_size):
                tile = self.get_tile((x, y))
                rect = pygame.Rect(
                    (x - base_x) * TILE_SIZE,
                    (y - base_y) * TILE_SIZE,
                    TILE_SIZE,
                    TILE_SIZE,
                )
                surface.blit(textures.tile_at(tile, (x, y), 0), rect)

        return surface

    def draw(self, surface: pygame.Surface, camera, textures) -> None:
        offset = camera.offset
        screen_w, screen_h = surface.get_size()
        start_x = int(offset.x // TILE_SIZE) - 1
        end_x = int((offset.x + screen_w) // TILE_SIZE) + 1
        start_y = int(offset.y // TILE_SIZE) - 1
        end_y = int((offset.y + screen_h) // TILE_SIZE) + 1

        start_cx = start_x // self.chunk_size
        end_cx = end_x // self.chunk_size
        start_cy = start_y // self.chunk_size
        end_cy = end_y // self.chunk_size

        for cy in range(start_cy, end_cy + 1):
            for cx in range(start_cx, end_cx + 1):
                key = (cx, cy)
                if key not in self._chunk_cache or key in self._chunk_dirty:
                    self._chunk_cache[key] = self._build_chunk(key, textures)
                    self._chunk_dirty.discard(key)
                chunk_surf = self._chunk_cache[key]
                dest_x = cx * self.chunk_size * TILE_SIZE - offset.x
                dest_y = cy * self.chunk_size * TILE_SIZE - offset.y
                surface.blit(chunk_surf, (int(dest_x), int(dest_y)))
