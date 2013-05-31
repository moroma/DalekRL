#!/usr/bin/env python3

import libtcodpy as libtcod
from interfaces import Mappable, Traversable

class Tile(Mappable,Traversable):
    def __init__(self, pos, symbol, colour, walk_cost=0.0):
        Mappable.__init__(self,pos,symbol,colour)
        Traversable.__init__(self,walk_cost)

class Wall(Tile):
    def __init__(self, pos):
        Tile.__init__(self, pos, '#', libtcod.light_grey)

class Floor(Tile):
    def __init__(self, pos):
        Tile.__init__(self, pos, '.', libtcod.dark_grey, 1.0)

#class Stairs(Tile):
#    def __init__(self, pos):
#        Tile.__init__(self, pos, '<', libtcod.grey, 1.0)