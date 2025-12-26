from __future__ import annotations

from dataclasses import dataclass, field

import pygame


@dataclass
class UIState:
    build_mode: bool = False
    build_item: str = "wall"
    hotbar_slots: list[str | None] = field(
        default_factory=lambda: ["wall", "floor", "door", "workbench", "crate"]
    )
    crafting_scroll: int = 0
    dragging_item: tuple[str, str] | None = None
    inventory_open: bool = False
    debug_view: bool = False
    npc_debug_view: bool = False
    civ_debug_view: bool = False
    selected_group_id: int | None = None
    selected_npc_id: int | None = None
    group_panel_rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    minimap_zoom: int = 1
    map_open: bool = False
    map_center: pygame.Vector2 = field(default_factory=lambda: pygame.Vector2(0, 0))
    map_dragging: bool = False
    map_last_mouse: pygame.Vector2 = field(default_factory=lambda: pygame.Vector2(0, 0))
    map_rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    map_scale: float = 1.0


@dataclass
class ActionState:
    demolish_target: tuple[int, int] | None = None
    demolish_timer: float = 0.0
    demolish_tile: str | None = None
    gather_target: tuple[int, int] | None = None
    gather_tile: str | None = None
    gather_timer: float = 0.0
    smelt_timer: float = 0.0
    status_message: str | None = None
    status_timer: float = 0.0
