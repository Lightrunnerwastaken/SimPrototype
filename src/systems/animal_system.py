import random

import pygame

from src.constants import TILE_SIZE
from src.entity import Animal, Player, Carcass
from src.effects import HeartEffect
from src.vegetation import PlantManager
from src.systems.movement_helpers import random_dir, resolve_move_dir
from src.systems.movement_system import move_agent
from src.world import World
from src.cave_world import CaveWorld


def separation_force(animal: Animal, animals: list[Animal], radius: float = 24.0) -> pygame.Vector2:
    force = pygame.Vector2(0, 0)
    count = 0
    for other in animals:
        if other is animal or other.species != animal.species:
            continue
        delta = animal.position - other.position
        dist = delta.length()
        if 0 < dist < radius:
            force += delta.normalize() * (radius - dist) / radius
            count += 1
    if count > 0:
        force /= count
    return force


def update_animals(
    animals: list[Animal],
    player: Player,
    world: World | CaveWorld,
    plants: PlantManager,
    carcasses: list[Carcass],
    hearts: list[HeartEffect],
    dt: float,
) -> None:
    herbivores = [a for a in animals if a.species in {"deer", "rabbit"}]
    wolves = [a for a in animals if a.species == "wolf"]

    removed: set[Animal] = set()
    newborns: list[Animal] = []
    for carcass in list(carcasses):
        carcass.decay_timer -= dt
        if carcass.decay_timer <= 0:
            carcasses.remove(carcass)

    for animal in animals:
        if animal in removed:
            continue
        if animal.hit_timer > 0:
            animal.hit_timer = max(0.0, animal.hit_timer - dt)
        if animal.attack_cooldown > 0:
            animal.attack_cooldown = max(0.0, animal.attack_cooldown - dt)
        move_dir = pygame.Vector2(0, 0)
        speed = 0.0
        animal.hunger = min(1.0, animal.hunger + dt * 0.015)
        if animal.mate_cooldown > 0:
            animal.mate_cooldown = max(0.0, animal.mate_cooldown - dt)

        if animal.species == "spider":
            player_delta = player.position - animal.position
            player_dist = player_delta.length()
            if player_dist > 0 and player_dist < 200:
                move_dir = player_delta.normalize()
                speed = 95
                if player_dist < 18 and animal.attack_cooldown <= 0 and player.damage_cooldown <= 0:
                    player.hp = max(0.0, player.hp - 2.0)
                    player.damage_cooldown = 0.6
                    animal.attack_cooldown = 0.8
            else:
                animal.state_timer -= dt
                if animal.state_timer <= 0 or animal.wander_dir.length_squared() == 0:
                    animal.wander_dir = random_dir()
                    animal.state_timer = random.uniform(0.8, 2.2)
                move_dir = animal.wander_dir
                speed = 40
            move_dir = resolve_move_dir(animal, move_dir, world)
            desired_vel = move_dir * speed
            animal.velocity += (desired_vel - animal.velocity) * min(1.0, dt * 6.0)
            if animal.velocity.length_squared() > 0.01:
                move_agent(animal, animal.velocity.normalize(), dt, world, animal.velocity.length(), can_swim=False)
            continue

        if animal.species == "wolf":
            animal.eat_timer = 0.0
            carcass_target = None
            carcass_dist = None
            for carcass in carcasses:
                dist = carcass.position.distance_to(animal.position)
                if carcass_target is None or dist < carcass_dist:
                    carcass_target = carcass
                    carcass_dist = dist
            rival = None
            rival_dist = None
            if carcass_target is not None:
                for other in wolves:
                    if other is animal or other in removed:
                        continue
                    dist_to_carcass = other.position.distance_to(carcass_target.position)
                    if dist_to_carcass < 26:
                        if rival is None or dist_to_carcass < rival_dist:
                            rival = other
                            rival_dist = dist_to_carcass
                if rival is not None and animal.position.distance_to(rival.position) < 24:
                    animal.contest_timer = 0.3

            if animal.contest_timer > 0:
                animal.contest_timer = max(0.0, animal.contest_timer - dt)
                if rival is not None:
                    move_dir = (animal.position - rival.position).normalize()
                else:
                    move_dir = random_dir()
                speed = 75
                move_dir = resolve_move_dir(animal, move_dir, world)
                desired_vel = move_dir * speed
                animal.velocity += (desired_vel - animal.velocity) * min(1.0, dt * 6.0)
                continue
            if animal.hunger > 0.4 and carcass_target is not None and carcass_dist is not None and carcass_dist < 30:
                carcass_target.eat_timer += dt
                animal.eat_timer = carcass_target.eat_timer
                if carcass_target.eat_timer >= 1.0:
                    carcass_target.eat_timer = 0.0
                    carcass_target.bites_left -= 1
                    animal.hunger = max(0.0, animal.hunger - 0.5)
                    if carcass_target.bites_left <= 0:
                        carcasses.remove(carcass_target)
                speed = 0.0
                move_dir = pygame.Vector2(0, 0)
                move_dir = resolve_move_dir(animal, move_dir, world)
                desired_vel = move_dir * speed
                animal.velocity += (desired_vel - animal.velocity) * min(1.0, dt * 6.0)
                continue
            elif animal.hunger > 0.4 and carcass_target is not None and carcass_dist is not None:
                move_dir = (carcass_target.position - animal.position).normalize()
                speed = 85
                move_dir = resolve_move_dir(animal, move_dir, world)
                desired_vel = move_dir * speed
                animal.velocity += (desired_vel - animal.velocity) * min(1.0, dt * 6.0)
                continue
            if animal.chase_timer > 0:
                animal.chase_timer = max(0.0, animal.chase_timer - dt)
            if animal.chase_target in removed:
                animal.chase_target = None

            target = animal.chase_target
            target_dist = None
            if target is not None:
                target_dist = (target.position - animal.position).length()
                if target_dist > 240:
                    target = None
            if target is None:
                for herb in herbivores:
                    if herb in removed:
                        continue
                    dist = (herb.position - animal.position).length()
                    if dist < 220 and (target is None or dist < target_dist):
                        target = herb
                        target_dist = dist
                animal.chase_target = target
                animal.chase_timer = 0.6

            if animal.hunger > 0.6 and target is not None and target_dist is not None:
                if target_dist < 14:
                    removed.add(target)
                    animal.hunger = max(0.0, animal.hunger - 0.8)
                    carcasses.append(Carcass(target.position, bites=3))
                    animal.chase_target = None
                    continue
                move_dir = (target.position - animal.position).normalize()
                speed = 100
            else:
                if animal.mate_cooldown == 0 and animal.hunger < 0.3:
                    for mate in wolves:
                        if mate is animal or mate in removed:
                            continue
                        if mate.mate_cooldown > 0 or mate.hunger >= 0.3:
                            continue
                        if mate.position.distance_to(animal.position) < 28:
                            baby_pos = animal.position + pygame.Vector2(random.uniform(-8, 8), random.uniform(-8, 8))
                            newborns.append(Animal("wolf", baby_pos))
                            animal.mate_cooldown = 10.0
                            mate.mate_cooldown = 10.0
                            hearts.append(HeartEffect(animal.position + pygame.Vector2(0, -12)))
                            break
                animal.state_timer -= dt
                if animal.state_timer <= 0 or animal.wander_dir.length_squared() == 0:
                    animal.wander_dir = random_dir()
                    animal.state_timer = random.uniform(1.2, 3.5)
                move_dir = animal.wander_dir
                speed = 45
        else:
            threat_vec = pygame.Vector2(0, 0)
            threat_count = 0
            for wolf in wolves:
                if wolf in removed:
                    continue
                delta = animal.position - wolf.position
                dist = delta.length()
                if dist < 220 and dist > 0:
                    threat_vec += delta.normalize() * (1.0 / max(1.0, dist))
                    threat_count += 1
            player_delta = animal.position - player.position
            player_dist = player_delta.length()
            if player_dist < 180 and player_dist > 0:
                threat_vec += player_delta.normalize() * (1.0 / max(1.0, player_dist))
                threat_count += 1

            if threat_count > 0:
                animal.flee_dir = threat_vec.normalize()
                animal.flee_timer = 0.5
                move_dir = animal.flee_dir
                speed = 140 if animal.species == "rabbit" else 105
                animal.eat_timer = 0.0
            elif animal.flee_timer > 0:
                animal.flee_timer = max(0.0, animal.flee_timer - dt)
                move_dir = animal.flee_dir
                speed = 120 if animal.species == "rabbit" else 95
                animal.eat_timer = 0.0
            elif animal.hunger > 0.5:
                plant = plants.find_near(animal.position, radius_tiles=2)
                if plant is not None:
                    animal.eat_target = plant
                    animal.eat_timer += dt
                    if animal.eat_timer >= 1.2:
                        plants.consume(plant)
                        animal.eat_timer = 0.0
                        animal.hunger = max(0.0, animal.hunger - 0.6)
                    speed = 0.0
                    move_dir = pygame.Vector2(0, 0)
                else:
                    animal.eat_timer = 0.0
            else:
                animal.eat_timer = 0.0
                if animal.mate_cooldown == 0 and animal.hunger < 0.3:
                    for mate in herbivores:
                        if mate is animal or mate in removed or mate.species != animal.species:
                            continue
                        if mate.mate_cooldown > 0 or mate.hunger >= 0.3:
                            continue
                        if mate.position.distance_to(animal.position) < 26:
                            baby_pos = animal.position + pygame.Vector2(random.uniform(-8, 8), random.uniform(-8, 8))
                            newborns.append(Animal(animal.species, baby_pos))
                            animal.mate_cooldown = 10.0
                            mate.mate_cooldown = 10.0
                            hearts.append(HeartEffect(animal.position + pygame.Vector2(0, -12)))
                            break
                animal.state_timer -= dt
                if animal.state_timer <= 0 or animal.wander_dir.length_squared() == 0:
                    animal.wander_dir = random_dir()
                    animal.state_timer = random.uniform(1.2, 3.5)
                move_dir = animal.wander_dir
                speed = 55 if animal.species == "rabbit" else 45

        move_dir += separation_force(animal, animals) * 0.4
        move_dir = resolve_move_dir(animal, move_dir, world)
        desired_vel = move_dir * speed
        animal.velocity += (desired_vel - animal.velocity) * min(1.0, dt * 6.0)
        if animal.velocity.length_squared() > 0.01:
            move_agent(animal, animal.velocity.normalize(), dt, world, animal.velocity.length(), can_swim=False)

    if removed:
        animals[:] = [a for a in animals if a not in removed]
    if newborns:
        animals.extend(newborns)


def spawn_animals(
    animals: list[Animal],
    player: Player,
    world: World,
    species: str,
    target_count: int,
    radius_tiles: int = 18,
) -> None:
    center = world.to_grid(player.position)
    count = sum(
        1
        for a in animals
        if a.species == species and (a.position - player.position).length() < radius_tiles * TILE_SIZE
    )
    missing = target_count - count
    if missing <= 0:
        return
    spawned_positions = {world.to_grid(a.position) for a in animals if a.species == species}
    for _ in range(missing):
        for _attempt in range(20):
            dx = random.randint(-radius_tiles, radius_tiles)
            dy = random.randint(-radius_tiles, radius_tiles)
            gx = center[0] + dx
            gy = center[1] + dy
            if (gx, gy) in spawned_positions:
                continue
            too_close = False
            for sx, sy in spawned_positions:
                if abs(sx - gx) + abs(sy - gy) < 4:
                    too_close = True
                    break
            if too_close:
                continue
            tile = world.get_tile((gx, gy))
            if tile in {"water", "mountain"}:
                continue
            pos = pygame.Vector2((gx + 0.5) * TILE_SIZE, (gy + 0.5) * TILE_SIZE)
            animals.append(Animal(species, pos))
            spawned_positions.add((gx, gy))
            break


def spawn_cave_spiders(
    animals: list[Animal],
    player: Player,
    world: CaveWorld,
    target_count: int,
    radius_tiles: int = 12,
) -> None:
    center = world.to_grid(player.position)
    count = sum(
        1
        for a in animals
        if a.species == "spider" and (a.position - player.position).length() < radius_tiles * TILE_SIZE
    )
    missing = target_count - count
    if missing <= 0:
        return
    spawned_positions = {world.to_grid(a.position) for a in animals if a.species == "spider"}
    for _ in range(missing):
        for _attempt in range(22):
            dx = random.randint(-radius_tiles, radius_tiles)
            dy = random.randint(-radius_tiles, radius_tiles)
            gx = center[0] + dx
            gy = center[1] + dy
            if abs(dx) + abs(dy) < 3:
                continue
            if (gx, gy) in spawned_positions:
                continue
            tile = world.get_tile((gx, gy))
            if tile not in {"cave_floor", "cave_exit"}:
                continue
            pos = pygame.Vector2((gx + 0.5) * TILE_SIZE, (gy + 0.5) * TILE_SIZE)
            animals.append(Animal("spider", pos))
            spawned_positions.add((gx, gy))
            break
