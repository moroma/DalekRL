#!/usr/bin/env python3

import libtcodpy as libtcod
from interfaces import Mappable, Traversable, Transparent, TurnTaker, CountUp, Position, Activatable, HasInventory, Shouter, Talker, StatusEffect
from errors import LevelWinError, InvalidMoveError
from ui import HBar, Menu

from functools import reduce

#possibly belongs in maps.py
class MapPattern:
    # static constants used for map generation
    EMPTY    = 0x0
    CORRIDOR = 0x1
    ROOM     = 0x2
    WALL     = 0x4
    DOOR     = 0x8
    SPECIAL  = 0x10 # e.g. charger tile
#    FLOOR_FURNITURE = 0x20 # e.g. boxes and tables
#    WALL_SPECIAL    = 0x40 # e.g. portal
#    WALL_FURNITURE  = 0x80 # e.g. cupboard
    ANY             = 0xFF # i.e. all of above


    DATA_MAP = {
        ' ': EMPTY,
        '.': CORRIDOR|ROOM,
        'r': ROOM,
        'c': CORRIDOR,
        '#': WALL,
        '+': DOOR,
        'X': SPECIAL,
        '?': ANY,
        }

    def __init__(self,*rows):
        self.masks = []
        self.__hash = hash(reduce( lambda a,b: a+b, [ r for r in rows ], "" ))
        #  --x,w-->
        #  |   1 2 3   7 4 1   9 8 7   3 6 9
        # y,h  4 5 6   8 5 2   6 5 4   2 5 8
        #  v   7 8 9   9 6 3   3 2 1   1 4 7

        # build masks as arrays of arrays
        w = len(rows)
        h = len(rows[0])
        for m in range(4):
            self.masks.append([])
            for ci in range(w):
                self.masks[m].append([])
                for ri in range(h):
                    self.masks[m][ci].append(None)
        for ci in range(w):
            for ri in range(h):
                x = self.DATA_MAP.get(rows[ci][ri],self.EMPTY)
                self.masks[0][ci][ri]     = x     # 0
                self.masks[1][w-ri-1][ci] = x     # 90
                self.masks[2][w-ci-1][h-ri-1] = x # 180
                self.masks[3][ri][h-ci-1] = x     # 270

        # remove duplicate masks due to rotational symmetry
        symmetry_4 = True
        symmetry_2 = True
        for ci in range(w):
            for ri in range(h):
                if self.masks[0][ci][ri] != self.masks[1][ci][ri]:
                    symmetry_4 = False
                if self.masks[0][ci][ri] != self.masks[2][ci][ri]:
                    symmetry_2 = False
        if symmetry_4:
            del self.masks[1:3]
        elif symmetry_2:
            del self.masks[2:3]

        # convert each row from list to 

    def apply_to(self,map_array):
        r   = []
        kw2 = len(self.masks[0])//2
        kh2 = len(self.masks[0][0])//2
        for mci in range(kw2,len(map_array)-kw2):
            for mri in range(kh2,len(map_array[mci])-kh2):
                for mask in self.masks:
                    ok = True
                    for kci in range(-kw2,kw2+1):
                        for kri in range(-kh2,kh2+1):
                            #print("%2x&%2x "%(map_array[mci+kci][mri+kri], mask[kci+kw2][kri+kh2]), end="")
                            if not (map_array[mci+kci][mri+kri] & mask[kci+kw2][kri+kh2]) and not(map_array[mci+kci][mri+kri]==0 and mask[kci+kw2][kri+kh2]&MapPattern.WALL):
                                #print("!", end="")
                                ok = False
                                #break
                        #print()
                        if not ok:
                            break
                    #print("-----------------")
                    if ok:
                        #print("WOOOOOO")
                        r.append(Position(mci,mri))
                    #return r
        return r

    def __hash__(self):
        return self.__hash

class Tile(Mappable,Traversable,Transparent):
    patterns  = []
    place_min = 1
    place_max = 10

    def __init__(self, pos, symbol, colour, walk_cost=0.0, transparency=0.0, may_block_movement=False):
        """walk_cost == 0.0  =>  can't traverse tile
        walk_cost > 0.0; may_block_movement == True  =>  pathing shouldn't rely on tile being traversable (e.g. teleport tiles, locked doors)"""
        Mappable.__init__(self,pos,symbol,colour,remains_in_place=True)
        Traversable.__init__(self,walk_cost,may_block_movement)
        Transparent.__init__(self,transparency)

    @staticmethod
    def random_furniture(rng, pos):
        return Crate(pos)

    @staticmethod
    def random_special_tile(rng, pos):
        S = [FloorTeleport,FloorCharger]
        return S[libtcod.random_get_int(rng,0,len(S)-1)](pos)

    @staticmethod
    def get_all_tiles(rng, map_array, types=None):
        # for tile in tiles
        #    tile.place_in(map_array)
        #    for pattern in tile.patterns:
        #        # list of pos where tile can be placed
        #        ps = pattern.apply_to(map_array)
        #        ps.sort(random_get_float)
        if types is None:
            types = [FloorTeleport,FloorCharger,Crate,Window,Table,Locker,WallPanel,ClankyFloor,CameraConsole]

        ## naive way to do it (slow)
        #r = {}
        #for T in types:
        #    r[T] = []
        #    for pattern in T.patterns:
        #        r[T] += pattern.apply_to(map_array)
        #    r[T].sort( key = lambda a: libtcod.random_get_float(rng,0.0,1.0) )
        #return r

        # calculate which patterns are used by which objects, and apply each unique pattern once
        pattern_map = {}
        for T in types:
            for p in T.patterns:
                if not p in pattern_map.keys():
                    pattern_map[p] = []
                pattern_map[p].append(T)
        
        r = {}
        for (p,T_list) in pattern_map.items():
            p_list = p.apply_to(map_array)
            for T in T_list:
                if not T in r.keys():
                    r[T] = []
                r[T] += p_list

        # randomize order of positions in list, so caller can just pop() them
        # NB. keys are sorted because this must be deterministic for map gen
        for T in sorted(r.keys(), key=lambda a: a.__name__):
            r[T].sort( key = lambda a: libtcod.random_get_float(rng,0.0,1.0) )

        return r

class CountUpTile(Tile,CountUp,Activatable):

    def __init__(self, pos, symbol, colour, walk_cost=0.0, transparency=0.0, may_block_movement=False, count_up=10):
        Tile.__init__(self, pos, symbol, colour, walk_cost, transparency, may_block_movement)
        CountUp.__init__(self, count_up+1)
        #TurnTaker.__init__(self, 0)
        Activatable.__init__(self)
        self.bar = HBar(Position(pos.x-2,pos.y-1),5,libtcod.light_blue,libtcod.darkest_grey)
        self.bar.max_value = self.count_to-1
        self.bar.timeout = 5.0

    def step_on(self):

        if self.pos == self.map.player.pos:
            if self.count == 0:
                self.bar.is_visible = True
            if self.inc():
                return True
            else:
                self.bar.value = self.count_to-self.count

       # elif self.count > 0:
       #     self.bar.is_visible = False
       #     self.bar.value = 0
       #     self.reset()

        return False

    def try_leaving(self,obj):
        self.bar.is_visible = False
        self.bar.value = 0
        self.reset()
        return Tile.try_leaving(self,obj)


class Wall(Tile):
    def __init__(self, pos):
        Tile.__init__(self, pos, '#', libtcod.light_grey)

class Locker(Tile):
    patterns = [
        MapPattern("...",
                   "###",
                   "###")
        ]
    place_min = 3
    place_max = 10
    def __init__(self, pos):
        Tile.__init__(self, pos, 'L', libtcod.light_green, 0.0, 0.0, True)
        self.has_given_item = False

    def try_movement(self,obj):
        if not isinstance(obj,HasInventory) or self.has_given_item:
            return False

        self.colour = libtcod.light_grey
        obj.pickup(Item.random(None,None,weight=1.2))
        self.has_given_item = True

        return False

class WallPanel(Tile):
    # TODO: factor out common with lockers and subclass
    patterns = [
        MapPattern("...",
                   "###",
                   "###")
        ]
    place_min = 7
    place_max = 13
    def __init__(self, pos):
        Tile.__init__(self, pos, 'P', libtcod.dark_yellow, 0.0, 0.0, True)
        self.has_given_item = False
        self.evidence = None # TODO: this panel might contain the evidence?

    def try_movement(self,obj):
        if not isinstance(obj,HasInventory) or self.has_given_item:
            return False

        self.colour = libtcod.light_grey
        if not self.evidence is None:
            obj.pickup(self.evidence)
        self.has_given_item = True

        return False

class Table(Tile,Activatable):
    patterns = [
        MapPattern("rrr",
                   "rrr",
                   "rrr")
        ]
    place_min = 10
    place_max = 20
    def __init__(self, pos):
        Tile.__init__(self, pos, 'T', libtcod.light_blue, 1.0, 1.0)
        Activatable.__init__(self)

    def activate(self, activator=None):
        # sanity
        if not (self.owner is None or self.owner is activator):
            raise InvalidMoveError("Table already occupied by %s" % self.owner)
        assert not activator is None, "Table activated by None"

        # hide under table
        if self.owner is None:
            self.owner = activator
            self.owner.is_visible = False

        # stop hiding
        else:
            self.owner.is_visible = True
            self.owner = None
        return True

    def try_leaving(self, obj):
        # prevent leaving if in crate
        return not obj is self.owner

class Floor(Tile):
    def __init__(self, pos):
        Tile.__init__(self, pos, '.', libtcod.dark_grey, 1.0, 1.0)

class ClankyFloor(Tile,Talker,Shouter):
    patterns = [
        MapPattern("###",
                   "ccc",
                   "###")
        ]
    place_min = 5
    place_max = 25

    def __init__(self, pos):
        Floor.__init__(self, pos)
        Talker.__init__(self)
        Shouter.__init__(self, 15)
        self.add_phrases('ON',['** CLONK **','** CLANK **'],0.8)
        self.add_phrases('OFF',['** CLUNK **','** CLANG **'],0.8)

    def try_movement(self, obj):
        if self.talk('ON') and obj is self.map.player:
            self.shout()

        return True

    def try_leaving(self, obj):
        if self.talk('OFF') and obj is self.map.player:
            self.shout()

        return True

class StairsUp(Tile):
    place_max = 1
    def __init__(self, pos):
        Tile.__init__(self, pos, '<', libtcod.dark_grey, 1.0, 1.0)

class StairsDown(CountUpTile):
    place_max = 1
    def __init__(self, pos):
        CountUpTile.__init__(self, pos, '>', libtcod.light_grey, 1.0, 1.0, count_up=10)

    def activate(self,activator=None):
        if self.step_on():
            raise LevelWinError("Escaped!")


class Crate(Tile, Activatable):
    patterns = [
        # middle of a room
        MapPattern("rrr",
                   "rrr",
                   "rrr"),
        # or in a wide corridor
        MapPattern("ccc",
                   "ccc",
                   "###")
        ]
    place_min = 5
    place_max = 10

    def __init__(self, pos):
        Tile.__init__(self, pos, 'N', libtcod.light_grey, 1.0, 0.8)
        Activatable.__init__(self)
        self.remains_in_place = False

    def activate(self, activator=None):
        # sanity
        if not (self.owner is None or self.owner is activator):
            raise InvalidMoveError("Crate already occupied by %s" % self.owner)
        assert not activator is None, "Crate activated by None"

        # climb into crate
        if self.owner is None:
            self.owner = activator
            self.owner.is_visible = False

        # climb out of crate
        else:
            self.owner.is_visible = True
            self.owner = None
        return True

    def try_leaving(self, obj):
        # prevent leaving if in crate
        return not obj is self.owner


class Window(Tile,Shouter):
    patterns = [
        MapPattern("rrr",
                   "###",
                   "..."),
        ]
    place_min = 0
    place_max = 10
    def __init__(self, pos):
        Tile.__init__(self, pos, '\\', libtcod.light_grey, 0.0, 1.0)
        Shouter.__init__(self, 20)

    def smash(self):
        self.shout(self.pos)
        self.map.add(Floor(self.pos))
        self.map.remove(self)


class Door(Tile,CountUp,TurnTaker):
    OPEN = {'symbol':'.','colour':libtcod.dark_grey,'transparency':1.0,'walkcost':1.0,
            'timer':6, 'barcolour': libtcod.light_red
            }
    CLOSING = {'symbol':'-','colour':libtcod.grey,'transparency':1.0,'walkcost':1.0,
               'timer':4, 'barcolour': libtcod.light_red
               }
    CLOSED = {'symbol':'+','colour':libtcod.light_grey,'transparency':0.0,'walkcost':0.3,
              'timer':4, 'barcolour': libtcod.light_green
              }
    def __init__(self, pos):
        Tile.__init__(self, pos, Door.CLOSED['symbol'], Door.CLOSED['colour'], Door.CLOSED['walkcost'], Door.CLOSED['transparency'])
        CountUp.__init__(self, Door.CLOSED['timer'])
        TurnTaker.__init__(self,5)
        self.unseen_symbol = Door.CLOSED['symbol'] # always shows as closed when can't be seen
        self.state = Door.CLOSED
        self.bar = HBar(Position(pos.x-1,pos.y-1),3,Door.CLOSED['barcolour'],libtcod.darkest_grey)
        self.bar.max_value = self.count_to-1
        self.bar.timeout = 5.0
        self._trying_to_open = False

    def to_open(self):
        self.__change(Door.OPEN)
        self.map.recalculate_paths()
        self.map.player.reset_fov()

    def to_closed(self):
        self.__change(Door.CLOSED)
        self.map.recalculate_paths()
        self.map.player.reset_fov()

    def to_closing(self):
        self.__change(Door.CLOSING)

    def __change(self,state_dat):
        self.state = state_dat
        self.symbol = state_dat['symbol']
        self.colour = state_dat['colour']
        self.transparency = state_dat['transparency']
        self.walk_cost = state_dat['walkcost']
        self.count_to = state_dat['timer']
        self.bar.fgcolours = [state_dat['barcolour']]
        self.reset()

    def try_movement(self, obj):
        if self.state is Door.OPEN:
            return True

        elif self.state is Door.CLOSING:
            self.reset()
            return True

        else: # Door.CLOSED
            self._trying_to_open = True
            if self.inc():
                self.bar.is_visible = False
                self.to_open()
                #if obj is self.map.player: # i think we need to do this anyway
                #    self.map.recalculate_paths()
                #    self.map.player.reset_fov()
                return True
            else:
                if self.map.can_see(self):
                    self.bar.is_visible = True
                    self.bar.value = self.count_to-self.count
                return False

    def take_turn(self):
        if self.state is Door.CLOSED:
            if self._trying_to_open:
                self._trying_to_open = False
            else:
                self.bar.is_visible = False
                self.reset()
            return

        else: # open or closing
            if self.inc():
                self.bar.is_visible = False
                if self.state is Door.OPEN:
                    self.to_closing()
                else: # closing
                    self.to_closed()
            elif self.state is Door.CLOSING:
                # don't show state whilst open
                if self.map.can_see(self):
                    self.bar.is_visible = True
                    self.bar.value = self.count_to-self.count
                else:
                    self.bar.is_visible = False


# implemented as a turn taker
#from monsters import Monster
#from player import Player
#class FloorTeleport(Tile,TurnTaker):
#    def __init__(self, pos):
#        Tile.__init__(self, pos, '^', libtcod.purple, 0.2, 1.0)
#        TurnTaker.__init__(self,1000)
#
#    def take_turn(self):
#        # sanity
#        if len(self.map.find_all_at_pos(self.pos,[Monster,Player])) == 0:
#            return
#
#        targets = self.map.find_all(FloorTeleport,Tile)
#        targets.remove(self)
#
#        if len(targets) == 0:
#            return # oops, only one telepad on the level
#
#        for obj in self.map.find_all_at_pos(self.pos,[Monster,Player]):
#            try:
#                obj.move_to( targets[libtcod.random_get_int(None,0,len(targets)-1)].pos )
#
#            except InvalidMoveError:
#                pass # teleport exit blocked?


# implemented using the try_movement() method
class FloorTeleport(Tile):
    patterns = [
        # end of a corridor
        MapPattern("?#?",
                   "#..",
                   "?#?"),
        # corner of a room
        MapPattern("##?",
                   "#::",
                   "?::")
        ]
    place_min = 2
    place_max = 5

    def __init__(self, pos):
        Tile.__init__(self, pos, '^', libtcod.purple, 0.2, 1.0, True)

    def try_movement(self,obj):

        if obj.pos.distance_to(self.pos) >= 2:
            # moving to this tile from far away: must be teleporting; don't teleport again!
            return True

        try:
            targets = self.map.find_all(FloorTeleport,Tile)
            targets.remove(self)
            if len(targets) == 0:
                pass # oops, only one telepad on the level
            else:
                obj.move_to( targets[libtcod.random_get_int(None,0,len(targets)-1)].pos )

        except InvalidMoveError:
            pass # teleport exit blocked?

        return False # prevent original movement

from items import Item
class FloorCharger(Tile, CountUp):
    patterns = [
        # against a room wall
        MapPattern("###",
                   "rrr",
                   "rrr"),
        ]
    place_max = 2

    def __init__(self, pos):
        Tile.__init__(self, pos, 'X', libtcod.purple, 1.0, 1.0, False)
        CountUp.__init__(self, 50)

    def try_movement(self, obj):
        if isinstance(obj,HasInventory):
            for i in obj.items + list(obj.slot_items.values()):
                if isinstance(i,Item) and i.is_chargable and i.charge():
                    if self.inc():
                        return True

        return True


from monsters import Monster, StaticCamera
class CameraConsole(CountUpTile):
    patterns = [
        MapPattern("###",
                   "rrr",
                   "rrr")
        ]
    place_min = 1
    place_max = 2

    cameras_on = True

    def __init__(self,pos):
        CountUpTile.__init__(self, pos, 'C', libtcod.purple, 1.0, 1.0, count_up=7)

    def activate(self, activator=None):
        if self.step_on():
            xu = self.map.size.x//4
            yu = self.map.size.y//4
            b = Menu( Position(xu,yu), Position(xu*2,yu*2), title="Camera Control" )
            b.add('1',"View cameras")
            b.add('2',"Switch %s cameras" %(CameraConsole.cameras_on and 'off' or 'on'))
            b.add('x',"Exit")

            c = b.get_key()
            del b

            cams = self.map.find_all(StaticCamera,Monster)

            if c == '1':
                for cam in cams:
                    cam.has_been_seen = True

            elif c == '2':
                if CameraConsole.cameras_on:
                    for cam in cams:
                        cam.add_effect(StatusEffect.BLIND)
                else:
                    for cam in cams:
                        cam.remove_effect(StatusEffect.BLIND)

                CameraConsole.cameras_on = not CameraConsole.cameras_on
