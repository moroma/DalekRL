#!/usr/bin/env python3

# testing imports
from behave import *
from mock import patch, Mock

# game imports
import maps
import player
import interfaces
#import DalekRL

@given('the default test map')
def step_impl(context):
    #DalekRL.init()
    p = player.Player()
    p.redraw_screen = Mock()
    p.handle_keys = Mock(return_value=p.do_nothing) # default is do nothing
    context.map = maps.EmptyMap(0, interfaces.Position(80,46), p)
    context.map.generate()
