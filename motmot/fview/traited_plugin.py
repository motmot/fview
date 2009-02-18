import enthought.traits.api as traits
import wx

class HasTraits_FViewPlugin(traits.HasTraits):
    """Base class for traits-based plugin for fview.

    Subclass this class to create a plugin for fview. Override any
    methods desired -- this is just boilerplate to keep the fview app
    happy.

    """
    plugin_name = traits.Str('generic fview plugin') # set this in derived class
    frame = traits.Any # wxpython frame

    def __init__(self,wx_parent,*args,**kwargs):
        if 'wxFrame args' in kwargs:
            frame_args=kwargs['wxFrame args']
            del kwargs['wxFrame args']
        else:
            frame_args=(-1,self.plugin_name) # empty tuple
        self.frame = wx.Frame(wx_parent,*frame_args)
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
