import pkg_resources
import wx
import os

def load_plugins(wxframe):
    PluginClasses = []
    loaded_components = []
    pkg_env = pkg_resources.Environment()
    for name in pkg_env:
        egg = pkg_env[name][0]
        modules = []

        for name in egg.get_entry_map('cam_iface.fview_plugins'):
            egg.activate()
            entry_point = egg.get_entry_info('cam_iface.fview_plugins', name)
            if entry_point.module_name not in loaded_components:
                try:
                    PluginClass = entry_point.load()
                except Exception,x:
                    if int(os.environ.get('FVIEW_RAISE_ERRORS','0')):
                        raise
                    else:
                        import warnings
                        warnings.warn('could not load plugin %s: %s'%(str(entry_point),str(x)))
                        continue
                PluginClasses.append( PluginClass )
                modules.append(entry_point.module_name)
                loaded_components.append(entry_point.module_name)
    # make instances of plugins
    plugins = [PluginClass(wxframe) for PluginClass in PluginClasses]
    plugin_dict = {}
    for plugin in plugins:
        class PluginHelper:
            def __init__(self,plugin):
                self.plugin = plugin
                self.frame = plugin.get_frame()
                wx.EVT_CLOSE(self.frame, self.OnWindowClose)
            def OnWindowClose(self,event):
                # don't really close the window, just hide it
                self.frame.Show(False)
            def OnShowFrame(self,event):
                self.frame.Show(True)
        plugin_dict[plugin] = PluginHelper(plugin)
    return plugins, plugin_dict
