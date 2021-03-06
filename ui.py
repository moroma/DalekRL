#!/usr/bin/env python3

import weakref

import libtcodpy as libtcod

class UI:
    ui_elements = []
    timeout_register = {}

    # abstraction of tcod coloured text control constants (also see map in DalekRL.py)
    COLCTRL_RED    = libtcod.COLCTRL_1
    COLCTRL_YELLOW = libtcod.COLCTRL_2
    COLCTRL_GREEN  = libtcod.COLCTRL_3
    COLCTRL_BLUE   = libtcod.COLCTRL_4
    COLCTRL_PURPLE = libtcod.COLCTRL_5
    COLCTRL_STOP   = libtcod.COLCTRL_STOP  # for consistency

    def __init__(self):
        UI.ui_elements.append(weakref.ref(self))
        self.is_visible = False
        self._timeout = 0.0

    @property
    def timeout(self):
        return self._timeout
    @timeout.setter
    def timeout(self,t):
        if self._timeout > 0.0:
            UI.timeout_register[self._timeout] -= 1
            if UI.timeout_register[self._timeout] == 0:
                UI.timeout_register.remove(self._timeout)
        if t > 0.0:
            UI.timeout_register[t] = UI.timeout_register.get(t,0) + 1
        self._timeout = t
    @timeout.deleter
    def timeout(self):
        del self._timeout

    @staticmethod
    def need_update(timeout):
        return timeout == 0.0 or timeout in UI.timeout_register.keys()

    @staticmethod
    def draw_all(timeout):
        for eref in UI.ui_elements:
            e = eref()
            if e is None:
                UI.ui_elements.remove(eref)
            else:
                if e.is_visible:
                    if e.timeout==0.0 or e.timeout>timeout:
                        e.draw()
        #if timeout == 0.0:
        #    print("%d UI elements"%len(UI.ui_elements))

    @staticmethod
    def clear_all():
        for eref in UI.ui_elements:
            e = eref()
            if e is not None:
                e.is_visible = False
                del e
        UI.ui_elements = []

    def refresh_ui_list(self):
        if not weakref.ref(self) in UI.ui_elements:
            UI.ui_elements.append(weakref.ref(self))


class Message(UI):
    def __init__(self, pos, text, centred=False, colour=None):
        UI.__init__(self)
        self.pos = pos
        self.text = text
        self.centred = centred
        self.colour = colour

    def draw(self):
        x = self.pos.x
        if self.centred:
            x -= len(self.text)//2
        if self.colour is None:
            libtcod.console_print(0, x, self.pos.y, self.text) #, libtcod.white, libtcod.BKGND_NONE)
        else:
            libtcod.console_print(0, x, self.pos.y, "%c%s%c"%(self.colour,self.text,self.COLCTRL_STOP))


class Bar(UI):
    def __init__(self, pos, size, fgcolours, bgcolour, show_numerator=True, show_denominator=False, text=None, text_align=str.center):
        UI.__init__(self)
        self.pos = pos
        self.size = size
        if not isinstance(fgcolours,list):
            fgcolours = [fgcolours]
        self.fgcolours = fgcolours
        self.bgcolour = bgcolour

        self.show_numerator = show_numerator
        self.show_denominator = show_denominator
        self.text = text
        self.text_align = text_align

        self.value = 0
        self.max_value = 1

        self.percentiles = [1.0]

    def draw(self):
        raise NotImplementedError


class HBar(Bar):
    
    def draw(self):
        assert len(self.percentiles)==len(self.fgcolours), "HBar not configured correctly"

        # calculate text
        s = ""
        if self.show_numerator:
            if self.show_denominator:
                s = "%d/%d"%(self.value,self.max_value)
            else:
                s = "%d"%(self.value)
        if self.text is not None:
            s = "%s %s"%(self.text,s)
        s = self.text_align(s,self.size)

        # draw bar
        fv = self.value/self.max_value
        fg_idx = 0
        for i in range(0,self.size):
            #calculate colour for this character
            f = (i+1)/self.size
            col = self.bgcolour
            if f<=fv: # part of bar fg
                while f>self.percentiles[fg_idx]:
                    fg_idx += 1
                    assert fg_idx < len(self.percentiles), "HBar not configured correctly"
                col = self.fgcolours[fg_idx]
            libtcod.console_put_char_ex(0, self.pos.x+i, self.pos.y, s[i], libtcod.white, col)


class Box(UI):
#    NW_CORNER = '\u250c'
#    NE_CORNER = '\u2510'
#    SW_CORNER = '\u2514'
#    SE_CORNER = '\u2518'
#    VERT_EDGE = '\u2502'
    HORI_EDGE = chr(libtcod.CHAR_HLINE)
    NW_CORNER = chr(libtcod.CHAR_NW)
    NE_CORNER = chr(libtcod.CHAR_NE)
    SW_CORNER = chr(libtcod.CHAR_SW)
    SE_CORNER = chr(libtcod.CHAR_SE)
    VERT_EDGE = chr(libtcod.CHAR_VLINE)
    T_LEFT    = chr(libtcod.CHAR_TEEE)
    T_RIGHT   = chr(libtcod.CHAR_TEEW)

    def __init__(self, pos, size, colour=libtcod.white, title=""):
        UI.__init__(self)
        self.pos = pos
        self.size = size
        self.colour = colour
        self.title = title


    def draw(self):
        libtcod.console_print(0, self.pos.x, self.pos.y, "%s%s%s"%(self.NW_CORNER,self.HORI_EDGE*(self.size.x-2),self.NE_CORNER))
        if self.title == "":
            for y in range(self.pos.y+1,self.pos.y+self.size.y):
                libtcod.console_print(0, self.pos.x, y, "%s%s%s"%(self.VERT_EDGE," "*(self.size.x-2),self.VERT_EDGE))
        else:
            # title
            libtcod.console_print(0, self.pos.x, self.pos.y+1, "%s%s%s"%(self.VERT_EDGE,self.title.center(self.size.x-2),self.VERT_EDGE))
            libtcod.console_print(0, self.pos.x, self.pos.y+2, "%s%s%s"%(self.T_LEFT,self.HORI_EDGE*(self.size.x-2),self.T_RIGHT))
            for y in range(self.pos.y+3,self.pos.y+self.size.y):
                libtcod.console_print(0, self.pos.x, y, "%s%s%s"%(self.VERT_EDGE," "*(self.size.x-2),self.VERT_EDGE))
        libtcod.console_print(0, self.pos.x, self.pos.y+self.size.y, "%s%s%s"%(self.SW_CORNER,self.HORI_EDGE*(self.size.x-2),self.SE_CORNER))



class MenuItem:
    def __init__(self, hotkey, text, fgcolour=libtcod.white, bgcolour=libtcod.black, is_selected=False):
        self.hotkey = hotkey
        self.text = text
        self.fgcolour = fgcolour
        self.bgcolour = bgcolour
        self.is_selected = is_selected

    def draw_at(self, pos):
        x = "( )"
        if self.is_selected:
            x = "(X)"
        libtcod.console_print(0, pos.x, pos.y, " %s. %s %s"%(self.hotkey,self.text,x))


class MenuItemSpacer(MenuItem):
    def __init__(self):
        self.hotkey = None

    def draw_at(self,pos):
        pass


class Menu(Box):
    def __init__(self, pos, size, colour=libtcod.white, title=""):
        Box.__init__(self, pos, size, colour, title)
        self.__items = []

    def add(self, hotkey, text, fgcolour=libtcod.white, bgcolour=libtcod.black):
        self.__items.append( MenuItem(hotkey,text,fgcolour,bgcolour,len(self.__items)==0) )

    def add_spacer(self):
        self.__items.append( MenuItemSpacer() )

    def draw(self):
        Box.draw(self)
        dh = (self.size.y-4) // (len(self.__items)+1)
        h = dh + 2
        for i in self.__items:
            i.draw_at( self.pos+(2,h) )
            h += dh

    def sel_index(self):
        for i in range(len(self.__items)):
            if self.__items[i].is_selected:
                return i
        assert False, "No item selected in menu!"

    def sel_next(self):
        i = self.sel_index()
        if i == len(self.__items)-1:
            return False
        self.__items[i].is_selected = False
        self.__items[i+1].is_selected = True
        if isinstance(self.__items[i+1],MenuItemSpacer):
            return self.sel_next()
        return True

    def sel_prev(self):
        i = self.sel_index()
        if i == 0:
            return False
        self.__items[i].is_selected = False
        self.__items[i-1].is_selected = True
        if isinstance(self.__items[i-1],MenuItemSpacer):
            return self.sel_prev()
        return True

    def get_key(self):
        self.is_visible = True
        r = None
        while 1:
            self.draw()
            libtcod.console_flush()
            k = libtcod.console_wait_for_keypress(True)
            if k and k.pressed and k.c:
                c = chr(k.c)
                if c in [i.hotkey for i in self.__items]:
                    r = c
                    break
                elif c == 'j':
                    self.sel_prev()
                elif c == 'k':
                    self.sel_next()
                elif c == ' ':
                    if self.sel_index() != 0:
                        r = self.__items[self.sel_index()].hotkey
                    break
            self.is_visible = False

        # TODO: player.redraw_screen()

        return r
