import enthought.traits.api as traits
import wx

class HasTraits_FViewPlugin(traits.HasTraits):
    """plugin for fview.

    This class implements everything necessary to be a valid fview
    plugin.

    """
    plugin_name = traits.Str('generic fview plugin') # set this in derived class

    def __init__(self,wx_parent,*args,**kwargs):
        self.frame = wx.Frame(wx_parent)
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
