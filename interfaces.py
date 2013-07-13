#!/usr/bin/env python3

import libtcodpy as libtcod
from math import hypot, atan2, pi
import weakref

from errors import InvalidMoveError
from ui import Message

class Position:
    def __init__(self,x,y):
        self.x = x
        self.y = y

    def __hash__(self):
        return hash((self.x,self.y))

    def __add__(self,other):
        if isinstance(other,tuple):
            return Position(self.x + other[0], self.y + other[1])
        else:
            return Position(self.x + other.x, self.y + other.y)

    def __sub__(self,other):
        if isinstance(other,tuple):
            return Position(self.x - other[0], self.y - other[1])
        else:
            return Position(self.x - other.x, self.y - other.y)

    def __gt__(self,other):
        """Furthest from origin is largest; if tied, larger x beats larger y so that we sort left-right, top-bottom"""
        return (self.x*self.y>other.x*other.y) or (self.x>other.x)
    def __ge__(self,other):
        return (self.x*self.y>other.x*other.y) or (self.x>=other.x)
    def __eq__(self,other):
        return self.x==other.x and self.y==other.y

    def __repr__(self):
        return "Position(%d,%d)" % (self.x,self.y)

    def __str__(self):
        return "(%d,%d)" % (self.x,self.y)

    def distance_to(self,other):
        """returns distance to other"""
        return hypot(self.x-other.x,self.y-other.y)

    def angle_to(self,other):
        """returns angle in radians/pi between self and other. i.e. 0.0 => matching directions; 1.0 => opposites"""
        t = (atan2(self.x,self.y) - atan2(other.x,other.y))/ pi
        if t > 1.0:
            t -= 2.0
        elif t < -1.0:
            t += 2.0
        return abs(t)

class Mappable:
    """Can appear on the map"""

    def __init__(self, pos, symbol, colour, remains_in_place=False, unseen_symbol=None, unseen_colour=libtcod.darkest_grey):
        self.map = None
        self.pos = pos
        self.last_pos = pos
        self.symbol = symbol
        self.colour = colour
        self.remains_in_place = remains_in_place

        self.is_visible = True
        self.has_been_seen = False
        self.visible_to_player = False

        self.unseen_symbol = (unseen_symbol is None) and self.symbol or unseen_symbol
        self.unseen_colour = unseen_colour

    ##
    # movement
    def move(self, delta):
        """move by a delta"""
        return self.move_to(self.pos+delta)
 
    def move_to(self, pos):
        """move by an absolute"""
        assert not self.remains_in_place, "trying to move immovable object %s" % self
        ## test whether movement is valid # this lives in map.move now
        #if not self.map is None and self.map.is_blocked(pos):
        #    raise InvalidMoveError( "Can't move %s to %s"%(self,pos) )

        self.map.move(self, pos)

    ##
    # drawing
    def draw(self):
        # NB. this gets called a lot!
        if not self.is_visible:
            return
        colour = self.colour
        symbol = self.unseen_symbol

        if not (self.visible_to_player):
            if self.has_been_seen and self.remains_in_place:
                colour = self.unseen_colour
                symbol = self.unseen_symbol
            else:
                return
        libtcod.console_put_char_ex(0, self.pos.x, self.pos.y, self.symbol, colour, libtcod.BKGND_NONE)
        self.has_been_seen = True

class TurnTaker:
    turn_takers = []

    def __init__(self, initiative):
        """Lowest initiative goes first"""
        self.initiative = initiative
        TurnTaker.add_turntaker(self)

    def take_turn(self):
        raise NotImplementedError

    @staticmethod
    def take_all_turns():
        for tref in TurnTaker.turn_takers:
            t = tref()
            if t is None:
                TurnTaker.turn_takers.remove(tref)
            else:
                t.take_turn()

    @staticmethod
    def clear_all():
        for tref in TurnTaker.turn_takers:
            t = tref()
            if not t is None:
                del t
        TurnTaker.turn_takers = []

    def refresh_turntaker(self):
        if not weakref.ref(self) in TurnTaker.turn_takers:
            TurnTaker.add_turntaker(self)

    @staticmethod
    def add_turntaker(t):
        # might be a faster way to do this
        TurnTaker.turn_takers.append(weakref.ref(t))        
        TurnTaker.turn_takers.sort( key = lambda x: x() is None and 100000 or x().initiative )                

    @staticmethod
    def clear_turntaker(t,count=1):
        r = weakref.ref(t)
        for x in range(count):
            if r in TurnTaker.turn_takers:
                TurnTaker.turn_takers.remove(r)


class Traversable:
    def __init__(self, walk_cost=0.0, may_block_movement=False):
        # 0.0 => can't traverse
        # 1.0 => traverse with no penalty
        self.walk_cost = walk_cost
        # False => try_movement always True
        # True  => try_movement might return False
        self.may_block_movement = may_block_movement

    def try_leaving(self,obj):
        return True

    def try_movement(self,obj):
        return not self.blocks_movement()

    def blocks_movement(self, is_for_mapping=False):
        return (self.walk_cost == 0.0) and (not is_for_mapping or self.may_block_movement)

class Transparent:
    def __init__(self, transparency=0.0):
        # 0.0 => completely opaque
        # 1.0 => completely transparent
        self.transparency = transparency

    def blocks_light(self):
        return self.transparency == 0.0


class StatusEffect:
    """things that have passive status (such as being blind, stunned, able to see through walls, ...)"""
    # buffs
    X_RAY_VISION = 100
    FAST         = 101

    # debuffs
    BLIND        = 200
    DEAF         = 201

    def __init__(self):
        self.current_effects = []

    def add_effect(self,status):
        if status in self.current_effects:
            return False
        else:
            self.current_effects.append(status)
            return True

    def remove_effect(self,status):
        if not status in self.current_effects:
            return False
        else:
            self.current_effects.remove(status)
            return True

    def has_effect(self,status):
        return status in self.current_effects


class CountUp:
    """things that count up (e.g. multi-turn stairs traversal)"""
    def __init__(self,count_to,c=0):
        self.count_to = count_to
        self.count    = c

    def inc(self,i=1):
        if self.full():
            return True
        self.count += i
        return self.full()

    def dec(self,i=1):
        if i > self.count:
            self.count = 0
        else:
            self.count -= i
        return self.count == 0

    def reset(self,c=0):
        self.count = c

    def full(self):
        return self.count == self.count_to


class HasInventory:
    def __init__(self,inv_size,fixed_slots=()):
        self.items = [None for i in range(inv_size)]
        self.slot_items = {}
        for s in fixed_slots:
            self.slot_items[s] = None

class Carryable:
    pass

class Activator:
    pass

class Activatable:
    def __init__(self,owner=None):
        assert isinstance(owner,Activator) or owner is None, "%s can't activate %s"%(owner,self)
        self.owner = owner

    def activate(self,activator=None):
        assert isinstance(self.owner,Activator) or isinstance(activator,Activator), "%s can't be activated" % self
        return True

class Alertable:
    def __init__(self,listen_radius=10):
        self.listen_radius = listen_radius

    def alert(self,to_pos):
        if hasattr(self,'pos'):
            return to_pos.distance_to(self.pos) <= self.listen_radius
        else:
            return True


# TODO: use this for symmetry between player and monsters with same capabilities
class CanSee:
    def __init__(self,radius=0):
        self.seeing_radius = radius

    def reset_fov(self):
        raise NotImplementedError


class Talker:
    currently_talking = []

    def __init__(self):
        self.__phrases = {}
        self.is_talking = False
        self.__chat = Message(None, "", True)
        self.__chat.is_visible = False
        self.__chat.timeout = 2.0

    def add_phrases(self,key,phrases,probability=0.05,is_shouting=False):
        if not key in self.__phrases.keys():
            self.__phrases[key] = {}
        self.__phrases[key]['probability'] = probability
        self.__phrases[key]['is_shouting'] = is_shouting
        self.__phrases[key]['phrases']     = phrases
        return self

    def stop_talk(self):
        self.__chat.is_visible = False
        self.is_talking = False
        self.currently_talking.remove(weakref.ref(self))

    def talk(self, key=None):
        if self.is_talking:
            self.stop_talk()
        if not key in self.__phrases.keys():
            return False
        if libtcod.random_get_float(None,0.0,1.0)<self.__phrases[key]['probability']:
            #assert key in self.__phrases.keys(), "Talker %s has no vocab for key %s"%(self,key)
            self.__chat.pos = self.pos-(0,1)
            self.__chat.text = self.__phrases[key]['phrases'][libtcod.random_get_int(None,0,len(self.__phrases[key]['phrases'])-1)]
            self.is_talking = True
            self.__chat.is_visible = True
            self.currently_talking.append(weakref.ref(self))
            if isinstance(self,Shouter) and self.__phrases[key]['is_shouting']:
                self.shout()
            return True
        return False
    
    @staticmethod
    def stop_all_talk():
        for tref in Talker.currently_talking:
            t = tref()
            if t is None:
                Talker.currently_talking.remove(tref)
            else:
                t.stop_talk()

class Shouter:
    def __init__(self,audible_radius=10):
        assert isinstance(self,Mappable), "Shouter must be a mappable object" # bad mi??
        self.audible_radius=audible_radius

    def shout(self,at_pos=None):
        if at_pos is None:
            at_pos = self.pos

        for a in self.map.find_all_within_r(self,Alertable,self.audible_radius):
            a.alert(at_pos)

