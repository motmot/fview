traits_version = None
try:
    # Enthought library imports
    import enthought.traits.api as traits
    from enthought.traits.api import on_trait_change
    traits_version = 3
except ImportError:
    # traits 4
    import traits.api as traits
    from traits.api import on_trait_change
    traits_version = 4

if traits_version==3:
    import enthought.traits.api as traits
    from enthought.traits.ui.api import View, Item, Group, RangeEditor
elif traits_version==4:
    import traits.api as traits
    from traitsui.api import View, Item, Group, RangeEditor
else:
  raise RuntimeError('could not identify traits')

import wx
import motmot.wxvideo.wxvideo as wxvideo

class HasTraits_FViewPlugin(traits.HasTraits):
    """Base class for traits-based plugin for fview.

    Subclass this class to create a plugin for fview. Override any
    methods desired -- this is just boilerplate to keep the fview app
    happy.

    """
    plugin_name = traits.Str('generic fview plugin') # set this in derived class
    frame = traits.Any # wxpython frame

    def __init__(self,wx_parent,wxframe_args=None,fview_options=None):
        if wxframe_args is None:
            wxframe_args = (-1,self.plugin_name)

        self.frame = wx.Frame(wx_parent,*wxframe_args)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        control = self.edit_traits( parent=self.frame,
                                    kind='subpanel',
                                    ).control
        sizer.Add(control, 1, wx.EXPAND)
        self.frame.SetSizer(sizer)
        self.frame.SetAutoLayout(True)

    def get_frame(self):
        """return wxPython frame widget"""
        return self.frame

    def get_plugin_name(self):
        return self.plugin_name

    def camera_starting_notification(self,cam_id,
                                     pixel_format=None,
                                     max_width=None,
                                     max_height=None):
        pass

    def quit(self):
        pass

    def process_frame(self,cam_id,buf,buf_offset,timestamp,framenumber):
        """do work on each frame

        This function gets called on every single frame capture. It is
        called within the realtime thread, NOT the wxPython
        application mainloop's thread. Therefore, be extremely careful
        (use threading locks) when sharing data with the rest of the
        class.

        """
        draw_points = [] #  [ (x,y) ]
        draw_linesegs = [] # [ (x0,y0,x1,y1) ]
        return draw_points, draw_linesegs

    def set_view_flip_LR( self, val ):
        pass

    def set_view_rotate_180( self, val ):
        pass

__all__ = ['HasTraits_FViewPlugin',
           'wx', 'wxvideo',
           'traits',
           'View', 'Item', 'Group', 'RangeEditor'
]

