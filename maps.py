#!/usr/bin/env python3

import libtcodpy as libtcod

from monsters import Monster
from player import Player
from interfaces import Mappable, Position, Traversable, Transparent, StatusEffect, LightSource
from items import Item, Evidence
from tiles import Tile, Wall, Floor, Light, FlatLight, Door, StairsDown, StairsUp, MapPattern, CanHaveEvidence
from errors import InvalidMoveError

from functools import reduce


class Map:
    """Map of Mappable objects, representing the game map currently in play."""
    __layer_order = [Tile, Item, Monster, Player]

    def __init__(self, seed, size, player):
        """seed is the RNG seed to use for generating the map; size is a Position instance giving the map size
        and player is a valid Player object."""
        self.player = player
        self.__layers = {
            Player: {},
            Monster: {},
            Item: {},
            Tile: {},
            }
        if seed is None:
            self.map_rng = None
        else:
            self.map_rng = libtcod.random_new_from_seed(seed)
        self.size = size
        self.__tcod_map_empty             = libtcod.map_new(self.size.x, self.size.y) # for xray, audio, ghosts(?)
        libtcod.map_clear(self.__tcod_map_empty, True, True)               # clear the map to be traversable and visible
        self.__tcod_map                   = libtcod.map_new(self.size.x, self.size.y) # for pathing and rendering
        self.__tcod_pathfinder            = None
        self.__tcod_static_light_console  = libtcod.console_new(self.size.x, self.size.y)  # stores cumulative light data
        self.__tcod_moving_light_console  = libtcod.console_new(self.size.x, self.size.y)
        libtcod.console_set_default_background(self.__tcod_static_light_console, Mappable.LIGHT_L_CLAMP)
        #litbcod.console_set_default_background(self.__tcod_moving_light_console, Mappable.LIGHT_L_CLAMP)
        self._dirty_pos                   = []

    def __get_layer_from_obj(self, obj):
        """Return which map layer obj is in"""
        for l in self.__layer_order:
            if isinstance(obj, l):
                return l
        assert False, "No map layer for %s" % obj

    def add(self, obj, layer=None):
        """add object obj to given map layer. If omitted, relevant layer is calculated"""
        assert isinstance(obj, Mappable), "%s cannot appear on map" % obj
        if layer is None:
            layer = self.__get_layer_from_obj(obj)
        self.__layers[layer].setdefault(obj.pos, []).append(obj)
        obj.map = self

    def remove(self, obj, layer=None):
        """remove object obj from given map layer, or first layer found if none given."""
        assert isinstance(obj, Mappable), "%s cannot appear on map" % obj
        if layer is None:
            layer = self.__get_layer_from_obj(obj)

        assert obj.pos in self.__layers[layer].keys(), "%s not found at %s in layer %s" % (obj, obj.pos, layer)

        self.__layers[layer][obj.pos].remove(obj)
        if len(self.__layers[layer][obj.pos]) == 0:
            del self.__layers[layer][obj.pos]
        obj.map = None
        obj.pos = None

    def move(self, obj, pos, layer=None):
        """move object obj on map to position pos. Provide correct layer for more efficient calculation.
        NB. setting a Mappable's pos directly will break stuff."""
        assert isinstance(obj, Mappable), "%s cannot appear on map" % obj
        assert not obj.map is None, "%s not added to map" % obj
        r = 0.0

        # check that destination is within map bounds
        if pos.x > self.size.x or pos.x < 0 or pos.y > self.size.y or pos.y < 0:
            raise InvalidMoveError

        # check that we can move from current pos
        srcs  = self.find_all_at_pos(obj.pos, Tile) # probably just Tiles
        for src in srcs:
            if isinstance(src, Traversable):
                if not src.try_leaving(obj):
                    raise InvalidMoveError # TODO: convert to use walk_cost

        # check that we can move to pos
        dests = self.find_all_at_pos(pos, Tile) # probably just Tiles
        for dest in dests:
            if isinstance(dest, Traversable):
                r += dest.try_movement(obj)  # may raise InvalidMoveError

        if layer is None:
            layer = self.__get_layer_from_obj(obj)

        assert obj.pos in self.__layers[layer].keys(), "%s not found at %s in layer %s" % (obj, obj.pos, layer)

        # move obj reference
        self.__layers[layer][obj.pos].remove(obj)
        self.__layers[layer].setdefault(pos, []).append(obj)

        # update obj position
        obj.last_pos = obj.pos
        obj.pos      = pos

        # this is awkward; we want large r to mean "no more turns to have"; but a walk cost of 0.0 means no move
        return r > 0.0 and r <= 1.0 and 1.0 - r or r

    def find_all(self, otype, layer=None):
        """find all type otype in layer (or whole map if layer not given)"""
        layers = [layer]
        if layer is None:
            layers = self.__layer_order

        # fast if asking for a layer
        if otype in layers:
            return reduce(lambda a, b: a + b, self.__layers[otype].values(), [])

        r = []
        for layer in layers:
            for ol in self.__layers[layer].values():
                r += [o for o in ol if isinstance(o, otype)]
        return r

    def find_nearest(self, obj, otype, layer=None, must_be_visible=True):
        """find nearest thing of type otype to obj. Can limit by map layer and whether visible (i.e. drawn)"""
        # TODO: match arg order with find_within_r and find_all
        r = 10000000 # safely larger than the map
        ro = None

        for o in self.find_all(otype, layer):
            if obj is o or (must_be_visible and not o.is_visible):
                continue
            d = obj.pos.distance_to(o.pos)
            if d < r:
                r  = d
                ro = o
        return ro

    def find_all_within_r(self, obj, otype, radius, must_be_visible=True, layer=None):
        """find all type otype in radius of obj. Can limit by map layer and whether visible (i.e. drawn)"""
        # TODO: there might be a more efficient way to do this using another FOV map from TCOD
        ret = []
        for o in self.find_all(otype, layer):
            if obj is o or (must_be_visible and not o.is_visible):
                continue
            if obj.pos.distance_to(o.pos) < radius:
                ret.append(o)
        return ret

    def find_random_clear(self, rng=None):
        """find random clear cell in map, using given RNG, or TCOD default if none supplied"""
        # assumes that 2+ tiles in the same space means a door/crate/what-have-you
        occupied = list(self.__layers[Player].keys()) + list(self.__layers[Monster].keys()) \
            + [t[0] for t in self.__layers[Tile].items() if t[1][0].blocks_movement() and len(t[1]) == 0]

        while 1:
            p = Position(libtcod.random_get_int(rng, 0, self.size.x - 1),
                         libtcod.random_get_int(rng, 0, self.size.y - 1))
            if not p in occupied and not self.is_blocked(p):
                return p

    def find_at_pos(self, pos, layer=None):
        """find first object at pos in layer(s), or any layer if none supplied.
        Returns None if nothing found"""
        layers = [layer]
        if layer is None:
            layers = self.__layer_order

        for l in layers:
            if pos in self.__layers[l].keys() and len(self.__layers[l][pos])>0:
                return self.__layers[l][pos][0]

        return None

    def find_all_at_pos(self, pos, layers=None):
        """find all objects at pos in layer(s), or any layer if none supplied.
        Returns empty list if nothing found"""
        if layers is None:
            layers = self.__layer_order
        elif not isinstance(layers, list):
            layers = [layers]
        r = []
        for l in layers:
            if pos in self.__layers[l].keys():
                r += self.__layers[l][pos]
        return r

    def get_walk_cost(self, pos):
        """get walk cost of traversing pos"""
        obj = self.find_at_pos(pos, Tile)
        if isinstance(obj, Traversable):
            return obj.walk_cost
        else:
            # can't traverse an empty space and objects that don't implement Traversable
            return 0.0

    def is_blocked(self, pos):
        """whether objects at pos completely block movement or not"""
        obj = self.find_at_pos(pos, Tile)
        if isinstance(obj, Traversable):
            return obj.blocks_movement()
        else:
            return True

    def draw(self):
        """draw the map on screen"""
        for layer in self.__layer_order:
            for d in self.__layers[layer].values():
                for o in d:
                    o.draw()

    def recalculate_dirty(self):
        """recalculate paths and lighting, where necessary"""
        if len(self._dirty_pos) > 0:
            self.recalculate_paths(self._dirty_pos, force_now=True)
            self._dirty_pos = []
        self.recalculate_lighting(self.player.pos, statics=False)

    def recalculate_paths(self, pos=None, is_for_mapping=False, force_now=False):
        """Recalculates pathing information. If a list of pos given, assume only those positions have changed state.
        If is_for_mapping is set, don't count things like teleports as traversable.
        If force_now not set, flag positions as dirty but do no calculations yet"""
        #print("%d: RECALCULATING PATHS%s!"%(self.player.turns,pos is None and " FOR ALL" or " AT %s"%pos))

        if pos is None:
            libtcod.map_clear(self.__tcod_map)
            for ol in self.__layers[Tile].values():
                for o in ol:
                    is_walkable = (isinstance(o, Traversable) and (not o.blocks_movement(is_for_mapping)))
                    is_transparent = (isinstance(o, Transparent) and not o.blocks_light())
                    libtcod.map_set_properties(self.__tcod_map, o.pos.x, o.pos.y, is_transparent, is_walkable)
        else:
            if not isinstance(pos, list):
                pos = [pos]
            if not force_now:
                self._dirty_pos += pos
                return
            for p in pos:
                for o in self.__layers[Tile].get(p, []):
                    is_walkable = (isinstance(o, Traversable) and (not o.blocks_movement(is_for_mapping)))
                    is_transparent = (isinstance(o, Transparent) and not o.blocks_light())
                    libtcod.map_set_properties(self.__tcod_map, o.pos.x, o.pos.y, is_transparent, is_walkable)

        #self.__tcod_pathfinder = libtcod.path_new_using_map(self.__tcod_map)
        self.__tcod_pathfinder = libtcod.dijkstra_new(self.__tcod_map)

        # lighting needs updating too
        if not is_for_mapping:
            self.recalculate_lighting(pos)

    def prepare_fov(self, pos, radius=0, reset=True):
        """recalculate player fov at pos with optional radius. Set reset=False to accumulate multiple fovs"""
        libtcod.map_compute_fov(self.__tcod_map_empty, pos.x, pos.y, radius, True, libtcod.FOV_BASIC)
        libtcod.map_compute_fov(self.__tcod_map, pos.x, pos.y, radius, True, libtcod.FOV_BASIC)

        for layer in self.__layer_order:
            for (pos, ts) in self.__layers[layer].items():
                if self._drawing_can_see(pos):
                    for t in ts:
                        t.visible_to_player = True
                elif reset:
                    for t in ts:
                        t.visible_to_player = False

    def recalculate_lighting(self, pos=None, statics=True):
        """recalculate lighting of each mappable. pos indicates position(s) that has changed transparency.
        Set statics to false if only calculating moving light sources"""
        # there are two maps for light; one of static objects that only gets refreshed when tiles and other fixed
        # mappables change state (e.g. doors opening); and one for moving objects, that gets refreshed every turn
        #
        #  * individual light coverage maps are handled as images that are blitted to a console
        #  * the console is subsequently queried by the map for LOS and drawing
        #  * moving lights need to be calculating using whole map LOS

        lights = self.find_all(LightSource)

        # TODO: optimise for pos=foo

        # reset light levels for every light source
        if statics:
            libtcod.console_clear(self.__tcod_static_light_console)
        libtcod.console_clear(self.__tcod_moving_light_console)

        for l in lights:
            if l.remains_in_place:
                if statics:
                    l.reset_map(pos)
                    l.blit_to(self.__tcod_static_light_console)
            else:
                # TODO: optimise!
                l.reset_map()
                l.blit_to(self.__tcod_moving_light_console)

    def is_lit(self, obj):
        """is obj lit enough to be visible?"""
        print("got here %s %s" % (obj, obj.current_effects))
        if isinstance(obj, StatusEffect) and obj.has_effect(StatusEffect.HIDDEN_IN_SHADOW):
            return self.light_level(obj.pos) >= LightSource.INTENSITY_VISIBLE * 2.0
        else:
            return self.light_level(obj.pos) >= LightSource.INTENSITY_VISIBLE  # INTENSITY_L_CLAMP

    def light_level(self, pos):
        """returns a float representing light level/colour at pos"""
        return libtcod.color_get_hsv(libtcod.console_get_char_background(
                self.__tcod_static_light_console, pos.x, pos.y))[2] \
            + libtcod.color_get_hsv(libtcod.console_get_char_background(
                self.__tcod_moving_light_console, pos.x, pos.y))[2]

    def light_colour(self, pos):
        """returns colour of light at pos, incorporating intensity"""
        return libtcod.console_get_char_background(self.__tcod_static_light_console, pos.x, pos.y) \
            + libtcod.console_get_char_background(self.__tcod_moving_light_console, pos.x, pos.y)

    def debug_lighting(self):
        """blit static and moving light maps to console"""
        libtcod.console_blit(self.__tcod_static_light_console, 0, 0, 0, 0, 0, 0, 0, 0.5, 1.0)
        libtcod.console_flush()
        libtcod.console_wait_for_keypress(True)
        libtcod.console_blit(self.__tcod_moving_light_console, 0, 0, 0, 0, 0, 0, 0, 0.5, 1.0)
        libtcod.console_flush()
        libtcod.console_wait_for_keypress(True)

    def can_see(self, obj, target=None, angle_of_vis=1.0):
        """default is: can obj see player? if target is given, this becomes: can obj see target?
        angle_of_vis between 0.0 and 1.0 where 0.0 is blind and 1.0 can see all around"""
        # TODO: handle x-ray vision here
        assert isinstance(obj, Mappable), "%s can't be tested for visibility" % obj
        if target is None or target is self.player:
            if isinstance(obj, StatusEffect) and obj.has_effect(StatusEffect.BLIND):
                return False
            #if angle_of_vis<1.0:
            #    print("angle from %s to %s is %f"%(obj,self.player,(obj.pos-obj.last_pos).angle_to(self.player.pos-obj.pos)))
            #
            #    travelling S:     pos-last_pos == (0,1)
            #    player in-front:  player.pos-obj.pos  must (0, >0)
            return self.player.is_visible \
                and self.is_lit(self.player) \
                and libtcod.map_is_in_fov(self.__tcod_map, obj.pos.x, obj.pos.y) \
                and (angle_of_vis == 1.0 or (obj.pos - obj.last_pos).angle_to(self.player.pos - obj.pos) <= angle_of_vis)
        elif obj is self.player:
            return obj.is_visible and self.is_lit(obj) and libtcod.map_is_in_fov(self.__tcod_map, obj.pos.x, obj.pos.y)
        else:
            raise NotImplementedError

    def _drawing_can_see(self, pos):
        """can player see pos [FOR DRAWING!]"""
        # ONLY FOR DRAWING!!
        if self.player.has_effect(StatusEffect.X_RAY_VISION):
            return libtcod.map_is_in_fov(self.__tcod_map_empty, pos.x, pos.y)
        else:
            return libtcod.map_is_in_fov(self.__tcod_map, pos.x, pos.y)

    def get_path(self, from_pos, to_pos, steps=None):
        """gets array of Position objects from from_pos to to_pos. set steps to limit number of objects to return"""
        #libtcod.path_compute(self.__tcod_pathfinder,from_pos.x,from_pos.y,to_pos.x,to_pos.y)
        # TODO: can i compute one of these for each cell on the map and cache the results, indexed by pos?
        libtcod.dijkstra_compute(self.__tcod_pathfinder, from_pos.x, from_pos.y)
        libtcod.dijkstra_path_set(self.__tcod_pathfinder, to_pos.x, to_pos.y)

        if steps is None:
            steps = libtcod.dijkstra_size(self.__tcod_pathfinder)

        p = []
        for i in range(steps):
            x, y = libtcod.dijkstra_get(self.__tcod_pathfinder, i)
            p.append(Position(x, y))

        return p

    def close(self):
        """close map (prior to deletion)"""
        #libtcod.path_delete(self.__tcod_pathfinder)
        if not self.__tcod_pathfinder is None:
            libtcod.dijkstra_delete(self.__tcod_pathfinder)
        libtcod.map_delete(self.__tcod_map)
        libtcod.map_delete(self.__tcod_map_empty)
        libtcod.console_delete(self.__tcod_static_light_console)
        libtcod.console_delete(self.__tcod_moving_light_console)

    def __del__(self):
        self.close()

    def get_monsters(self):
        """get list of monsters in map"""
        return reduce(lambda a, b: a + b, self.__layers[Monster].values(), [])

    def get_items(self):
        """get list of items in map"""
        return reduce(lambda a, b: a + b, self.__layers[Item].values(), [])

    def generate(self):
        """generate map (for subclasses to implement)"""
        raise NotImplementedError

    def _gen_draw_map_edges(self):
        """draw walls around the very edges of the map"""
        # place map edges
        for i in range(0, self.size.x):
            self.add(Wall(Position(i, 0)))
            self.add(Wall(Position(i, self.size.y - 1)))
        for i in range(1, self.size.y - 1):
            self.add(Wall(Position(0, i)))
            self.add(Wall(Position(self.size.x - 1, i)))

    def _gen_add_evidence(self):
        """add one evidence object to a random map tile"""
        # do some stuff with an evidence object
        e = Evidence(None)

        # figure out where to put it
        OPEN_SPACE_P  = 0.3 # probability weight of evidence being in the open
        hiding_places = self.find_all(CanHaveEvidence, Tile)
        max_p         = reduce(lambda a, b: a + b, [h.evidence_chance for h in hiding_places], 0.0)
        p             = libtcod.random_get_float(self.map_rng, -OPEN_SPACE_P * max_p, max_p)
        if p <= 0.0:
            e.pos = self.find_random_clear(self.map_rng)
            self.add(e)

        else:
            i = -1
            while p > 0:
                i += 1
                p -= hiding_places[i].evidence_chance
            hiding_places[i].evidence = e

    def _gen_add_key_elements(self):
        """add stairs and player"""
        up_pos   = self.find_random_clear(self.map_rng)
        down_pos = self.find_random_clear(self.map_rng)

        self.recalculate_paths(is_for_mapping=True)
        while len(self.get_path(up_pos, down_pos)) < 1:
            up_pos   = self.find_random_clear(self.map_rng)
            down_pos = self.find_random_clear(self.map_rng)

        # place stairs
        self.add(StairsDown(down_pos))
        self.add(StairsUp(up_pos))

        # place player
        self.player.pos = up_pos
        self.add(self.player)

    def _gen_apply_patterns(self, map_array):
        """given a 2d array of MapPattern flags representing a map layout, randomly add features in valid places"""
        # won't return consistently ordered list!
        #for (T,ps) in Tile.get_all_tiles(self.map_rng,map_array).items():
        Tgat = Tile.get_all_tiles(self.map_rng, map_array)
        Ts = [k for k in Tgat.keys()]
        Ts.sort(key=lambda T: T.__name__)
        for T in Ts:
            ps = Tgat[T]
            T_wanted = libtcod.random_get_int(self.map_rng, T.place_min, T.place_max)
            while len(ps) > 0 and T_wanted > 0:
                p = ps.pop()
                if not map_array[p.x][p.y] & MapPattern.SPECIAL:
                    if map_array[p.x][p.y] & (MapPattern.CORRIDOR | MapPattern.ROOM):
                        self.add(Floor(p))
                    self.add(T(p))
                    map_array[p.x][p.y] |= MapPattern.SPECIAL
                    T_wanted -= 1
                
    def _gen_finish(self):
        """call once map gen complete"""
        # calculate path information
        self.recalculate_paths()

        # calculate player's initial fov
        self.player.reset_fov()

    @staticmethod
    def random(seed, size, player):
        """return a random map of size for player using given RNG seed"""
        print(" -- MAP SEED %d --" % seed)
        #return EmptyMap(seed,size,player)
        #return DalekMap(seed,size,player)
        return TypeAMap(seed, size, player)


class EmptyMap(Map):
    """Empty map, no monsters or items"""

    def generate(self):
        """generate"""
        self._gen_draw_map_edges()

        # fill with floor
        for i in range(1, self.size.x - 1):
            for j in range(1, self.size.y - 1):
                self.add(Floor(Position(i, j)))

        # place daleks
        #for i in range(0,1):
        #    d = Monster.random(self.map_rng,self.find_random_clear(self.map_rng))
        #    self.add(d)

        # place some items
        #for i in range(0,3):
        #    i = Item.random(self.map_rng,self.find_random_clear(self.map_rng))
        #    self.add(i)

        # add evidence
        self._gen_add_evidence()

        self._gen_add_key_elements()
        self._gen_finish()


class DalekMap(Map):
    """Simple map with central obstruction, monsters and items."""
    def generate(self):
        self._gen_draw_map_edges()

        # put floor in
        # put a randomly-sized impassable box in the middle
        left_x   = int(libtcod.random_get_float(self.map_rng, 0.1, 0.4) * self.size.x)
        right_x  = int(libtcod.random_get_float(self.map_rng, 0.6, 0.9) * self.size.x)
        top_y    = int(libtcod.random_get_float(self.map_rng, 0.1, 0.4) * self.size.y)
        bottom_y = int(libtcod.random_get_float(self.map_rng, 0.6, 0.9) * self.size.y)
        for i in range(1, self.size.x - 1):
            for j in range(1, self.size.y - 1):
                if i in range(left_x, right_x + 1) and j in range(top_y, bottom_y + 1):
                    if i in (left_x, right_x) or j in (top_y, bottom_y):
                        self.add(Wall(Position(i, j)))
                    else:
                        pass
                else:
                    self.add(Floor(Position(i, j)))

        # place daleks
        for i in range(0, 15):
            d = Monster.random(self.map_rng, self.find_random_clear(self.map_rng))
            self.add(d)

        # place some items
        for i in range(0, 3):
            i = Item.random(self.map_rng, self.find_random_clear(self.map_rng))
            self.add(i)

        # add evidence
        self._gen_add_evidence()

        self._gen_add_key_elements()
        self._gen_finish()


class TypeAMap(Map):
    """Map Layout:
     * corridors of 1 and 2 tile width
     * adjoining rooms with multiple exits and interconnects
     * TODO: sub-partitioned rooms
     * 80-90% of map space used
    """

    COMPASS = { 'N': {'opposite': 'S', 'clockwise': 'E', 'anticlockwise': 'W', 'adjacent': ['W', 'E']},
                'S': {'opposite': 'N', 'clockwise': 'W', 'anticlockwise': 'E', 'adjacent': ['W', 'E']},
                'E': {'opposite': 'W', 'clockwise': 'S', 'anticlockwise': 'N', 'adjacent': ['N', 'S']},
                'W': {'opposite': 'E', 'clockwise': 'N', 'anticlockwise': 'S', 'adjacent': ['N', 'S']},
                }

    CORRIDOR_MAX_BENDS  = 4
    CORRIDOR_LENGTH_VAR = [0.8, 1.3]
    CORRIDOR_MAX_MINOR  = 6
    CORRIDOR_MINOR_LEN  = 60
    CORRIDOR_MINOR_BEND = 1
    CORRIDOR_MINOR_FREQ = 6
    CORRIDOR_MINOR_STEP = 4
    CORRIDOR_MIN_LENGTH = 5
    MIN_ROOMS           = 6
    MAX_ROOMS           = 14
    ROOM_MIN_WIDTH      = 4
    ROOM_MAX_AREA       = 80 * 14 # i.e. approx 1/3rd of screen area
    ROOM_BOUNDARY_STOP  = [1.0, 0.8, 0.6, 0.5]
    REJECT_COVERAGE_PC  = 0.6
    REJECT_COVERAGE_SQ  = 0.8
    SANITY_LIMIT        = 100
    BOUNDARY_UNSET      = -1
    TELEPORT_CHANCE     = 0.2 # just less than 1 per room
    LIGHT_MIN_RADIUS    = 8
    LIGHT_MAX_RADIUS    = 25
    DEBUG               = False

    def __init__(self, seed, size, player):
        """map constructor"""
        Map.__init__(self, seed, size, player)
        self._map = [[]]

    def debug_print(self, s):
        """for debugging map gen code"""
        if self.DEBUG:
            print(s)

    class _ME:
        """private map element class, representing a possible room, corridor or door"""
        def __init__(self, tile_id, pos, size, opos=None, direction=None, length=None):
            if not isinstance(pos, Position):
                pos = Position(pos)
            if not isinstance(size, Position):
                size = Position(size[0], size[1])
            self.tile_id = tile_id
            self.pos = pos
            self.size = size
            # for corridors
            self.opos = opos
            self.direction = direction
            self.length = length
            self.flat_light = False

        def __str__(self):
            if self.direction is None:
                return "Internal map element %d at %s, size %s. pos=%s" % (self.tile_id, self.pos, self.size, self.opos)
            else:
                return "Internal map element %d at %s, size %s. pos=%s, dir=%s, len=%d" % (
                    self.tile_id, self.pos, self.size, self.opos, self.direction, self.length)

        def commit(self, m):
            """applies map element to 2d map array m"""
            assert self.pos.x + self.size.x <= len(m) and self.pos.y + self.size.y <= len(m[0]), \
                "Can't commit %s to grid size (%d,%d)" % (self, len(m), len(m[0]))
            #self.debug_print(".commit %s to grid size (%d,%d)"%(self,len(m),len(m[0])))
            for x in range(self.size.x):
                for y in range(self.size.y):
                    #print(" ... (%d,%d) = %d"%(x+self.pos.x,y+self.pos.y,self.tile_id))
                    m[x + self.pos.x][y + self.pos.y] |= self.tile_id

    def _gen_get_compass_dir(self):
        """get a random compass direction"""
        return ['N', 'S', 'E', 'W'][libtcod.random_get_int(self.map_rng, 0, 3)]

    def _gen_get_compass_turn(self, current_direction):
        """get a random direction 90 deg from current"""
        return TypeAMap.COMPASS[current_direction]['adjacent'][libtcod.random_get_int(self.map_rng, 0, 1)]

    def _gen_get_compass_opposite(self, current_direction):
        """get opposite direction to current"""
        return TypeAMap.COMPASS[current_direction]['opposite']

    def _gen_get_compass_left(self, current_direction):
        """get direction 90 deg left of current"""
        return TypeAMap.COMPASS[current_direction]['anticlockwise']

    def _gen_get_compass_right(self, current_direction):
        """get direction 90 deg right of current"""
        return TypeAMap.COMPASS[current_direction]['clockwise']

    def _gen_get_dir_to_closest_edge(self, pos):
        """get compass direction from pos to nearest edge"""
        half_x = self.size.x // 2
        half_y = self.size.y // 2
        if pos.x < half_x:
            if pos.y < half_y:
                # NW quad
                if pos.x > pos.y:
                    return 'N'
                else:
                    return 'W'
            else:
                # SW quad
                if pos.x > self.size.y - pos.y:
                    return 'S'
                else:
                    return 'W'
        else:
            if pos.y < half_y:
                # NE quad
                if self.size.x - pos.x > pos.y:
                    return 'N'
                else:
                    return 'E'
            else:
                # SE quad
                if pos.x > pos.y:
                    return 'E'
                else:
                    return 'S'

    def _gen_get_dir_to_furthest_edge(self, pos):
        """get compass direction from pos to furthest edge"""
        return self._gen_compass_opposite(self._gen_get_dir_to_closest_edge(self, pos))

    def _gen_get_available_dist(self, pos, direction):
        """get distance from pos to edge in direction"""
        if   direction == 'N':
            return pos.y
        elif direction == 'S':
            return self.size.y - pos.y
        elif direction == 'E':
            return self.size.x - pos.x
        elif direction == 'W':
            return pos.x
        else:
            assert False, "_gen_get_available_dist called with bad direction %s" % direction

    def _gen_pos_from_dir(self, direction, distance):
        """return a position, based on moving distance in direction from (0,0)"""
        if   direction == 'N':
            return Position(0, -distance)
        elif direction == 'S':
            return Position(0, distance)
        elif direction == 'E':
            return Position(distance, 0)
        elif direction == 'W':
            return Position(-distance, 0)
        else:
            assert False, "_gen_pos_from_dir called with bad direction %s" % direction

    def _gen_dir_from_pos(self, pos_from, pos_to=None):
        """calculate principal direction to travel in to get from pos to pos.
        if pos_to omitted, direction to get to map bounds"""
        if pos_to is None:
            pos_to = self.size
        v = pos_to - pos_from

        length = abs(v.x)
        direction = 'E'
        if v.x < 0:
            direction = 'W'
        if abs(v.y) > abs(v.x):
            length = abs(v.y)
            direction = 'S'
            if v.y < 0:
                direction = 'N'

        return (direction, length)

    def _gen_get_edge_tile(self, edge, border_min=0, border_max=2):
        """Random unoccupied Position() within <border_min/_max> tiles of map edge <edge>"""
        p = None
        if   edge == 'N':
            p = Position(libtcod.random_get_int(self.map_rng, border_min, self.size.x - border_min - 1),
                         libtcod.random_get_int(self.map_rng, border_min, border_max))
        elif edge == 'S':
            p = Position(libtcod.random_get_int(self.map_rng, border_min, self.size.x - border_min - 1),
                         self.size.y - libtcod.random_get_int(self.map_rng, border_min, border_max) - 1)
        elif edge == 'W':
            p = Position(libtcod.random_get_int(self.map_rng, border_min, border_max),
                         libtcod.random_get_int(self.map_rng, border_min, self.size.y - border_min - 1))
        elif edge == 'E':
            p = Position( self.size.x - libtcod.random_get_int(self.map_rng, border_min, border_max),
                          libtcod.random_get_int(self.map_rng, border_min, self.size.y - border_min - 1))
        else:
            assert False, "_gen_get_edge_tile called with invalid edge %s" % edge

        if self._map[p.x][p.y] == 0:
            return p
        else:
            return self._gen_get_edge_tile(edge, border_min, border_max)

    def _gen_get_centre_tile(self, border=0):
        """Random unoccupied Position(), border tiles from map edge"""
        x = libtcod.random_get_int(self.map_rng, border, self.size.x - border - 1)
        y = libtcod.random_get_int(self.map_rng, border, self.size.y - border - 1)
        if self._map[x][y] == 0:
            return Position(x, y)
        else:
            return self._gen_get_centre_tile(border)

    def _gen_room(self, opos):
        """Make a room, spiralling out from <pos>. Uses _map to identify collisions with corridors and other features"""
        # 6
        # 6455555     x = 1
        # 6423335     while 1:
        # 642^135         go x in direction d
        # 6422135         go x in clockwise from d
        # 6444435         x++
        # 6666665         d = opposite(d)
        #

        #  55.......       .......
        #  53333       86N5555579
        #  53114       86n3114s79
        #  53^24       86n3^24s79
        #  52224       86n2224s79
        #  44444       8644444s79
        #              8666666s79
        #              8888888879
        #

        # no N/S bound set, increment N/S step every other turn
        # one N/S bound set, increment N/S step every 4th turn
        # both N/S bounds set, don't increment
        # no E/W bound set, increment E/W step every other turn
        # one E/W bound set, increment E/W step every 4th turn
        # both E/W bounds set, don't increment

        #    ''          ''        4ee''          ''             ''             ''
        #   3ccc        3ccc       4           N              NeeeE          NeeeE
        #   31a4'''     31a4'''    4    '''    4    '''       4    '''           4'''
        #'  3^24  '  '  3^24  '  ' 4 ^    '  ' 4 x    '     ' 4 x    '     '   x 4  '
        #   bb24  '     bb2S  '    ddddS  '    ddddS  '           S  '     fWffffS  '
        #  ''dd4       ''          ''          ''             ''             ''
        #
        #               S           S          NS             NSE

        #        '''''                      '         '                      
        #          ||Neeeeegi              3c!         '
        #          ||531a45||              31a'      Ncc!
        #         '||53^245||              3^2 '     3^2 '
        #         |||5bb245||              bb2  '    bb2  '
        #         jhffffffS||
        #         '''''

        #
        #           '             3cEc
        #        3cEc'            31a4  '
        #        31a'             3^24 '
        #        3^2              bb24'
        #        bb2                 !
        #                           '

        # sanity
        if self._map[opos.x][opos.y] > 0:
            return []

        direction = 'N' # always go clockwise starting N
        length    = 0
        pos       = Position(opos.x, opos.y)
        size      = Position(0, 0)
        bounds    = {'N': self.BOUNDARY_UNSET, 'S': self.BOUNDARY_UNSET,
                     'E': self.BOUNDARY_UNSET, 'W': self.BOUNDARY_UNSET}
        r_segs    = []
        sanity    = 0

        while min(bounds.values()) == self.BOUNDARY_UNSET:
            sanity += 1
            if sanity > self.SANITY_LIMIT * 10:
                assert False, "Sanity limits hit in room gen"
            if direction in ['N', 'S']:
                if bounds[direction] == self.BOUNDARY_UNSET:
                    size.y += 1
                    length = size.y
                else:
                    length = abs(bounds[direction] - pos.y) - 1
            else:
                if bounds[direction] == self.BOUNDARY_UNSET:
                    size.x += 1
                    length = size.x
                else:
                    length = abs(bounds[direction] - pos.x) - 1
            target_pos = pos + self._gen_pos_from_dir(direction, length)

            self.debug_print(" [] %s %d at %s towards %s" % (direction, length, pos, target_pos))

            x_range = range(pos.x, target_pos.x + 1)
            if pos.x > target_pos.x:
                x_range = range(target_pos.x, pos.x + 1)
            y_range = range(pos.y, target_pos.y + 1)
            if pos.y > target_pos.y:
                y_range = range(target_pos.y, pos.y + 1)

            found = False
            for x in x_range:
                for y in y_range:
                    if self._map[x][y] > 0:
                        if (x == target_pos.x and y == target_pos.y):
                            # hit at end of edge; don't need to rewind direction
                            target_pos -= self._gen_pos_from_dir(direction, 1)

                            # if we've already hit this edge, don't reset boundary
                            if bounds[direction] != self.BOUNDARY_UNSET:
                                self.debug_print("    end hit %d ignored at (%d,%d) size=%s; target now %s" % (
                                        self._map[x][y], x, y, size, target_pos))
                                found = True
                                break
                            self.debug_print("    end hit %d at (%d,%d) size=%s; target now %s" % (
                                    self._map[x][y], x, y, size, target_pos))

                            #  * put a door at collision point
                            self.debug_print("    Door added in corner at %s" % (
                                    target_pos + self._gen_pos_from_dir(self._gen_get_compass_right(direction), 1)))
                            r_segs.append(self._ME(MapPattern.DOOR, target_pos + \
                                                       self._gen_pos_from_dir(self._gen_get_compass_right(direction), 1),
                                                   Position(1, 1),
                                                   Position(x, y)))
                            t = self._gen_get_compass_left(direction)
                            if bounds[t] == self.BOUNDARY_UNSET:
                                if t in ('N', 'S'):
                                    bounds[t] = y + self._gen_pos_from_dir(t, 1).y
                                else:
                                    bounds[t] = x + self._gen_pos_from_dir(t, 1).x

                        elif bounds[self._gen_get_compass_left(direction)] != self.BOUNDARY_UNSET:
                            target_pos -= self._gen_pos_from_dir(direction, 1)
                            self.debug_print("        hit %d ignored at (%d,%d) size=%s; target now %s" % (
                                    self._map[x][y], x, y, size, target_pos))

                            if bounds[direction] != self.BOUNDARY_UNSET:
                                found = True
                                break
                            self.debug_print("        substituting for current dir! %s" % direction)
                            target_pos -= self._gen_pos_from_dir(direction, 1)
                        else:
                            # collision with a corridor or another room
                            #  * turn back anti-clockwise
                            direction = self._gen_get_compass_left(direction)
                            #  * move back one square from pos
                            target_pos = pos - self._gen_pos_from_dir(direction, 1)

                            if direction in ['N', 'S']:
                                size.y -= 1
                            else:
                                size.x -= 1

                            self.debug_print("        hit %d at (%d,%d) size=%s; target now %s" % (self._map[x][y], x, y, size, target_pos))

                            #  * put a door at collision point
                            self.debug_print("        Door added at %s" % (Position(x, y) - self._gen_pos_from_dir(direction, 1)))
                            r_segs.append(self._ME(MapPattern.DOOR, Position(x, y) - self._gen_pos_from_dir(direction, 1), Position(1, 1), Position(x, y)))

                        #  * record this position as the bound for this direction
                        if bounds[direction] == self.BOUNDARY_UNSET:
                            if direction in ['N', 'S']:
                                bounds[direction] = y
                            else:
                                bounds[direction] = x
                        self.debug_print("        bounds = %s" % bounds)

                        #  * continue
                        found = True
                        break
                if found:
                    break

            direction = self._gen_get_compass_right(direction)
            pos = target_pos

        self.debug_print ("Room starting at %s is %s" % (opos, bounds))

        tl = Position(bounds['W'] + 2, bounds['N'] + 2)
        br = Position(bounds['E'] - 1, bounds['S'] - 1)
        size = br - tl
        r_segs.append(self._ME(MapPattern.ROOM, tl, size, opos))

        # room behaves badly if starting coord outside bounds
        if tl > opos or br < opos:
            self.debug_print ("Rejecting room: starting coord outside final bounds")
            return []

        # size limits
        if size.x < self.ROOM_MIN_WIDTH or size.y < self.ROOM_MIN_WIDTH:
            return []
        if size.x * size.y > self.ROOM_MAX_AREA:
            return []

        # lighting
        #  * choose a scheme out of
        light_roll = libtcod.random_get_float(self.map_rng, 0.0, 1.0)
        #       * flat light
        if light_roll < 0.4:
            for s in r_segs:
                s.flat_light = True
        #       * one central light
        elif light_roll < 0.9:
            p = tl + (size.x // 2, size.y // 2)
            self.debug_print("room light at %s; tl=%s sz=%s" % (p, tl, size))
            r_segs.append(self._ME(MapPattern.LIGHT, p, Position(1, 1), p))
        #       * grid of lights in middle
        #       * lights on edges
        #       * no lights at all
        else:
            pass

        return r_segs

    def _gen_corridor_seg(self, opos, direction, length, width=1):
        """generate a section of corridor from opos in direction for length tiles and width.
        returns a list of map elements"""
        size = None
        if direction == 'N':
            if opos.y + width >= self.size.y:
                length -= width
            else:
                opos += (0, width)
        elif direction == 'W':
            if opos.x + width >= self.size.x:
                length -= width
            else:
                opos += (width, 0)
        pos  = Position(opos.x, opos.y)
        if   direction == 'N':
            # adjust pos to top-left
            pos -= Position(0, length)
            size = Position(width, length)
        elif direction == 'S':
            size = Position(width, length)
        elif direction == 'E':
            size = Position(length, width)
        elif direction == 'W':
            pos -= Position(length, 0)
            size = Position(length, width)
        else:
            assert False, "_gen_corridor_seg called with invalid direction %s" % direction
        r_segs = [self._ME(MapPattern.CORRIDOR, pos, size, opos, direction, length)]

        # lighting
        # NB. need to insert lighting segs at beginning of return list to help corridor gen
        light_roll = libtcod.random_get_float(self.map_rng, 0.0, 1.0)
        #       * flat lighting
        if   light_roll < 0.4:
            for r in r_segs:
                r.flat_light = True
        #       * one central light
        elif light_roll < 0.9:
            p = pos + (size.x // 2, size.y // 2)
            self.debug_print("light at %s in corridor %s %s %s" % (p, pos, size, width))
            r_segs.insert(0, self._ME(MapPattern.LIGHT, p, (1, 1), p, 'N', 0))
        #       * light at each end
        #elif light_roll < 0.8:
        #    r_segs.insert(0, self._ME(MapPattern.LIGHT, pos, (1,1), pos, 'N', 0))
        #    r_segs.insert(0, self._ME(MapPattern.LIGHT, pos+size-Position(1,1), (1,1), pos+size, 'N', 0))
        #       * no lights at all
        else:
            pass

        return r_segs

    def _gen_corridor_to_area(self, pos, direction, edge, width, bendiness=3):
        """returns map elements representing a corridor starting at pos, travelling in direction and terminating near edge.
        bendiness indicates how many bends to try"""
        c_segs = []
        curr_pos = pos
        num_bends = libtcod.random_get_int(self.map_rng, 2, bendiness)

        sanity = 0

        terminating_pos = self._gen_get_edge_tile(edge, self.CORRIDOR_MIN_LENGTH + width + 1, self.CORRIDOR_MIN_LENGTH + width + 6)
        while curr_pos.distance_to(terminating_pos) < self.CORRIDOR_MIN_LENGTH * 5:
            sanity += 1
            if sanity > self.SANITY_LIMIT:
                break
            terminating_pos = self._gen_get_edge_tile(edge, self.CORRIDOR_MIN_LENGTH + width + 1, self.CORRIDOR_MIN_LENGTH + width + 6)

        while num_bends > 0 and curr_pos.distance_to(terminating_pos) > width+1:
            if   num_bends == 1:
                # get as close to terminating pos as possible
                d, l = self._gen_dir_from_pos( curr_pos, terminating_pos )
                c_segs += self._gen_corridor_seg( curr_pos, d, l, width )
                self.debug_print("Bend 1 (last): pos %s, target %s, dir %s, len %d" % (curr_pos, terminating_pos, d, l))

            elif num_bends == 2:
                # get on same long or lat as terminating pos
                v = terminating_pos - curr_pos
                l = abs(v.x)
                if direction in ['N', 'S']:
                    l = abs(v.y)
                if l > self._gen_get_available_dist(curr_pos, direction):
                    direction = self._gen_get_compass_opposite(direction)
                if l > self._gen_get_available_dist(curr_pos, direction): # still!
                    l = self._gen_get_available_dist(curr_pos, direction) - self.CORRIDOR_MIN_LENGTH - width
                c_segs += self._gen_corridor_seg(curr_pos, direction, l, width)
                self.debug_print("Bend 2 (pen.): pos %s, target %s, dir %s, len %d" % (curr_pos, terminating_pos, direction, l))

            else:
                # travel random distance in current direction, then turn
                l_min = self._gen_get_available_dist(curr_pos, direction) - self.CORRIDOR_MIN_LENGTH - width
                if l_min > self.CORRIDOR_MIN_LENGTH + width + 1:
                    l_min = self.CORRIDOR_MIN_LENGTH + width + 1
                elif l_min <= 0:
                    direction = self._gen_get_compass_opposite(direction)
                c_segs += self._gen_corridor_seg(curr_pos, direction, libtcod.random_get_int(self.map_rng, self.CORRIDOR_MIN_LENGTH + width + 1, self._gen_get_available_dist(curr_pos, direction) - self.CORRIDOR_MIN_LENGTH - width), width)
                self.debug_print("Bend >2 (first): pos %s, target %s, dir %s, len %d" % (curr_pos, terminating_pos, direction, c_segs[-1].length))
                direction = self._gen_get_compass_turn(direction)
            num_bends -= 1
            curr_pos += self._gen_pos_from_dir(c_segs[-1].direction, c_segs[-1].length)

        return c_segs

    def _gen_corridor_wriggle(self, pos, direction, length, width, bendiness):
        """returns map elements representing a corridor starting at pos and travelling in direction for length.
        bendiness indicates how many bends to try"""
        c_segs    = []
        len_used  = 0
        curr_pos  = pos
        num_bends = libtcod.random_get_int(self.map_rng, 0, bendiness)

        sanity = 0
        while len_used < length:
            sanity += 1
            if sanity > self.SANITY_LIMIT:
                #assert False, "sanity hit whilst routing corridor"
                break
            len_wanted = int(libtcod.random_get_float(self.map_rng, self.CORRIDOR_LENGTH_VAR[0], self.CORRIDOR_LENGTH_VAR[1]) * (length) / (1 + num_bends))
            if len_wanted + len_used > length:
                len_wanted = length - len_used
            if len_wanted < self.CORRIDOR_MIN_LENGTH:
                len_wanted = self.CORRIDOR_MIN_LENGTH
            len_avail = self._gen_get_available_dist(curr_pos, direction)

            if len_avail > len_wanted + 1:
                c_segs += self._gen_corridor_seg(curr_pos, direction, len_wanted, width)
                len_used += len_wanted
                curr_pos += self._gen_pos_from_dir(direction, len_wanted)
                self.debug_print("iter: %d; pos: %s; dir: %s; used: %d; wanted %d; avail: %d" % (sanity, curr_pos, direction, len_used, len_wanted, len_avail))

            # turn towards area with space to draw what we want
            direction = self._gen_get_compass_turn(direction)
            o = self._gen_get_compass_opposite(direction)
            #if self._gen_get_available_dist( curr_pos, direction ) < self._gen_get_available_dist( curr_pos, o ):
            if self._gen_get_available_dist(curr_pos, direction) < self.CORRIDOR_MIN_LENGTH + width + 1:
                direction = o

        return c_segs

    def generate(self):
        """generate map"""
        # reset internal map structure
        self._map = [[0 for y in range(self.size.y)] for x in range(self.size.x)]

        # map boundaries
        #self._gen_draw_map_edges()
        edges = [
            self._ME(MapPattern.WALL, Position(0, 0), Position(self.size.x - 1, 1)),
            self._ME(MapPattern.WALL, Position(0, 0), Position(1, self.size.y - 1)),
            self._ME(MapPattern.WALL, Position(self.size.x - 1, 0), Position(1, self.size.y)),
            self._ME(MapPattern.WALL, Position(0, self.size.y - 1), Position(self.size.x, 1))
            ]
        for e in edges:
            e.commit(self._map)

        # * corridors and rooms include just walkable tiles
        corridors = []
        rooms = []
        # * route one corridor across most of map
        #    * choose random site near one edge of map
        #    * choose random site near far edge of map
        #    * choose corridor width
        #    * choose number of corridor bends (1-4, depending on sites)
        #    * plot corridor
        self.debug_print(" -- MAIN CORRIDOR --")
        d = self._gen_get_compass_dir()
        o = self._gen_get_compass_opposite(d)
        corridors += self._gen_corridor_to_area(self._gen_get_edge_tile( o, 2, 4),
                                         d,
                                         o,
                                         2,
                                         self.CORRIDOR_MAX_BENDS)

        # * calculate allowance for intersecting corridors (1-5)
        # * consume allowance: 1 for 1 tile width; 2 for 2 tile width, multiplied by 1 for short corridor, 2 for long
        #    * choose random length and termination points
        #    * choose random number of bends
        #    * plot corridor
        main_len = reduce(lambda a, b: a + b.length, corridors, 0)
        used_len = 0
        index_len = 0
        c_idx = 0
        sanity = 0
        while used_len < main_len:
            sanity += 1
            if sanity > self.SANITY_LIMIT:
                assert False, "broke sanity trying to add wriggle corridors"
                break
            delta_len = libtcod.random_get_int(self.map_rng, 0, self.CORRIDOR_MINOR_FREQ) * self.CORRIDOR_MINOR_STEP
            index_len += delta_len
            while index_len > corridors[c_idx].length:
                index_len -= corridors[c_idx].length
                c_idx += 1
                if c_idx == len(corridors):
                    # put wriggle corridor at end of last part of main
                    c_idx -= 1
                    index_len = corridors[c_idx].length
            c = corridors[c_idx]
            intersect = c.opos + self._gen_pos_from_dir(c.direction, index_len)
            d = self._gen_get_compass_turn(c.direction)
            self.debug_print("%d/%d %d/%d from %s %s for %d = %s" % (used_len, main_len, index_len, c.length, c.opos, c.direction, index_len, intersect))

            corridors += self._gen_corridor_wriggle(intersect,
                                             d,
                                             libtcod.random_get_int(self.map_rng, self.CORRIDOR_MINOR_LEN // 2, self.CORRIDOR_MINOR_LEN),
                                             1,
                                             self.CORRIDOR_MINOR_BEND)

            used_len += delta_len

        # * if corridors don't give reasonable coverage, give up and start again
        coverage_tl_pos = Position(self.size.x, self.size.y)
        coverage_br_pos = Position(0, 0)
        for c in corridors:
            if c.pos < coverage_tl_pos:
                coverage_tl_pos = c.pos
            if c.pos + c.size > coverage_br_pos:
                coverage_br_pos = c.pos + c.size
        if coverage_tl_pos.distance_to(coverage_br_pos) < Position(0, 0).distance_to(self.size) * self.REJECT_COVERAGE_PC:
            self.debug_print("Rejecting map !!!")
            return self.generate()

        # * commit corridors to map
        for c in corridors:
            c.commit(self._map)

        # * randomly pick empty tiles and grow rooms until they touch corridors
        room_count = 0
        while room_count < libtcod.random_get_int(self.map_rng, self.MIN_ROOMS, self.MAX_ROOMS):
            r = self._gen_room(self._gen_get_centre_tile(3))
            if len(r) > 0:
                room_count += 1
                rooms += r
                for ri in r:
                    ri.commit(self._map) # prevents rooms from overlapping as much

        # put edges back
        for e in edges:
            e.commit(self._map)

        # [* may need to repeat this loop 2-3 times, making squares permanent at each point]
        # * for each square larger than threshold:
        #    * if random chance succeeds:
        #        * sub-divide with partitions
        # * create doors at intersects
        # * use pathing to prove map traversable
        # * populate Map object from _map

        self._gen_apply_patterns(self._map)

        misses = 0
        for x in range(len(self._map)):
            for y in range(len(self._map[x])):
                t = self._map[x][y]

                if t & MapPattern.SPECIAL:
                    # assume special tiles have already managed floor/wall space, if necessary
                    pass

                elif t & MapPattern.DOOR:
                    # only draw door if exactly two tiles in compass directions are walkable
                    m_ns = 0
                    m_ew = 0
                    if y > 0 and y < self.size.y - 1:
                        n = self._map[x][y - 1]
                        s = self._map[x][y + 1]
                        if n & (MapPattern.CORRIDOR | MapPattern.ROOM | MapPattern.SPECIAL) > 0 \
                                and s & (MapPattern.CORRIDOR | MapPattern.ROOM | MapPattern.SPECIAL) > 0:
                            m_ns = 1
                        if (n & (MapPattern.WALL | MapPattern.DOOR) > 0 or n == 0) \
                                and (s & (MapPattern.WALL | MapPattern.DOOR) > 0 or s == 0):
                            m_ns = -1
                    if x > 0 and x < self.size.x - 1:
                        e = self._map[x - 1][y]
                        w = self._map[x + 1][y]
                        if e & (MapPattern.CORRIDOR | MapPattern.ROOM | MapPattern.SPECIAL) > 0 \
                                and w & (MapPattern.CORRIDOR | MapPattern.ROOM | MapPattern.SPECIAL) > 0:
                            m_ew = 1
                        if (e & (MapPattern.WALL | MapPattern.DOOR) > 0 or e == 0) \
                                and (w & (MapPattern.WALL | MapPattern.DOOR) > 0 or w == 0):
                            m_ew = -1
                    #if True or (m_ns > 0 and m_ew < 0) or (m_ns < 0 and m_ew > 0):
                    if (m_ns > 0 and m_ew < 0) or (m_ns < 0 and m_ew > 0):
                        self.add(Floor(Position(x, y)))
                        self.add(Door(Position(x, y)))
                    elif m_ns <= 0 and m_ew <= 0:
                        self.add(Wall(Position(x, y)))
                    else:
                        self.add(Floor(Position(x, y)))

                elif t & MapPattern.CORRIDOR:
                    self.add(Floor(Position(x, y)))

                elif t & MapPattern.ROOM:
                    self.add(Floor(Position(x, y)))

                elif t & MapPattern.WALL:
                    self.add(Wall(Position(x, y)))

                elif t == 0:
                    if x > 0 and y > 0 and x < self.size.x - 1 and y < self.size.y - 1:
                        # * if tile adjoins one walkable tile, it is a wall tile
                        if self._map[x - 1][y - 1] > 0 or \
                           self._map[x][y - 1] > 0 or \
                           self._map[x + 1][y - 1] > 0 or \
                           self._map[x - 1][y] > 0 or \
                           self._map[x][y] > 0 or \
                           self._map[x + 1][y] > 0 or \
                           self._map[x - 1][y + 1] > 0 or \
                           self._map[x][y + 1] > 0 or \
                           self._map[x + 1][y + 1] > 0:
                            self.add(Wall(Position(x, y)))
                    else:
                        misses += 1
                else:
                    print("WARNING: Invalid _map data at pos (%d,%d); flags 0x%x" % (x, y, self._map[x][y]))
                    #assert False, "Invalid _map data at pos (%d,%d); flags 0x%x"%(x,y,self._map[x][y])

                # overlay lights
                if t & MapPattern.LIGHT:
                    self.add(Light(Position(x, y), libtcod.random_get_int(self.map_rng, self.LIGHT_MIN_RADIUS, self.LIGHT_MAX_RADIUS)))

        # add remaining lights
        for s in corridors + rooms:
            if s.flat_light and (s.tile_id & (MapPattern.CORRIDOR | MapPattern.ROOM)):
                self.add(FlatLight(s.pos, s.size))

        if 1.0 - (misses / (self.size.x * self.size.y)) < self.REJECT_COVERAGE_SQ:
            return self.generate()


        #####  PSEUDO-CODE  #########################################
        # * corridors and rooms include just walkable tiles
        # * route one corridor across most of map
        #    * choose random site near one edge of map
        #    * choose random site near far edge of map
        #    * choose corridor width
        #    * choose number of corridor bends (1-4, depending on sites)
        #    * plot corridor
        # * calculate allowance for intersecting corridors (1-5)
        # * consume allowance: 1 for 1 tile width; 2 for 2 tile width, multiplied by 1 for short corridor, 2 for long
        #    * choose random intersect on main corridor
        #    * choose random length and termination points
        #    * choose random number of bends
        #    * plot corridor
        # * for each remaining unplotted tile
        #    * calculate largest square that can be made without overlapping a corridor+1 tile
        #    * if square size > threshold or (>0 and random chance):
        #       * if square overlaps another one
        #          * if this square size > that square size
        #             * remove that square
        #          * else continue
        #       * save square
        # [* may need to repeat this loop 2-3 times, making squares permanent at each point]
        # * for each square larger than threshold:
        #    * if random chance succeeds:
        #        * sub-divide with partitions
        # * create doors at intersects
        # * use pathing to prove map traversable
        # * for tile in empty tiles:
        #    * if tile adjoins one walkable tile, it is a wall tile


        # place daleks
        for i in range(15):
            d = Monster.random(self.map_rng, self.find_random_clear(self.map_rng))
            self.add(d)

        # place some items
        for i in range(8):
            i = Item.random(self.map_rng, self.find_random_clear(self.map_rng))
            self.add(i)

        # add evidence
        self._gen_add_evidence()

        self._gen_add_key_elements()
        self._gen_finish()


class TypeBMap(Map):
    """Map
     * use B-tree algorithm to create cell-shaped rooms with 1 tile gap between them
     * populate gaps with corridors
     * spawn doors
    """
    pass
