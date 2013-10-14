import threading
import numpy as np

def ros_ensure_valid_name(name):
    return name.replace('-','_')

def lineseg_box(xmin, ymin, xmax, ymax):
    return [ [xmin,ymin,xmin,ymax],
             [xmin,ymax,xmax,ymax],
             [xmax,ymax,xmax,ymin],
             [xmax,ymin,xmin,ymin],
     ]

def lineseg_circle(x,y,radius,N=64):
    draw_linesegs = []

    theta = np.arange(N)*2*np.pi/N
    xdraw = x+np.cos(theta)*radius
    ydraw = y+np.sin(theta)*radius
    for i in range(N-1):
        draw_linesegs.append(
            (xdraw[i],ydraw[i],xdraw[i+1],ydraw[i+1]))
    draw_linesegs.append(
        (xdraw[-1],ydraw[-1],xdraw[0],ydraw[0]))

    return draw_linesegs


class SharedValue:
    def __init__(self):
        self.evt = threading.Event()
        self._val = None
    def set(self,value):
        # called from producer thread
        self._val = value
        self.evt.set()
    def is_new_value_waiting(self):
        return self.evt.isSet()
    def get(self,*args,**kwargs):
        # called from consumer thread
        self.evt.wait(*args,**kwargs)
        val = self._val
        self.evt.clear()
        return val
    def get_nowait(self):
        # XXX TODO this is not atomic and is thus dangerous.
        # (The value could get read, then another thread could set it,
        # and only then might it get flagged as clear by this thread,
        # even though a new value is waiting.)
        val = self._val
        self.evt.clear()
        return val

class SharedValue1(object):
    def __init__(self,initial_value):
        self._val = initial_value
        self.lock = threading.Lock()
    def get(self):
        self.lock.acquire()
        try:
            val = self._val
        finally:
            self.lock.release()
        return val
    def set(self,new_value):
        self.lock.acquire()
        try:
            self._val = new_value
        finally:
            self.lock.release()
