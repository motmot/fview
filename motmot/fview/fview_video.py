import wx
import wx.xrc as xrc
import pkg_resources
import numpy
import motmot.imops.imops as imops
import pyglet.gl as gl

from pygarrayimage.arrayimage import ArrayInterfaceImage

import motmot.wxglvideo.wxglvideo as vid

class PointDisplayCanvas( vid.DynamicImageCanvas ):
    def __init__(self,*args,**kw):
        super(PointDisplayCanvas, self).__init__(*args,**kw)
        self.extra_points_linesegs = ([], [])

    def core_draw(self):
        super(PointDisplayCanvas, self).core_draw()

        points,linesegs = self.extra_points_linesegs
        gl.glColor4f(0.0,1.0,0.0,1.0) # green point

        gl.glBegin(gl.GL_POINTS)
        for pt in points:
            gl.glVertex2f(pt[0],pt[1])
        gl.glEnd()

        gl.glColor4f(1.0,1.0,1.0,1.0) # green point

    def extra_initgl(self):
        gl.glEnable( gl.GL_POINT_SMOOTH )
        gl.glPointSize(5)

class DynamicImageCanvas(wx.Panel):
    def __init__(self,*args,**kw):
        super(DynamicImageCanvas, self).__init__(*args,**kw)

        self.rotate_180 = False
        self.flip_lr = False

        self.children = {}
        self.green_points = {}
        self.red_points = {}
        self.lbrt = {}

        self.box = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(self.box)
        #wx.EVT_IDLE( self, self.OnIdle )

    def _new_child(self,id_val,image):
        child = PointDisplayCanvas(self,-1)
        child.set_fullcanvas(True)
        self.box.Add( child, 1, wx.EXPAND)
        self.Layout()
        pygim = ArrayInterfaceImage( image, allow_copy=False )
        child.new_image( pygim )
        child.set_rotate_180( self.rotate_180 )
        child.set_flip_lr( self.flip_lr )

        self.children[id_val] = child
        self.green_points[id_val] = []
        self.red_points[id_val] = []
        self.lbrt[id_val] = ()

    def set_rotate_180(self, value):
        self.rotate_180 = value
        for id_val in self.children:
            child = self.children[id_val]
            child.set_rotate_180(value)

    def set_flip_LR(self, value):
        self.flip_lr = value
        for id_val in self.children:
            child = self.children[id_val]
            child.set_flip_lr(value)

    def set_green_points(self,id_val,points):
        self.green_points[id_val]=points

    def set_red_points(self,id_val,points):
        self.red_points[id_val]=points

    def set_lbrt(self,id_val,lbrt):
        self.lbrt[id_val]=lbrt

    def update_image(self, id_val, image, format='MONO8',
                     xoffset=0, yoffset=0):
        image=numpy.asarray(image)
        if format == 'RGB8':
            image = imops.rgb8_to_rgb8( image )
        elif format == 'ARGB8':
            image = imops.argb8_to_rgb8( image )
        elif format == 'YUV411':
            image = imops.yuv411_to_rgb8( image )
        elif format == 'YUV422':
            image = imops.yuv422_to_rgb8( image )
        elif format == 'MONO8':
            pass
        elif format == 'RAW8':
            pass
        elif format == 'MONO16':
            image = imops.mono16_to_mono8_middle8bits( image )
        else:
            raise ValueError("Unknown format '%s'"%(format,))

        if id_val not in self.children:
            # The line gives us:
            #  Gtk-CRITICAL **: gtk_widget_set_colormap: assertion `!GTK_WIDGET_REALIZED (widget)' failed
            self._new_child(id_val,image)
        else:
            child = self.children[id_val]
            child.update_image(image)
            #child.extra_points_linesegs = ([],[])

    def update_image_and_drawings(self,
                                  id_val,
                                  image,
                                  format='MONO8',
                                  points=None,
                                  linesegs=None,
                                  xoffset=0,
                                  yoffset=0):

        try:
            child = self.children[id_val]
        except KeyError:
            # XXX BUG: on the first frame for this camera, no points will be drawn
            pass
        else:
            child.extra_points_linesegs = points, linesegs

        self.update_image( id_val,
                           image,
                           format=format,
                           xoffset=xoffset,
                           yoffset=yoffset)
        # draw points and linesegs
        if points is None:
            points = []
        if linesegs is None:
            linesegs = []

    def OnIdle(self, event):
        for id_val in self.children:
            child = self.children[id_val]
            child.OnDraw()
        event.RequestMore( True )
