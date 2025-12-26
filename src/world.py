import math
import pygame

from src.constants import TILE_SIZE


class World:
    def __init__(self, seed: int = 7) -> None:
        self.seed = seed
        self.tiles: dict[tuple[int, int], str] = {}
        self.chunk_size = 16
        self._chunk_cache: dict[tuple[int, int], pygame.Surface] = {}
        self._chunk_dirty: set[tuple[int, int]] = set()
        self._cave_mouth_done: set[tuple[int, int]] = set()
        self._cave_region_counts: dict[tuple[int, int], int] = {}
        self._cave_region_size = 50
        self.spawn_px = pygame.Vector2(0, 0)
        self._clear_spawn()

    def _tile_seed(self, grid_pos: tuple[int, int]) -> int:
        x, y = grid_pos
        return (x * 92837111 + y * 689287499 + self.seed * 283923481) & 0xFFFFFFFF

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

    def _plate_center(self, cell_x: int, cell_y: int, plate_size: float) -> pygame.Vector2:
        seed = self._hash(cell_x, cell_y, 1001)
        ox = (seed & 0xFFFF) / 0xFFFF
        oy = ((seed >> 16) & 0xFFFF) / 0xFFFF
        return pygame.Vector2((cell_x + ox) * plate_size, (cell_y + oy) * plate_size)

    def _plate_velocity(self, cell_x: int, cell_y: int) -> pygame.Vector2:
        seed = self._hash(cell_x, cell_y, 2002)
        angle = ((seed & 0xFFFF) / 0xFFFF) * math.pi * 2.0
        speed = 0.5 + (((seed >> 16) & 0xFFFF) / 0xFFFF) * 0.5
        return pygame.Vector2(math.cos(angle), math.sin(angle)) * speed

    def _tectonic_fields(self, grid_pos: tuple[int, int]) -> tuple[float, float, float, float, float]:
        x, y = grid_pos
        plate_size = 120.0
        cell_x = int(math.floor(x / plate_size))
        cell_y = int(math.floor(y / plate_size))

        nearest = None
        second = None
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                cx = cell_x + dx
                cy = cell_y + dy
                center = self._plate_center(cx, cy, plate_size)
                dist = (center.x - x) ** 2 + (center.y - y) ** 2
                if nearest is None or dist < nearest[0]:
                    second = nearest
                    nearest = (dist, cx, cy, center)
                elif second is None or dist < second[0]:
                    second = (dist, cx, cy, center)

        if nearest is None or second is None:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        d1 = math.sqrt(nearest[0])
        d2 = math.sqrt(second[0])
        boundary_width = plate_size * 0.25
        boundary = max(0.0, min(1.0, 1.0 - (d2 - d1) / boundary_width))

        normal = second[3] - nearest[3]
        if normal.length_squared() > 0:
            normal = normal.normalize()
        else:
            normal = pygame.Vector2(1.0, 0.0)

        v1 = self._plate_velocity(nearest[1], nearest[2])
        v2 = self._plate_velocity(second[1], second[2])
        v_rel = (v2 - v1).dot(normal)
        convergence = max(0.0, -v_rel)
        divergence = max(0.0, v_rel)

        base_height = self._value_noise(x, y, 140.0, 17) * 0.25
        base_height += self._value_noise(x, y, 60.0, 29) * 0.15
        base_height += 0.32
        uplift = convergence * boundary * 0.35
        rift = divergence * boundary * 0.25
        ridge = abs(self._value_noise(x, y, 14.0, 401) - 0.5) * 0.12 * boundary
        basin = (0.42 - self._value_noise(x, y, 200.0, 601)) * 0.12
        height = base_height + uplift - rift + ridge + basin
        height = max(0.0, min(1.0, height))

        moisture = self._value_noise(x, y, 90.0, 731)
        moisture = moisture + (0.25 - height * 0.25)
        moisture = max(0.0, min(1.0, moisture))

        return height, moisture, boundary, convergence, divergence

    def _generate_tile(self, grid_pos: tuple[int, int]) -> str:
        x, y = grid_pos
        height, moisture, boundary, convergence, _divergence = self._tectonic_fields((x, y))
        sea_level = 0.33

        warp_x = (self._value_noise(x, y, 70.0, 903) - 0.5) * 18.0
        warp_y = (self._value_noise(x, y, 70.0, 907) - 0.5) * 18.0
        river_noise = abs(self._value_noise(x + warp_x, y + warp_y, 24.0, 901) - 0.5)
        river = river_noise < 0.02 and height > sea_level + 0.02 and moisture > 0.45

        lake_noise = self._value_noise(x, y, 120.0, 615)
        lake = lake_noise < 0.08 and height < sea_level + 0.03 and moisture > 0.5

        if height < sea_level or river or lake:
            return "water"

        if height < sea_level + 0.03:
            return "sand"

        mountain_stress = convergence * boundary
        if height > 0.78 or (mountain_stress > 0.35 and height > 0.7):
            neighbor_heights = [
                self._tectonic_fields((x + 1, y))[0],
                self._tectonic_fields((x - 1, y))[0],
                self._tectonic_fields((x, y + 1))[0],
                self._tectonic_fields((x, y - 1))[0],
            ]
            edge = any(h < 0.72 for h in neighbor_heights)
            if edge:
                entrance_noise = self._value_noise(x, y, 18.0, 1103)
                has_mountain_neighbor = any(h > 0.78 for h in neighbor_heights)
                if entrance_noise < 0.04 and min(neighbor_heights) < 0.7 and has_mountain_neighbor:
                    region = (x // self._cave_region_size, y // self._cave_region_size)
                    count = self._cave_region_counts.get(region, 0)
                    if count < 3:
                        self._cave_region_counts[region] = count + 1
                        return "cave_entrance"
            return "mountain"
        if height > 0.64:
            base_tile = "hill"
        else:
            base_tile = "ground"

        seed = self._tile_seed((x, y))
        seed ^= (seed >> 13)
        seed = (seed * 1274126177) & 0xFFFFFFFF
        roll = (seed % 1000) / 1000.0

        tree_chance = 0.045 + moisture * 0.075 - height * 0.04
        rock_chance = 0.028 + height * 0.075 + boundary * 0.035 - moisture * 0.03
        tree_chance = max(0.018, min(tree_chance, 0.12))
        rock_chance = max(0.018, min(rock_chance, 0.1))

        if base_tile in {"ground", "hill"}:
            if roll < tree_chance:
                return "tree"
            if roll < tree_chance + rock_chance:
                return "rock"
        return base_tile

    def debug_fields(self, grid_pos: tuple[int, int]) -> tuple[float, float, float, float]:
        height, moisture, boundary, convergence, _divergence = self._tectonic_fields(grid_pos)
        return height, moisture, boundary, convergence

    def _clear_spawn(self) -> None:
        for y in range(-1, 2):
            for x in range(-1, 2):
                self.tiles[(x, y)] = "ground"

    def to_grid(self, position_px: pygame.Vector2) -> tuple[int, int]:
        return int(position_px.x // TILE_SIZE), int(position_px.y // TILE_SIZE)

    def tile_at_px(self, position_px: pygame.Vector2) -> str:
        return self.get_tile(self.to_grid(position_px))

    def grid_rect(self, grid_pos: tuple[int, int]) -> pygame.Rect:
        x, y = grid_pos
        return pygame.Rect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE)

    def get_tile(self, grid_pos: tuple[int, int]) -> str:
        tile = self.tiles.get(grid_pos)
        if tile is None:
            tile = self._generate_tile(grid_pos)
            self.tiles[grid_pos] = tile
            if tile == "cave_entrance":
                self._apply_cave_mouth(grid_pos)
        return tile

    def _apply_cave_mouth(self, grid_pos: tuple[int, int]) -> None:
        if grid_pos in self._cave_mouth_done:
            return
        self._cave_mouth_done.add(grid_pos)
        x, y = grid_pos
        choices = [
            ((0, -1), self._tectonic_fields((x, y - 1))[0]),
            ((0, 1), self._tectonic_fields((x, y + 1))[0]),
            ((-1, 0), self._tectonic_fields((x - 1, y))[0]),
            ((1, 0), self._tectonic_fields((x + 1, y))[0]),
        ]
        direction, _ = min(choices, key=lambda item: item[1])
        dx, dy = direction
        mouth_pos = (x + dx, y + dy)
        mouth_tile = self._mouth_tile_for_dir(direction)
        self._set_if_allowed(mouth_pos, mouth_tile, allowed={"ground", "hill", "scree"})

        for oy in range(-2, 3):
            for ox in range(-2, 3):
                if abs(ox) + abs(oy) > 2:
                    continue
                if (ox * dx + oy * dy) <= 0:
                    continue
                pos = (x + ox, y + oy)
                if pos == grid_pos:
                    continue
                if pos == mouth_pos:
                    continue
                self._set_if_allowed(pos, "scree", allowed={"mountain", "hill"})

    def _mouth_tile_for_dir(self, direction: tuple[int, int]) -> str:
        dx, dy = direction
        if dx == 0 and dy == -1:
            return "cave_mouth_n"
        if dx == 0 and dy == 1:
            return "cave_mouth_s"
        if dx == -1 and dy == 0:
            return "cave_mouth_w"
        return "cave_mouth_e"

    def _set_if_allowed(
        self,
        grid_pos: tuple[int, int],
        tile: str,
        allowed: set[str] | None = None,
    ) -> None:
        current = self.tiles.get(grid_pos)
        if current is None:
            current = self._approx_tile_type(grid_pos)
        if allowed is None:
            allowed = {"mountain", "hill", "ground"}
        if current in allowed:
            self.set_tile(grid_pos, tile)

    def _approx_tile_type(self, grid_pos: tuple[int, int]) -> str:
        x, y = grid_pos
        height, moisture, _boundary, _convergence, _divergence = self._tectonic_fields((x, y))
        sea_level = 0.33
        warp_x = (self._value_noise(x, y, 70.0, 903) - 0.5) * 18.0
        warp_y = (self._value_noise(x, y, 70.0, 907) - 0.5) * 18.0
        river_noise = abs(self._value_noise(x + warp_x, y + warp_y, 24.0, 901) - 0.5)
        river = river_noise < 0.02 and height > sea_level + 0.02 and moisture > 0.45
        lake_noise = self._value_noise(x, y, 120.0, 615)
        lake = lake_noise < 0.08 and height < sea_level + 0.03 and moisture > 0.5
        if height < sea_level or river or lake:
            return "water"
        if height < sea_level + 0.03:
            return "sand"
        if height > 0.78:
            return "mountain"
        if height > 0.64:
            return "hill"
        return "ground"

    def set_tile(self, grid_pos: tuple[int, int], tile: str) -> None:
        self.tiles[grid_pos] = tile
        self._mark_chunks_dirty(grid_pos)

    def is_blocking(self, tile: str) -> bool:
        return tile in {"tree", "rock", "wall", "workbench", "furnace", "mountain", "crate", "stone_wall"}

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

                if tile == "ground":
                    if self.get_tile((x, y - 1)) == "sand":
                        surface.blit(textures.edge("ground", "sand", "n"), rect)
                    if self.get_tile((x, y + 1)) == "sand":
                        surface.blit(textures.edge("ground", "sand", "s"), rect)
                    if self.get_tile((x - 1, y)) == "sand":
                        surface.blit(textures.edge("ground", "sand", "w"), rect)
                    if self.get_tile((x + 1, y)) == "sand":
                        surface.blit(textures.edge("ground", "sand", "e"), rect)
                elif tile == "sand":
                    if self.get_tile((x, y - 1)) == "water":
                        surface.blit(textures.edge("sand", "water", "n"), rect)
                    if self.get_tile((x, y + 1)) == "water":
                        surface.blit(textures.edge("sand", "water", "s"), rect)
                    if self.get_tile((x - 1, y)) == "water":
                        surface.blit(textures.edge("sand", "water", "w"), rect)
                    if self.get_tile((x + 1, y)) == "water":
                        surface.blit(textures.edge("sand", "water", "e"), rect)

        return surface

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
                if tile not in {"tree", "rock", "crate"}:
                    continue
                tile_center = pygame.Vector2((x + 0.5) * TILE_SIZE, (y + 0.5) * TILE_SIZE)
                dist = tile_center.distance_to(position_px)
                if best is None or dist < best_dist:
                    best = ((x, y), tile)
                    best_dist = dist
        return best

    def find_tile_near(self, position_px: pygame.Vector2, target: str, radius: int = 1) -> tuple[int, int] | None:
        center = self.to_grid(position_px)
        for y in range(center[1] - radius, center[1] + radius + 1):
            for x in range(center[0] - radius, center[0] + radius + 1):
                if self.get_tile((x, y)) == target:
                    return (x, y)
        return None

    def draw(self, surface: pygame.Surface, camera, textures, time_ms: int, debug_view: bool) -> None:
        offset = camera.offset
        screen_w, screen_h = surface.get_size()
        start_x = int(offset.x // TILE_SIZE) - 1
        end_x = int((offset.x + screen_w) // TILE_SIZE) + 1
        start_y = int(offset.y // TILE_SIZE) - 1
        end_y = int((offset.y + screen_h) // TILE_SIZE) + 1

        if debug_view:
            for y in range(start_y, end_y + 1):
                for x in range(start_x, end_x + 1):
                    tile = self.get_tile((x, y))
                    rect = pygame.Rect(
                        int(x * TILE_SIZE - offset.x),
                        int(y * TILE_SIZE - offset.y),
                        TILE_SIZE,
                        TILE_SIZE,
                    )
                    surface.blit(textures.tile_at(tile, (x, y), time_ms), rect)
                    height, moisture, boundary, _convergence = self.debug_fields((x, y))
                    overlay = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
                    overlay.fill(
                        (
                            int(height * 255),
                            int(moisture * 255),
                            int(boundary * 255),
                            90,
                        )
                    )
                    surface.blit(overlay, rect)
            return

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

        for y in range(start_y, end_y + 1):
            for x in range(start_x, end_x + 1):
                if self.get_tile((x, y)) != "water":
                    continue
                rect = pygame.Rect(
                    int(x * TILE_SIZE - offset.x),
                    int(y * TILE_SIZE - offset.y),
                    TILE_SIZE,
                    TILE_SIZE,
                )
                surface.blit(textures.tile_at("water", (x, y), time_ms), rect)
