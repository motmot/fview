import pkg_resources
import wx
import sys, os
import warnings, traceback

def load_plugins(wxframe,use_plugins=None,return_plugin_names=False,**fview_options):
    """
    Optional arguments
    ------------------
    use_plugins - list
    list of plugin numbers to load
    return_plugin_names - boolean
    if True, return ordered list of plugin names and do nothing else
    """
    PluginClassesAndNames = []
    loaded_components = []
    pkg_env = pkg_resources.Environment()
    count = 0
    plugin_names = []

    #use_plugins can be either a string or an integer plugin number
    #(confusing I know). Command line API retained for backwards
    #compatibility...
    use_plugins_num = []
    use_plugins_name = []
    if use_plugins is not None:
        for p in use_plugins:
            try:
                use_plugins_num.append( int(p) )
            except ValueError:
                use_plugins_name.append( p )

    for name in pkg_env:
        egg = pkg_env[name][0]
        modules = []

        for name in egg.get_entry_map('motmot.fview.plugins'):
            this_plugin_number = count
            count += 1
            plugin_names.append(name)
            if return_plugin_names:
                continue

            use = False
            if use_plugins is None:
                use = True
            else:
                if use_plugins_num and (this_plugin_number in use_plugins_num):
                    use = True
                if use_plugins_name and (name in use_plugins_name):
                    use = True

            if not use:
                continue

            egg.activate()
            entry_point = egg.get_entry_info('motmot.fview.plugins', name)
            if entry_point.module_name not in loaded_components:
                try:
                    PluginClass = entry_point.load()
                except Exception,x:
                    if int(os.environ.get('FVIEW_RAISE_ERRORS','0')):
                        print >> sys.stderr,'ERROR while loading %s'%(
                            entry_point.module_name,)
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
                PluginClassesAndNames.append( (PluginClass,name) )
                modules.append(entry_point.module_name)
                loaded_components.append(entry_point.module_name)
    if return_plugin_names:
        return plugin_names

    # make instances of plugins
    plugins = []
    plugin_names = []
    bad_plugins = {}
    for PluginClass,name in PluginClassesAndNames:
        try:
            instance = PluginClass(wxframe,fview_options=fview_options)
        except Exception,err:
            formatted_error = traceback.format_exc(err)
            bad_plugins[name] = (str(err), formatted_error)
            traceback.print_exc(err,sys.stderr)
        else:
            plugins.append( instance )
            plugin_names.append(name)
    plugin_dict = {}
    for plugin in plugins:
        class PluginHelper:
            def __init__(self,plugin):
                self.plugin = plugin
                self.frame = plugin.get_frame()
                wx.EVT_CLOSE(self.frame, self.OnWindowClose)
            def Destroy(self):
                self.frame.Destroy()
            def OnWindowClose(self,event):
                # don't really close the window, just hide it
                self.frame.Show(False)
            def OnShowFrame(self,event):
                self.frame.Show(True)
        plugin_dict[plugin] = PluginHelper(plugin)
    return plugins, plugin_dict, bad_plugins, plugin_names

