import pkg_resources
import wx
import os
import warnings, traceback

def load_plugins(wxframe):
    PluginClasses = []
    loaded_components = []
    pkg_env = pkg_resources.Environment()
    for name in pkg_env:
        egg = pkg_env[name][0]
        modules = []

        for name in egg.get_entry_map('motmot.fview.plugins'):
            egg.activate()
            entry_point = egg.get_entry_info('motmot.fview.plugins', name)
            if entry_point.module_name not in loaded_components:
                try:
                    PluginClass = entry_point.load()
                except Exception,x:
                    if int(os.environ.get('FVIEW_RAISE_ERRORS','0')):
                        raise
                    else:
                        formatted_error = traceback.format_exc(x)
                        warnings.warn('could not load plugin (set env var '
                                      'FVIEW_RAISE_ERRORS to raise error) '
                                      '%s: %s\n%s'%(str(entry_point),str(x),
                                                    formatted_error))
                        msg = 'While attempting to open the plugin "%s",\n' \
                              'FView encountered an error. The error is:\n\n' \
                              '%s\n\n' \
                              'More details:\n' \
                              '%s'%( name, x, formatted_error )
                        dlg = wx.MessageDialog(wxframe, msg,
                                               'FView plugin error',
                                               wx.OK | wx.ICON_WARNING)
                        dlg.ShowModal()
                        dlg.Destroy()
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
