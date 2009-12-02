#!/usr/bin/env python
from __future__ import with_statement
import threading, time, sys, os
import Queue
import motmot.utils.config
import pkg_resources # from setuptools

from version import __version__ # fview.version

import wx
import motmot.wxvalidatedtext.wxvalidatedtext as wxvt
from optparse import OptionParser

# set environment variable before importing cam_iface (camwire on linux)
A602f_conf = pkg_resources.resource_filename(__name__,'A602f.conf')
# other conf files in same directory, so this works for any camera
conf_dir = os.path.split(A602f_conf)[0]
os.environ['CAMWIRE_CONF'] = conf_dir

import motmot.cam_iface.choose as cam_iface_choose
cam_iface = None
import numpy as nx
import numpy as np
import motmot.FlyMovieFormat.FlyMovieFormat as FlyMovieFormat

from wx import xrc
import plugin_manager
import traceback

if int(os.environ.get('FVIEW_NO_OPENGL','0')):
    import motmot.wxvideo.wxvideo as video_module
else:
    import motmot.wxglvideo.simple_overlay as video_module

# trigger extraction
RESFILE = pkg_resources.resource_filename(__name__,"fview.xrc")
RESDIR = os.path.split(RESFILE)[0]
RES = xrc.EmptyXmlResource()
RES.LoadFromString(open(RESFILE).read())

def my_loadpanel(parent,panel_name):
    orig_dir = os.path.abspath(os.curdir)
    if os.path.exists(RESDIR): # sometimes RESDIR can be "" (GH-1)
        os.chdir(RESDIR)
    try:
        result = RES.LoadPanel(parent,panel_name)
    finally:
        os.chdir(orig_dir)
    return result

########
# persistent configuration data ( implementation in motmot.utils.config )
def get_rc_params():
    defaultParams = {
        'backend' : 'unity',
        'wrapper' : 'ctypes',
        'flipLR'  : True,
        'rotate180'  : False,
        'view_interval' : 1,
        }
    fviewrc_fname = motmot.utils.config.rc_fname(filename='fviewrc',
                                                 dirname='.fview')
    rc_params = motmot.utils.config.get_rc_params(fviewrc_fname,
                                                  defaultParams)
    return rc_params
def save_rc_params():
    save_fname = motmot.utils.config.rc_fname(must_already_exist=False,
                                              filename='fviewrc',
                                              dirname='.fview')
    motmot.utils.config.save_rc_params(save_fname,rc_params)
rc_params = get_rc_params()
########

# use to trigger GUI thread action from grab thread
CamPropertyDataReadyEvent = wx.NewEventType()

# use to trigger GUI thread action from grab thread
CamROIDataReadyEvent = wx.NewEventType()

# use to trigger GUI thread action from grab thread
ImageReadyEvent = wx.NewEventType()

# use to trigger GUI thread action from grab thread
CamFramerateReadyEvent = wx.NewEventType()

# use to trigger GUI thread action from grab thread
FViewShutdownEvent = wx.NewEventType()

USE_DEBUG = bool(int(os.environ.get('FVIEW_DEBUG','0')))

def DEBUG():
    print 'line %d thread %s'%(sys._getframe().f_back.f_lineno,
                               threading.currentThread())

class WindowsTimeHack:
    def __init__(self):
        tmp = time.clock()
        self.t1 = time.time()
    def time(self):
        return time.clock() + self.t1

if sys.platform == 'win32':
    thack = WindowsTimeHack()
    time_func = thack.time
else:
    time_func = time.time

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

VENDOR_MODEL_SHUTTER_TEXT = {'Basler':{'A602f':'Shutter (msec):',
                                       'A622f':'Shutter (msec):',
                                       },
                             }

VENDOR_MODEL_SHUTTER_SCALE = {'Basler':{'A602f':0.02, # msecs per tick
                                        'A622f':0.02, # msecs per tick
                                        },
                              }

in_fnt = Queue.Queue()

def grab_func(wxapp,
              image_update_lock,
              cam,
              cam_id,
              max_priority_enabled,
              quit_now,
              thread_done,
              fps_value,
              framerate_value,
              num_buffers_value,
#AR              app_ready,
              plugins,
              cam_prop_get_queue,
              cam_roi_get_queue,
              framerate_get_queue,
              cam_cmd_queue,
              fview_ext_trig_plugin,
              ):
    # transfer data from camera
    global in_fnt

    def showerr(str):
        print str

    max_priority_enabled.clear()

    if sys.platform.startswith('linux'):
        # Not all POSIX platforms support sched_getparam(). See
        # http://lists.apple.com/archives/Unix-porting/2005/Jul/msg00027.html
        import posix_sched
        try:
            max_priority = posix_sched.get_priority_max( posix_sched.FIFO )
            sched_params = posix_sched.SchedParam(max_priority)
            posix_sched.setscheduler(0, posix_sched.FIFO, sched_params)
            max_priority_enabled.set()
        except Exception, x:
            pass # not really a problem, just not in maximum priority mode

    n_frames = 0
    good_n_frames = 0
    start = None
#AR    app_ready.wait() # delay before starting camera to let wx start

    if hasattr(cam,'set_thread_owner'):
        cam.set_thread_owner()

    max_width = cam.get_max_width()
    max_height = cam.get_max_height()

    cam.start_camera()

    if 1:
        # This reduces likelihood of frame corruption on libdc1394
        # 2.1.0 with Firefly MV USB cameras. Tested on Ubuntu 8.04
        # amd64 with libusb-1.0.1.
        time.sleep(0.1)

    # semi-hack to maximize hardware ROI on start
    try: cam.set_frame_roi(0,0,max_width,max_height)
    except cam_iface.CamIFaceError, err:
        print ('fview warning: ignoring error on set_frame_roi() '
               'while trying to maximize ROI at start')

    l,b,w,h = cam.get_frame_roi()
    xyoffset = l,b

    # find memory allocator from plugins (e.g. FastImage)
    buf_allocator = None
    for plugin in plugins:
        if hasattr(plugin,'get_buffer_allocator'):
            buf_allocator = plugin.get_buffer_allocator(cam_id)
            if buf_allocator is not None:
                break # use first allocator

    send_framerate = False
    timestamp_source = 'camera driver'

    try:
        while not quit_now.isSet():
            try:
                if buf_allocator is None:
                    cam_iface_buf = cam.grab_next_frame_blocking()
                else:
                    # shorthand
                    func = cam.grab_next_frame_into_alloced_buf_blocking
                    cam_iface_buf = func(buf_allocator)
                    del func
                this_frame_has_good_data = True
            except cam_iface.BuffersOverflowed:
                showerr('WARNING: buffers overflowed, frame numbers off')
                continue
            except (cam_iface.FrameSystemCallInterruption, cam_iface.NoFrameReturned):
                # re-try
                continue
            except cam_iface.FrameDataMissing:
                #showerr('WARNING: frame data missing')
                this_frame_has_good_data = False
            except cam_iface.FrameDataCorrupt:
                #showerr('WARNING: frame data missing')
                this_frame_has_good_data = False
            if USE_DEBUG:
                sys.stdout.write('.')
                sys.stdout.flush()

            try:
                camera_driver_timestamp=cam.get_last_timestamp()
            except cam_iface.CamIFaceError, err:
                # XXX this is a hack to deal with trouble getting timestamp
                camera_driver_timestamp = -time.time()
            fno = cam.get_last_framenumber()
            now = time_func()
            if start is None:
                start = now
            n_frames += 1

            if not this_frame_has_good_data:
                continue

            plugin_points = []
            plugin_linesegs = []
            if fview_ext_trig_plugin is not None:
                points,linesegs = fview_ext_trig_plugin.process_frame(
                    cam_id, cam_iface_buf, xyoffset, camera_driver_timestamp, fno )
                plugin_points.extend( points )
                plugin_linesegs.extend( linesegs )

            if timestamp_source == 'camera driver':
                use_timestamp = camera_driver_timestamp # from camera driver
            elif timestamp_source == 'host clock':
                use_timestamp = now # from computer's own clockcamera driver
            elif timestamp_source == 'CamTrig':
                use_timestamp = fview_ext_trig_plugin.get_last_trigger_timestamp(cam_id)
            else:
                raise ValueError('unknown camera timestamp source')

            good_n_frames += 1

            for plugin in plugins:
                if plugin is fview_ext_trig_plugin:
                    # already did this plugin above
                    continue
                points,linesegs = plugin.process_frame(
                    cam_id, cam_iface_buf, xyoffset, use_timestamp, fno )
                plugin_points.extend( points )
                plugin_linesegs.extend( linesegs )

            #buf = nx.asarray(cam_iface_buf)
            image_update_lock.acquire()
            wxapp.last_image_fullsize = (max_width,max_height)
            wxapp.last_image = cam_iface_buf # frame
            wxapp.last_offset = xyoffset
            wxapp.new_image = True
            wxapp.plugin_points = plugin_points
            wxapp.plugin_linesegs = plugin_linesegs
            image_update_lock.release()

            event = wx.CommandEvent(ImageReadyEvent)
            event.SetEventObject(wxapp)
            wx.PostEvent(wxapp, event)

            if in_fnt.qsize() < 1000:
                # save a copy of the buffer
                in_fnt.put( (cam_iface_buf, xyoffset, use_timestamp, fno) )
            else:
                showerr('ERROR: not appending new frame to queue, because '
                        'it already has 1000 frames!')

            if now - start > 1.0:
                fps = n_frames/(now-start)
                good_fps = good_n_frames/(now-start)
                start = now
                n_frames = 0
                good_n_frames = 0
                fps_value.set((fps,good_fps))

            if framerate_value.is_new_value_waiting():
                fr = framerate_value.get_nowait()
                try:
                    cam.set_framerate(fr)
                except Exception, err:
                    showerr('ignoring error setting framerate: '+str(err))
                except:
                    showerr('ignoring error setting framerate')
                send_framerate = True

            if num_buffers_value.is_new_value_waiting():
                nb = num_buffers_value.get_nowait()
                try:
                    cam.set_num_framebuffers(nb)
                except Exception, err:
                    showerr('ignoring error setting number of framebuffers: '
                            '%s'%err)
                except:
                    showerr('ignoring error setting number of framebuffers')
                send_framerate = True

            try:
                while 1:
                    cmd,cmd_payload = cam_cmd_queue.get_nowait()
                    if cmd == 'property change':
                        prop_num,new_value,set_auto = cmd_payload
                        try:
                            cam.set_camera_property(
                                prop_num, new_value, set_auto )
                        except Exception, err:
                            showerr('ignoring error setting property: %s'%err)
                        value,auto = cam.get_camera_property( prop_num )
                        cam_prop_get_queue.put( (prop_num, value, auto) )
                        event = wx.CommandEvent(CamPropertyDataReadyEvent)
                        event.SetEventObject(wxapp)
                        wx.PostEvent(wxapp, event)
                    elif cmd == 'property query':
                        num_props = cam.get_num_camera_properties()
                        for prop_num in range(num_props):
                            value,auto = cam.get_camera_property( prop_num )
                            cam_prop_get_queue.put( (prop_num, value, auto) )
                        event = wx.CommandEvent(CamPropertyDataReadyEvent)
                        event.SetEventObject(wxapp)
                        wx.PostEvent(wxapp, event)
                    elif cmd == 'ROI query':
                        l,b,w,h = cam.get_frame_roi()
                        r = l+w
                        t = b+h
                        cam_roi_get_queue.put( (l,b,r,t) )
                        event = wx.CommandEvent(CamROIDataReadyEvent)
                        event.SetEventObject(wxapp)
                        wx.PostEvent(wxapp, event)
                    elif cmd == 'ROI set':
                        l,b,r,t = cmd_payload
                        w = r-l
                        h = t-b
                        try:
                            # if camera needs to be stopped for these
                            # operations, do it in the driver (not all
                            # cameras must be stopped).
                            cam.set_frame_roi(l,b,w,h)
                            xyoffset = l,b
                        except cam_iface.CamIFaceError, x:
                            # error setting frame size/offset
                            sys.stderr.write('fview ignoring error when '
                                             'attempting to set ROI: %s\n'%(x,))
                        else:
                            # send ROI back out to GUI thread if no error
                            cam_roi_get_queue.put( (l,b,r,t) )
                            event = wx.CommandEvent(CamROIDataReadyEvent)
                            event.SetEventObject(wxapp)
                            wx.PostEvent(wxapp, event)
                    elif cmd=='TriggerMode Set':
                        cam.set_trigger_mode_number(cmd_payload)
                        send_framerate = True
                    elif cmd=='framerate query':
                        send_framerate = True
                    elif cmd=='timestamp source':
                        timestamp_source = cmd_payload
                    else:
                        raise ValueError('unknown command: %s'%cmd)
            except Queue.Empty:
                pass

            if send_framerate:
                # framerate
                current_framerate = cam.get_framerate()
                trigger_mode = cam.get_trigger_mode_number()
                num_buffers = cam.get_num_framebuffers()

                framerate_get_queue.put(
                    (current_framerate,trigger_mode,num_buffers) )
                event = wx.CommandEvent(CamFramerateReadyEvent)
                event.SetEventObject(wxapp)
                wx.PostEvent(wxapp, event)
                # do num_buffers
                send_framerate = False

    finally:
        try:
            cam.close()
        except Exception,err:
            print 'ERROR trying to close camera:',err
        thread_done.set()

def save_func(wxapp,
              save_info_lock,
              quit_now,
              ):
    """save function for running in separate thread

    It's important to save data in a thread separate from the grab
    thread because we don't want to skip frames and it's important to
    be outside the GUI mainloop, because we don't want to block user
    input.

    """

    # transfer data from camera
    global in_fnt

    while not quit_now.isSet():
        try:
            while 1: # process each frame
                frame, xyoffset, timestamp, fno = in_fnt.get(0)
                if wxapp.save_fno:
                    save_temporal_value = float(fno)
                else:
                    save_temporal_value = timestamp

                # lock should be held to use wxapp.save_images and
                # wxapp.fly_movie

                with save_info_lock:
                    nth_frame = wxapp.save_images
                    if nth_frame:
                        if fno%nth_frame==0:
                            wxapp.fly_movie.add_frame(frame,save_temporal_value)

        except Queue.Empty:
            pass
        time.sleep(0.1) # give other threads plenty of time

class CameraParameterHelper:
    def __init__(self, cam, wxparent, wxsizer, prop_num, fview_app ):
        """

        This __init__ method gets called while cam has not been passed
        off to grab thread, and thus can directly manipulate cam.

        """
        self.prop_num = prop_num
        del prop_num

        self.fview_app = fview_app
        del fview_app

        self.present = True
        self.props = cam.get_camera_property_info(self.prop_num)
        if not self.props['is_present']:
            self.present = False
            return
        elif ('available' in self.props and # added in libcamiface 0.5.7, motmot.camiface 0.4.8
              not self.props['available']):
                self.present = False
                return
        elif not self.props['has_manual_mode']:

            # Temperature on Dragonfly2 doesn't like to be read out,
            # even though it reports being readout_capable. Don't
            # build a control for it.

            # (TODO: self.props['original_value'] could be used to set
            # the value in the GUI and get_camera_property could not
            # be called.)
            self.present = False
            return

        self.current_value, self.current_is_auto = cam.get_camera_property(
            self.prop_num)

        label = self.props['name']+':'
        if self.props['is_scaled_quantity']:
            label += ' (%s)'%(self.props['scaled_unit_name'],)
        statictext = wx.StaticText(wxparent,label=label)
        wxsizer.Add(statictext,flag=wx.ALIGN_CENTRE_VERTICAL)

        self.slider = wx.Slider(wxparent,
                                style=wx.SL_HORIZONTAL)

        minv = self.props['min_value']
        maxv = self.props['max_value']
        if minv == maxv:
            self.slider.SetRange(minv-1,maxv+1)
            self.slider.Enable(False)
        else:
            self.slider.SetRange(minv,maxv)
        wx.EVT_COMMAND_SCROLL(self.slider, self.slider.GetId(), self.OnScroll)

        wxsizer.Add(self.slider,
                    flag=wx.ALIGN_CENTRE_VERTICAL|wx.TOP|wx.BOTTOM|wx.EXPAND,
                    border=5)

        self.scaledtext = wx.TextCtrl(wxparent)
        if self.props['is_scaled_quantity']:
            self.validator = wxvt.setup_validated_float_callback(
                self.scaledtext, self.scaledtext.GetId(),
                self.OnSetScaledValue,
                ignore_initial_value=True)
        else:
            self.validator = wxvt.setup_validated_integer_callback(
                self.scaledtext, self.scaledtext.GetId(),
                self.OnSetRawValue,
                ignore_initial_value=True)
        wxsizer.Add(self.scaledtext)

        self.auto_widget = wx.CheckBox(wxparent,-1,'auto')
        wxsizer.Add(self.auto_widget)
        num_auto_modes = (self.props['has_manual_mode'] +
                          self.props['has_auto_mode'])
        self.auto_widget.SetValue(self.current_is_auto)
        if num_auto_modes < 2:
            self.auto_widget.Enable(False)

        wx.EVT_CHECKBOX(
            self.auto_widget, self.auto_widget.GetId(), self.OnToggleAuto)

        self.other_updates = []
        self.Update()

        self.fview_app.register_property_query_callback(
            self.prop_num, self.OnReceiveProperty)

    def OnReceiveProperty(self, value, auto):
        self.current_value, self.current_is_auto = value, auto
        self.Update()

    def AddToUpdate(self,ou):
        self.other_updates.append( ou )
    def Update(self, event=None):
        self.slider.SetValue(self.current_value)
        self.auto_widget.SetValue( self.current_is_auto )
        if self.props['is_scaled_quantity']:
            self.scaledtext.SetValue(
                str(self.current_value*self.props['scale_gain']
                    +self.props['scale_offset']) )
        else:
            self.scaledtext.SetValue( str(self.current_value) )
        self.validator.set_state('valid')

    def OnScroll(self, event):
        widget = event.GetEventObject()
        new_value = widget.GetValue()
        self.fview_app.enqueue_property_change(
            (self.prop_num,new_value,self.current_is_auto) )
        self.current_value = new_value
        self._UpdateSelfAndOthers()

    def OnSetScaledValue(self,event):
        # we know this is a valid float
        widget = event.GetEventObject()
        new_value_scaled = float(widget.GetValue())
        new_value = ((new_value_scaled-self.props['scale_offset']) /
                     self.props['scale_gain'])
        new_value = int(round(new_value))
        self.fview_app.enqueue_property_change(
            (self.prop_num,new_value,self.current_is_auto) )
        self.current_value = new_value
        self._UpdateSelfAndOthers()

    def OnSetRawValue(self,event):
        # we know this is a valid int
        widget = event.GetEventObject()
        new_value = int(widget.GetValue())
        self.fview_app.enqueue_property_change(
            (self.prop_num,new_value,self.current_is_auto) )
        self.current_value = new_value
        self._UpdateSelfAndOthers()

    def OnToggleAuto(self, event):
        widget = event.GetEventObject()
        set_auto = widget.IsChecked()
        self.current_is_auto = set_auto
        self.fview_app.enqueue_property_change(
            (self.prop_num,self.current_value,set_auto) )
        self._UpdateSelfAndOthers()

    def _UpdateSelfAndOthers(self, event=None):
        self.Update()
        for ou in self.other_updates:
            ou.Update()

class InitCameraDialog(wx.Dialog):
    def __init__(self,*args,**kw):
        cam_info = kw['cam_info']
        del kw['cam_info']
        wx.Dialog.__init__(self,*args,**kw)

        sizer = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(self, -1, "Select camera and parameters")
        font = wx.Font(14, wx.SWISS, wx.NORMAL, wx.NORMAL)
        label.SetFont(font)
        sizer.Add(label, 0, wx.ALIGN_CENTRE_HORIZONTAL|wx.ALL, 5)

        label = wx.StaticText(
            self, -1, "Note: this program does not support hotplugging.")
        sizer.Add(label, 0, wx.ALIGN_CENTRE_HORIZONTAL|wx.ALL, 5)
        del label

        line = wx.StaticLine(self, -1, size=(20,-1), style=wx.LI_HORIZONTAL)
        sizer.Add(line, 0, wx.GROW|wx.ALIGN_CENTER_VERTICAL|wx.RIGHT|wx.TOP, 5)
        del line

        # build flexgrid
        ncols = 3
        flexgridsizer = wx.FlexGridSizer( -1, ncols )
        for i in range(ncols):
            flexgridsizer.AddGrowableCol(i)

        if 1:
            label = wx.StaticText(self, -1, "Camera")
            label.SetFont(font)
            flexgridsizer.Add(label, 0, wx.ALIGN_CENTRE|wx.ALL, 5)
            label = wx.StaticText(self, -1, "Number of\nframebuffers")
            label.SetFont(font)
            flexgridsizer.Add(label, 0, wx.ALIGN_CENTRE|wx.ALL, 5)
            label = wx.StaticText(self, -1, "Video mode")
            label.SetFont(font)
            flexgridsizer.Add(label, 0, wx.ALIGN_CENTRE|wx.ALL, 5)

        self.num_buffers = []
        self.radios = []
        for idx in range(len(cam_info)):
            #label = wx.StaticText(self, -1, "Camera #%d:"%(idx+1,))
            #flexgridsizer.Add(label, 0, wx.ALIGN_RIGHT|wx.TOP|wx.BOTTOM, 5)

            this_cam_string = "%s %s (%s)"%(
                str(cam_info[idx]['vendor']),
                str(cam_info[idx]['model']),
                str(cam_info[idx]['chip']))
            radio = wx.RadioButton( self, -1, this_cam_string )
            self.radios.append(radio)
            flexgridsizer.Add(radio, 0, wx.ALIGN_CENTRE)

            text = wx.TextCtrl(self, -1, str(cam_info[idx]['num_buffers']),
                               style=wx.TE_CENTRE)
            wxvt.setup_validated_integer_callback(text,
                                                  text.GetId(),
                                                  None)
            self.num_buffers.append(text)

            flexgridsizer.Add(text, 0, wx.ALIGN_CENTRE)
            mode_choice_strings=cam_info[idx]['mode_choice_strings']
            mode_choice = wx.Choice(self, -1, choices=mode_choice_strings)
            choice = 0
            for i,mode_choice_string in enumerate(mode_choice_strings):
                if 'DC1394_VIDEO_MODE_FORMAT7_0' in mode_choice_string:
                    if 'YUV422' in mode_choice_string:
                        choice = i
                        break
                    elif 'YUV411' in mode_choice_string:
                        choice = i
                        break
                    elif 'MONO8' in mode_choice_string:
                        choice = i
                        break
            mode_choice.SetSelection(choice)
            flexgridsizer.Add(mode_choice, 0, wx.ALIGN_CENTRE)
            cam_info[idx]['mode_choice_control'] = mode_choice

        sizer.Add(flexgridsizer, 0, wx.GROW|wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5)

        line = wx.StaticLine(self, -1, size=(20,-1), style=wx.LI_HORIZONTAL)
        sizer.Add(line, 0, wx.GROW|wx.ALIGN_CENTER_VERTICAL|wx.RIGHT|wx.TOP, 5)

        btnsizer = wx.BoxSizer()

        btn = wx.Button(self, wx.ID_OK, "OK")
        wx.EVT_BUTTON(btn, wx.ID_OK, self.OnOK)
        btn.SetDefault()
        btnsizer.Add(btn,0,flag=wx.LEFT | wx.RIGHT,border=5)

        btn = wx.Button(self, wx.ID_CANCEL, "Cancel")
        wx.EVT_BUTTON(btn, wx.ID_CANCEL, self.OnCancel)
        btnsizer.Add(btn,0,0)

        sizer.Add(btnsizer, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5)

        self.SetSizer(sizer)
        sizer.Fit(self)
    def OnOK(self,event):
        self.SetReturnCode(wx.ID_OK)
        self.EndModal(wx.ID_OK)
    def OnCancel(self, event):
        self.SetReturnCode(wx.ID_CANCEL)
        self.EndModal(wx.ID_CANCEL)

class BackendChoiceDialog(wx.Dialog):
    def __init__(self, parent):
        # see http://wiki.wxpython.org/index.cgi/TwoStageCreation
        pre = wx.PreDialog()
        RES.LoadOnDialog(pre, parent, "BACKEND_CHOICE_DIALOG")
        self.PostCreate(pre)

        if cam_iface is not None:
            wxctrl = xrc.XRCCTRL(self,'CAM_IFACE_LOADED')
            wxctrl.SetLabel('Warning: changes will have no effect '
                            'until this application is restarted.')

        backend_choice = xrc.XRCCTRL(self,'BACKEND_CHOICE')
        for wrapper,backends in (
            cam_iface_choose.wrappers_and_backends.iteritems()):

            for backend in backends:
                if backend == 'blank' or backend=='dummy':
                    continue
                backend_choice.Append('%s (%s)'%(backend,wrapper))
        backend_choice.SetStringSelection('%s (%s)'%(rc_params['backend'],
                                                     rc_params['wrapper']))

        wxctrl = xrc.XRCCTRL(self,'SAVE_BACKEND_CHOICE')
        wx.EVT_BUTTON(wxctrl, wxctrl.GetId(),
                      self.OnOK)

        wxctrl = xrc.XRCCTRL(self,'CANCEL_BACKEND_CHOICE')
        wx.EVT_BUTTON(wxctrl, wxctrl.GetId(),
                      self.OnCancel)
        self.new_backend_and_wrapper = None

    def OnOK(self,event):
        wxctrl = xrc.XRCCTRL(self,'BACKEND_CHOICE')
        string_value = wxctrl.GetStringSelection()
        backend, wrapper = string_value.split()
        wrapper = wrapper[1:-1]
        # convert from unicode
        self.new_backend_and_wrapper = (str(backend),str(wrapper))
        self.SetReturnCode(wx.ID_OK)
        self.EndModal(wx.ID_OK)

    def OnCancel(self,event):
        self.SetReturnCode(wx.ID_CANCEL)
        self.EndModal(wx.ID_CANCEL)

def _need_cam_iface():
    global cam_iface
    if cam_iface is None:
        wrapper = rc_params['wrapper']
        backend = rc_params['backend']
        cam_iface = cam_iface_choose.import_backend(backend,wrapper)

class App(wx.App):

    def OnInit(self,*args,**kw):
        global options
        self.options = options # hack to workaround not passing args to OnInit
        self.save_images = 0 # save every nth image, 0 = false
        self.cam_ids = {}
        self.exit_code = 0
        self.grab_thread = None
        self.shutdown_error_info = None

        wx.InitAllImageHandlers()
        self.frame = wx.Frame(None, -1, "FView",size=(640,480))

        self.fview_ext_trig_plugin = None

        self.xrcid2validator = {}

        # statusbar ----------------------------------
        self.statusbar = self.frame.CreateStatusBar()
        self.statusbar.SetFieldsCount(3)
        self.statusbar.SetStatusWidths([-1,150,20])

        # menubar ------------------------------------
        menuBar = wx.MenuBar()
        #   File menu
        filemenu = wx.Menu()

        if 0:
            ID_open_cam_config = wx.NewId()
            filemenu.Append(
                ID_open_cam_config, "Open Camera Configuration...\tCtrl-O")
            wx.EVT_MENU(self, ID_open_cam_config, self.OnOpenCamConfig)

            ID_save_cam_config = wx.NewId()
            filemenu.Append(
                ID_save_cam_config, "Save Camera Configuration...\tCtrl-S")
            wx.EVT_MENU(self, ID_save_cam_config, self.OnSaveCamConfig)

            filemenu.AppendItem(wx.MenuItem(parentMenu=filemenu,
                                           kind=wx.ITEM_SEPARATOR))

        ID_set_record_dir = wx.NewId()
        filemenu.Append(ID_set_record_dir, "set record Directory...\tCtrl-D")
        wx.EVT_MENU(self, ID_set_record_dir, self.OnSetRecordDirectory)
        self.record_dir = os.environ.get('FVIEW_SAVE_PATH','')

        filemenu.AppendItem(wx.MenuItem(parentMenu=filemenu,
                                        kind=wx.ITEM_SEPARATOR))

        ID_quit = wx.NewId()
        filemenu.Append(ID_quit, "Quit\tCtrl-Q", "Quit application")
        wx.EVT_MENU(self, ID_quit, self.OnQuit)
        #wx.EVT_CLOSE(self, ID_quit, self.OnQuit)
        # JAB thinks this will allow use of the window-close ('x') button
        # instead of forcing users to file->quit

        menuBar.Append(filemenu, "&File")

        #   Camera menu
        cameramenu = wx.Menu()

        ID_init_camera = wx.NewId()
        cameramenu.Append(ID_init_camera, "initialize camera...")
        wx.EVT_MENU(self, ID_init_camera, self.OnInitCamera)

        ID_set_backend_choice = wx.NewId()
        cameramenu.Append(ID_set_backend_choice, "backend choice...")
        wx.EVT_MENU(self, ID_set_backend_choice, self.OnBackendChoice)

        menuBar.Append(cameramenu, "&Camera")

        # view menu
        viewmenu = wx.Menu()

        ID_rotate180 = wx.NewId()
        viewmenu.Append(ID_rotate180, "rotate 180 degrees",
                        "Rotate camera view 1800 degrees", wx.ITEM_CHECK)
        wx.EVT_MENU(self, ID_rotate180, self.OnToggleRotate180)

        ID_flipLR = wx.NewId() # mirror
        viewmenu.Append(ID_flipLR, "flip Left/Right",
                        "Flip image Left/Right", wx.ITEM_CHECK)
        wx.EVT_MENU(self, ID_flipLR, self.OnToggleFlipLR)

        self.update_view_num = -1
        self.view_interval = rc_params['view_interval']
        ID_set_view_interval = wx.NewId()
        viewmenu.Append(ID_set_view_interval, "Set display update interval...")
        wx.EVT_MENU(self, ID_set_view_interval, self.OnSetViewInterval)

        menuBar.Append(viewmenu, "&View")

        # windows menu
        windowsmenu = wx.Menu()

        ID_settings = wx.NewId()
        windowsmenu.Append(ID_settings, "Camera controls...\tCtrl-C")
        wx.EVT_MENU(self, ID_settings, self.OnOpenCameraControlsWindow)

        menuBar.Append(windowsmenu, "&Windows")

        # plugins menu
        self._load_plugins()

        del_plugins = []
        if len(self.plugins):
            windowsmenu.AppendItem(wx.MenuItem(parentMenu=windowsmenu,
                                               kind=wx.ITEM_SEPARATOR))
            for plugin in self.plugins:
                plugin_name = plugin.get_plugin_name()

                if hasattr(plugin,'set_all_fview_plugins'):
                    try:
                        plugin.set_all_fview_plugins(self.plugins)
                    except Exception,err:
                        formatted_error = traceback.format_exc(err)
                        traceback.print_exc(err,sys.stderr)
                        msg = 'While attempting to open the plugin "%s",\n' \
                              'FView encountered an error. The error is:\n\n' \
                              '%s\n\n' \
                              'More details:\n' \
                              '%s'%( plugin_name, err, formatted_error )
                        dlg = wx.MessageDialog(self.frame, msg,
                                               'FView plugin error',
                                               wx.OK | wx.ICON_WARNING)
                        dlg.ShowModal()
                        dlg.Destroy()
                        del_plugins.append(plugin)
                        continue

                ID_tmp = wx.NewId()
                item_tmp = wx.MenuItem(windowsmenu, ID_tmp, plugin_name+'...')
                windowsmenu.AppendItem(item_tmp)
                self.plugin_dict[plugin].fview_menu_wx_item = item_tmp
                wx.EVT_MENU(self, ID_tmp, self.plugin_dict[plugin].OnShowFrame)

        for del_plugin in del_plugins:
            del self.plugins[self.plugins.index(del_plugin)]

        helpmenu = wx.Menu()
        ID_helpmenu = wx.NewId()
        helpmenu.Append(ID_helpmenu, "About")
        wx.EVT_MENU(self, ID_helpmenu, self.OnAboutFView)
        menuBar.Append(helpmenu, "&Help")

        # finish menubar -----------------------------
        self.frame.SetMenuBar(menuBar)

        # main panel ----------------------------------
        self.main_panel = my_loadpanel(self.frame,"APP_PANEL")
        self.main_panel.SetFocus()

        frame_box = wx.BoxSizer(wx.VERTICAL)
        frame_box.Add(self.main_panel,1,wx.EXPAND)
        self.frame.SetSizer(frame_box)
        self.frame.Layout()

##        # main panel

        main_display_panel = xrc.XRCCTRL(self.main_panel,"MAIN_DISPLAY_PANEL")
        box = wx.BoxSizer(wx.VERTICAL)
        main_display_panel.SetSizer(box)

        self.cam_image_canvas = video_module.DynamicImageCanvas(
            main_display_panel,-1)
        self.cam_image_canvas.x_border_pixels = 0
        self.cam_image_canvas.y_border_pixels = 0
        box.Add(self.cam_image_canvas,1,wx.EXPAND)
        main_display_panel.SetAutoLayout(True)
        main_display_panel.Layout()

        # DONE WITH WX INIT STUFF

        self.grabbed_fnt = []

        self.thread_done = threading.Event()
        self.max_priority_enabled = threading.Event()
        self.quit_now = threading.Event()
#AR        self.app_ready = threading.Event()
        self.cam_fps_value = SharedValue()

        self.framerate = SharedValue()
        self.num_buffers = SharedValue()

        self.last_measurement_time = time.time()

        self.last_image = None
        self.last_image_fullsize = (0,0)
        self.last_offset = 0,0
        self.new_image = False
        self.fly_movie = None

        # MORE WX STUFF

        # camera control panel
        self.cam_control_frame = wx.Frame(
            self.frame, -1, "FView: Camera Control")
        self.cam_control_panel = my_loadpanel(
            self.cam_control_frame,"CAMERA_CONTROLS_PANEL")
        self.cam_control_panel.Fit()
        self.cam_control_frame.Fit()

        self.cam_settings_panel = xrc.XRCCTRL(
            self.cam_control_panel, "CAM_SETTINGS_PANEL")
        self.cam_framerate_panel = xrc.XRCCTRL(
            self.cam_control_panel, "CAM_FRAMERATE_PANEL")
        self.cam_roi_panel = xrc.XRCCTRL(
            self.cam_control_panel, "CAM_ROI_PANEL")
        self.cam_record_panel = xrc.XRCCTRL(
            self.cam_control_panel, "CAM_RECORD_PANEL")

        # Camera framerate frame ----------------------------

        wxctrl = xrc.XRCCTRL( self.cam_framerate_panel, "CAM_FRAMERATE")
        self.xrcid2validator["CAM_FRAMERATE"] = (
            wxvt.setup_validated_float_callback(
            wxctrl,
            wxctrl.GetId(),
            self.OnSetFramerate,
            ignore_initial_value=True))
        wxctrl = xrc.XRCCTRL( self.cam_framerate_panel, "CAM_NUM_BUFFERS")
        self.xrcid2validator["CAM_NUM_BUFFERS"] = (
            wxvt.setup_validated_integer_callback(
            wxctrl,
            wxctrl.GetId(),
            self.OnSetNumBuffers,
            ignore_initial_value=True))
        wxctrl = xrc.XRCCTRL( self.cam_framerate_panel, "EXTERNAL_TRIGGER_MODE")
        wx.EVT_CHOICE(wxctrl, wxctrl.GetId(), self.OnSetTriggerMode)

        wxctrl = xrc.XRCCTRL( self.cam_framerate_panel, "CAM_FRAMERATE_QUERY")
        wx.EVT_BUTTON(wxctrl, wxctrl.GetId(), self.OnGetFramerate)

        # Camera roi frame ----------------------------

        self.ignore_text_events = True
        self.roi_xrcids = [
            "ROI_LEFT","ROI_RIGHT","ROI_BOTTOM","ROI_TOP",
            "ROI_WIDTH","ROI_HEIGHT"]

        for xrcid in self.roi_xrcids:
            wxctrl = xrc.XRCCTRL( self.cam_roi_panel, xrcid)
            validator = wxvt.setup_validated_integer_callback(
                wxctrl, wxctrl.GetId(), self.OnSetROI,
                ignore_initial_value=True)
            self.xrcid2validator[xrcid] = validator

        self.ignore_text_events = False

        wxctrl = xrc.XRCCTRL( self.cam_roi_panel, "ROI_QUERY_CAMERA")
        wx.EVT_BUTTON(wxctrl, wxctrl.GetId(), self.OnUpdateROIPanel)

        wxctrl = xrc.XRCCTRL( self.cam_roi_panel, "ROI_FULL_FRAME")
        wx.EVT_BUTTON(wxctrl, wxctrl.GetId(), self.OnFullFrameROI)

        # Camera record frame ----------------------------

        self.recording_fmf = None

        wxctrl = xrc.XRCCTRL( self.cam_record_panel, "NTH_FRAME_TEXT")
        wxvt.setup_validated_integer_callback(wxctrl,
                                              wxctrl.GetId(),
                                              self.OnNthFrameChange)

        wxctrl = xrc.XRCCTRL( self.cam_record_panel, "save_fno_as_timestamp")
        self.save_fno=wxctrl.IsChecked()
        wx.EVT_CHECKBOX(wxctrl, wxctrl.GetId(), self.OnChangeSaveFNoAsTimestamp)

        wxctrl = xrc.XRCCTRL( self.cam_record_panel,
                              "update_display_while_saving")
        self.update_display_while_saving = wxctrl.IsChecked()
        wx.EVT_CHECKBOX(wxctrl, wxctrl.GetId(),
                        self.OnToggleUpdateDisplayWhileSaving)

        wxctrl = xrc.XRCCTRL( self.cam_record_panel, "START_RECORD_BUTTON")
        wx.EVT_BUTTON(wxctrl, wxctrl.GetId(),
                   self.OnStartRecord)
        wxctrl = xrc.XRCCTRL( self.cam_record_panel, "STOP_RECORD_BUTTON")
        wx.EVT_BUTTON(wxctrl, wxctrl.GetId(),
                   self.OnStopRecord)

        # Set view options
        viewmenu.Check(ID_rotate180,rc_params['rotate180'])
        self.cam_image_canvas.set_rotate_180( viewmenu.IsChecked(ID_rotate180) )
        for plugin in self.plugins:
            if not hasattr(plugin,'set_view_rotate_180'):
                print ('ERROR: plugin "%s" needs set_view_rotate_180() '
                       'method'%(plugin,))
                continue
            plugin.set_view_rotate_180( viewmenu.IsChecked(ID_rotate180) )

        viewmenu.Check(ID_flipLR,rc_params['flipLR'])
        self.cam_image_canvas.set_flip_LR( viewmenu.IsChecked(ID_flipLR) )
        for plugin in self.plugins:
            plugin.set_view_flip_LR( viewmenu.IsChecked(ID_flipLR) )

        # finalize wx stuff

        self.frame.SetAutoLayout(True)

        self.frame.Show()
        self.SetTopWindow(self.frame)

        wx.EVT_CLOSE(self.frame, self.OnWindowClose)

        self.cam_wait_msec_wait = 100

        ID_Timer2 = wx.NewId()
        self.timer2 = wx.Timer(self, ID_Timer2)
        wx.EVT_TIMER(self, ID_Timer2, self.OnFPS)
        self.update_interval2=5000
        self.timer2.Start(self.update_interval2)

        self.image_update_lock = threading.Lock()
        self.save_info_lock = threading.Lock()

        self.cam = None
        self.update_display_while_saving = True

        self.Connect(
            -1, -1, CamPropertyDataReadyEvent, self.OnCameraPropertyDataReady )
        self.Connect(
            -1, -1, CamROIDataReadyEvent, self.OnCameraROIDataReady )
        self.Connect(
            -1, -1, CamFramerateReadyEvent, self.OnFramerateDataReady )
        self.Connect(
            -1, -1, FViewShutdownEvent, self.OnQuit )
        self.Connect(
            -1, -1, ImageReadyEvent, self.OnUpdateCameraView )

        return True

    def _load_plugins(self):
        result = plugin_manager.load_plugins(
            self.frame,
            use_plugins=self.options.plugins,
            return_plugin_names=self.options.show_plugins)

        if self.options.show_plugins:
            print 'plugin description'
            print '------ -----------'
            for i,plugin in enumerate(result):
                print '    ',i,plugin
            sys.exit(0)

        plugins, plugin_dict, bad_plugins = result

        self.plugins = plugins
        self.plugin_dict = plugin_dict
        if len(bad_plugins):
            for name, (err,full_err) in bad_plugins.iteritems():
                msg = 'While attempting to open the plugin "%s",\n' \
                      'FView encountered an error. The error is:\n\n' \
                      '%s\n\n'%( name, err )
                dlg = wx.MessageDialog(self.frame, msg,
                                       'FView plugin error',
                                       wx.OK | wx.ICON_WARNING)
                dlg.ShowModal()
                dlg.Destroy()

        if self.options.show_plugins:
            print 'plugin description'
            print '------ -----------'
            for i,plugin in enumerate(self.plugins):
                print '    ',i,plugin
            sys.exit(0)

    def OnAboutFView(self, event):
        _need_cam_iface()

        driver = cam_iface.get_driver_name()
        wrapper = cam_iface.get_wrapper_name()
        disp = 'FView %s\n'%__version__
        disp += 'cam_iface driver: %s, wrapper: %s\n\n'%(driver,wrapper)
        disp += 'Loaded modules (.egg files only):\n'
        disp += '---------------------------------\n'
        for d in pkg_resources.working_set:
            disp += str(d) + '\n'
        dlg = wx.MessageDialog(self.frame, disp,
                               'About FView',
                               wx.OK | wx.ICON_INFORMATION)
        dlg.ShowModal()
        dlg.Destroy()

    def OnInitCamera(self, event):
        try:
            _need_cam_iface()

            if self.cam is not None:
                dlg = wx.MessageDialog(
                    self.frame, 'A camera may only be initialized once',
                    'FView error',
                    wx.OK | wx.ICON_ERROR
                    )
                dlg.ShowModal()
                dlg.Destroy()
                return

            driver_name = cam_iface.get_driver_name()
            num_cameras = cam_iface.get_num_cameras()

            cam_info = []
            try:
                for idx in range(num_cameras):
                    vendor, model, chip = cam_iface.get_camera_info(idx)
                    mode_choice_strings = []
                    for mode_number in range( cam_iface.get_num_modes(idx) ):
                        mode_choice_strings.append(
                            cam_iface.get_mode_string(idx,mode_number))

                    cam_name_string = "num_buffers('%s','%s')"%(vendor,model)
                    if cam_name_string in rc_params:
                        num_buffers = rc_params[cam_name_string]
                    else:
                        if vendor == 'Basler' and model == 'A602f':
                            num_buffers = 100
                        elif vendor == 'Basler' and model == 'A622f':
                            num_buffers = 50
                        elif vendor == 'Unibrain' and model == 'Fire-i BCL 1.2':
                            num_buffers = 100
                        elif vendor == 'Unibrain' and model == 'Fire-i BBW 1.3':
                            num_buffers = 100
                        elif vendor == 'Point Grey Research' and model=='Scorpion':
                            num_buffers = 32
                        else:
                            num_buffers = 32
                    if sys.platform.startswith('win'):
                        num_buffers = 10 # for some reason, this seems to be the max, at least with CMU1394
                    cam_info.append( dict(vendor=vendor,
                                          model=model,
                                          chip=chip,
                                          num_buffers=num_buffers,
                                          mode_choice_strings=mode_choice_strings,
                                          ) )
                # closes for loop
            except cam_iface.CamIFaceError, x:
                dlg = wx.MessageDialog(self.frame, str(x),
                                       'Error getting camera information',
                                       wx.OK | wx.ICON_ERROR)
                dlg.ShowModal()
                dlg.Destroy()
                return

            dlg = InitCameraDialog(self.frame, -1, "Select camera & parameters",
                                   size=wx.DefaultSize, pos=wx.DefaultPosition,
                                   style=wx.DEFAULT_DIALOG_STYLE,
                                   cam_info=cam_info)
            res = dlg.ShowModal()
            cam_no_selected = None
            if res == wx.ID_OK and len(dlg.radios):
                for idx in range(len(dlg.radios)):
                    if dlg.radios[idx].GetValue():
                        cam_no_selected = idx
                        num_buffers = int(dlg.num_buffers[idx].GetValue())
            else:
                return

            vendor, model, chip = cam_iface.get_camera_info(cam_no_selected)

            cam_name_string = "num_buffers('%s','%s')"%(vendor,model)
            rc_params[cam_name_string] = num_buffers
            save_rc_params()

            # allocate 400 MB then delete, just to get some respec' from OS:
            nx.zeros((400*1024,),nx.uint8)

            mode_choice = cam_info[cam_no_selected]['mode_choice_control']
            mode_number = mode_choice.GetSelection()

            try:
                self.cam = cam_iface.Camera(cam_no_selected,
                                            num_buffers,
                                            mode_number
                                            )
            except cam_iface.CamIFaceError, x:
                dlg = wx.MessageDialog(self.frame, str(x),
                                       'Error opening camera',
                                       wx.OK | wx.ICON_ERROR)
                dlg.ShowModal()
                dlg.Destroy()
                raise
            vendor, model, chip = cam_iface.get_camera_info(cam_no_selected)
            self.cam_ids[self.cam] = 'cam %d'%(len(self.cam_ids.keys())+1,)
            format = self.cam.get_pixel_coding()
            self.statusbar.SetStatusText('Connected to %s %s (%s)'%(
                vendor, model, format),0)

            self.property_callback_funcs = {}
            self.roi_callback_funcs = []
            self.framerate_callback_funcs = []

            # set external trigger modes
            try:
                trigger_mode = self.cam.get_trigger_mode_number()
            except cam_iface.CamIFaceError:
                print 'Error getting trigger mode number'
                trigger_mode = None

            wxctrl = xrc.XRCCTRL( self.cam_framerate_panel, "EXTERNAL_TRIGGER_MODE")
            for i in range(self.cam.get_num_trigger_modes()):
                trigger_mode_string = self.cam.get_trigger_mode_string(i)
                wxctrl.Append(trigger_mode_string)
            if trigger_mode is not None:
                wxctrl.SetSelection(trigger_mode)
            else:
                wxctrl.SetSelection(0)
            self.register_framerate_query_callback( self.OnReceiveFramerate )

            self.host_timestamp_ctrl = xrc.XRCCTRL( self.cam_framerate_panel,
                                  "use_host_timestamps")
            wx.EVT_CHECKBOX(self.host_timestamp_ctrl, self.host_timestamp_ctrl.GetId(),
                            self.OnUseHostTimestamps)

            cphs = []
            n_props = self.cam.get_num_camera_properties()

            # info from grab thread to GUI thread
            self.cam_prop_get_queue = Queue.Queue()
            self.cam_roi_get_queue = Queue.Queue()
            self.framerate_get_queue = Queue.Queue()

            # commands from GUI thread to grab thread
            self.cam_cmd_queue = Queue.Queue()

            self._mainthread_roi = None
            self.register_roi_query_callback( self.OnReceiveROI)
            self.cam_cmd_queue.put( ('ROI query',None) )
            self.cam_cmd_queue.put( ('framerate query',None) )

            auto_cam_settings_panel = xrc.XRCCTRL(
                self.cam_settings_panel, "AUTO_CAM_SETTINGS_PANEL")
            acsp_sizer = wx.FlexGridSizer(n_props) # guesstimate
            n_rows = 0
            n_cols = 4
            for prop_num in range(n_props):
                auto_cam_settings_panel.Hide()
                cph = CameraParameterHelper( self.cam,
                                             auto_cam_settings_panel,
                                             acsp_sizer,
                                             prop_num,
                                             self)
                auto_cam_settings_panel.Show()
                if cph.present:
                    n_rows += 1
                    cphs.append( cph )

            if not len(cphs):
                acsp_sizer.AddGrowableCol(0)
                statictext = wx.StaticText(
                    auto_cam_settings_panel,
                    label='(No properties present on this camera)')
                n_rows += 1
                acsp_sizer.Add(statictext,1,flag=wx.ALIGN_CENTRE|wx.EXPAND)
            else:
                acsp_sizer.AddGrowableCol(1)

            acsp_sizer.SetRows(n_rows)
            acsp_sizer.SetCols(n_cols)
            auto_cam_settings_panel.SetSizer(acsp_sizer)
            auto_cam_settings_panel.Layout()

            for cph in cphs:
                non_self_cphs = [cph2 for cph2 in cphs if cph2 is not cph]
                for cph2 in non_self_cphs:
                    cph.AddToUpdate( cph2 )

            self.cam_param_helpers = cphs
            wxctrl = xrc.XRCCTRL( self.cam_settings_panel, "QUERY_CAMERA_SETTINGS")
            wx.EVT_BUTTON(wxctrl, wxctrl.GetId(),
                          self.OnQueryCameraSettings)

            # query camera settings to initially fill window
            #self.OnQueryCameraSettings(None)

            # re-fit the camera control window
            self.cam_control_panel.Fit()
            self.cam_control_frame.Fit()


            # send plugins information that camera is starting
            format = self.cam.get_pixel_coding()
            bad_plugins = []
            for plugin in self.plugins:
                try:
                    plugin.camera_starting_notification(
                        self.cam_ids[self.cam],
                        pixel_format=format,
                        max_width=self.cam.get_max_width(),
                        max_height=self.cam.get_max_height())

                except Exception, err:
                    traceback.print_exc(err,sys.stderr)
                    if self.log_filename is None:
                        log_filename_str = ''
                    else:
                        log_filename_str = ' See\n\n%s'%(self.log_filename,)
                    msg = 'An FView plugin "%s" failed: %s\n\n'\
                          'The plugin will now be disabled, and '\
                          'the log will have more details.%s'%(
                        plugin.plugin_name,
                        str(err),log_filename_str)
                    dlg = wx.MessageDialog(self.frame,msg,
                                           'FView plugin error',
                                           wx.OK | wx.ICON_WARNING)
                    dlg.ShowModal()
                    dlg.Destroy()
                    bad_plugins.append( plugin )

            for bad_plugin in bad_plugins:
                self.plugin_dict[bad_plugin].fview_menu_wx_item.Enable(False)
                self.plugin_dict[bad_plugin].Destroy()
                del self.plugins[ self.plugins.index(bad_plugin) ]

            for plugin in self.plugins:
                if plugin.get_plugin_name() == 'FView external trigger':
                    self.fview_ext_trig_plugin = plugin
                    if self.fview_ext_trig_plugin.trigger_device.real_device:
                        self.cam_cmd_queue.put(('timestamp source','CamTrig'))
                        self.host_timestamp_ctrl.Enable(False)

            self.pixel_coding = format

            self.cam_max_width = self.cam.get_max_width()
            self.cam_max_height = self.cam.get_max_height()

            # start threads
            grab_thread = threading.Thread( target=grab_func,
                                            args=(self,
                                                  self.image_update_lock,
                                                  self.cam,
                                                  self.cam_ids[self.cam],
                                                  self.max_priority_enabled,
                                                  self.quit_now,
                                                  self.thread_done,
                                                  self.cam_fps_value,
                                                  self.framerate,
                                                  self.num_buffers,
                                                  self.plugins,
                                                  self.cam_prop_get_queue,
                                                  self.cam_roi_get_queue,
                                                  self.framerate_get_queue,
                                                  self.cam_cmd_queue,
                                                  self.fview_ext_trig_plugin,
                                                  ))
            grab_thread.setDaemon(True)
            grab_thread.start()
            self.grab_thread = grab_thread

            save_thread = threading.Thread( target=save_func,
                                            args=(self,
                                                  self.save_info_lock,
                                                  self.quit_now,
                                                  ))
            save_thread.setDaemon(True)
            save_thread.start()
        except Exception,err:
            if self.log_filename is None:
                log_filename_str = ''
            else:
                log_filename_str = '%s\n\n'%(self.log_filename,)
            dlg = wx.MessageDialog(
                self.frame, ('An unknown error accessing the camera was '
                             'encountered. The log file will have details. '
                             '\n\n%sFView will now exit. The error '
                             'was:\n%s'%(log_filename_str,str(err),)),
                'FView error',
                wx.OK | wx.ICON_ERROR
                )
            dlg.ShowModal()
            dlg.Destroy()
            traceback.print_exc(err,sys.stderr)
            self.exit_code = 1
            self.OnQuit()

    def register_property_query_callback( self, prop_num, callback_func):
        self.property_callback_funcs.setdefault(prop_num,[]).append(
            callback_func)

    def OnCameraPropertyDataReady(self, event):
        try:
            while 1:
                data = self.cam_prop_get_queue.get_nowait()
                (prop_num, current_value, is_set) = data
                for cb_func in self.property_callback_funcs.get(prop_num,[]):
                    cb_func( current_value, is_set )
        except Queue.Empty:
            pass

    def register_roi_query_callback(self, callback_func):
        self.roi_callback_funcs.append(callback_func)

    def register_framerate_query_callback(self, callback_func):
        self.framerate_callback_funcs.append(callback_func)

    def OnCameraROIDataReady(self, event):
        try:
            while 1:
                data = self.cam_roi_get_queue.get_nowait()
                (l,b,r,t) = data
                for cb_func in self.roi_callback_funcs:
                    cb_func( l,b,r,t )
        except Queue.Empty:
            pass

    def OnFramerateDataReady(self, event):
        try:
            while 1:
                data = self.framerate_get_queue.get_nowait()
                current_framerate, trigger_mode, num_buffers = data
                for cb_func in self.framerate_callback_funcs:
                    cb_func( current_framerate, trigger_mode, num_buffers )
        except Queue.Empty:
            pass

    def enqueue_property_change( self, cmd):
        self.cam_cmd_queue.put( ('property change',cmd) )

    def OnSetViewInterval(self,event):
        dlg=wx.TextEntryDialog(self.frame, 'Display every Nth frame, where N is:',
                               'Set view interval',str(self.view_interval))
        try:
            if dlg.ShowModal() == wx.ID_OK:
                interval = int(dlg.GetValue())
                rc_params['view_interval'] = interval
                save_rc_params()
                self.view_interval = interval
        finally:
            dlg.Destroy()

    def OnSetRecordDirectory(self, event):

        dlg = wx.DirDialog( self.frame, "Movie record directory",
                            style = wx.DD_DEFAULT_STYLE | wx.DD_NEW_DIR_BUTTON,
                            defaultPath = self.record_dir,
                            )
        try:
            if dlg.ShowModal() == wx.ID_OK:
                self.record_dir = dlg.GetPath()
        finally:
            dlg.Destroy()

    def OnBackendChoice(self, event):
        dlg = BackendChoiceDialog(self.frame)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                if dlg.new_backend_and_wrapper is not None:
                    backend,wrapper = dlg.new_backend_and_wrapper
                    rc_params['wrapper'] = wrapper
                    rc_params['backend'] = backend
                    save_rc_params()
        finally:
            dlg.Destroy()

    def OnQueryCameraSettings(self, event):
        self.cam_cmd_queue.put( ('property query',None) )

    def OnToggleRotate180(self, event):
        self.cam_image_canvas.set_rotate_180( event.IsChecked() )
        rc_params['rotate180'] = event.IsChecked()
        save_rc_params()
        for plugin in self.plugins:
            if not hasattr(plugin,'set_view_rotate_180'):
                print ('ERROR: plugin "%s" needs set_view_rotate_180() '
                       'method'%(plugin,))
                continue
            plugin.set_view_rotate_180( event.IsChecked() )

    def OnToggleFlipLR(self, event):
        self.cam_image_canvas.set_flip_LR( event.IsChecked() )
        rc_params['flipLR'] = event.IsChecked()
        save_rc_params()
        for plugin in self.plugins:
            plugin.set_view_flip_LR( event.IsChecked() )

    def OnSetFramerate(self, event):
        if self.ignore_text_events:
            return
        widget = event.GetEventObject()
        fr_string = widget.GetValue()
        try:
            fr = float(fr_string)
        except ValueError:
            return
        self.framerate.set(fr)

    def OnReceiveFramerate(self,framerate,trigger_mode,num_buffers):
        self.ignore_text_events = True
        wxctrl = xrc.XRCCTRL( self.cam_framerate_panel, "CAM_FRAMERATE")
        wxctrl.SetValue(str(framerate))
        self.xrcid2validator["CAM_FRAMERATE"].set_state('valid')

        wxctrl = xrc.XRCCTRL( self.cam_framerate_panel, "CAM_NUM_BUFFERS")
        wxctrl.SetValue(str(num_buffers))
        self.xrcid2validator["CAM_NUM_BUFFERS"].set_state('valid')
        self.ignore_text_events = False

        wxctrl = xrc.XRCCTRL( self.cam_framerate_panel, "EXTERNAL_TRIGGER_MODE")
        if trigger_mode is not None:
            wxctrl.SetSelection(trigger_mode)
        else:
            wxctrl.SetSelection(0)

    def OnGetFramerate(self, event):
        self.cam_cmd_queue.put( ('framerate query',None) )

##        #framerate=self.cam.get_framerate()#XXX bad to cross thread boundary!
###        num_buffers = self.cam.get_num_framebuffers()
####        try:
####            trigger_mode = self.cam.get_trigger_mode_number()
####        except cam_iface.CamIFaceError:
####            trigger_mode = None
##        trigger_mode = None

##        self.ignore_text_events = True
####        wxctrl = xrc.XRCCTRL( self.cam_framerate_panel, "CAM_NUM_BUFFERS")
####        wxctrl.SetValue(str(num_buffers))
####        self.xrcid2validator["CAM_NUM_BUFFERS"].set_state('valid')
##        self.ignore_text_events = False

##        wxctrl=xrc.XRCCTRL(self.cam_framerate_panel, "EXTERNAL_TRIGGER_MODE")
##        if trigger_mode is not None:
##            wxctrl.SetSelection(trigger_mode)
##        else:
##            wxctrl.SetSelection(0)

    def OnSetNumBuffers(self, event):
        if self.ignore_text_events:
            return
        widget = event.GetEventObject()
        fr_string = widget.GetValue()
        try:
            fr = int(fr_string)
        except ValueError:
            return
        self.num_buffers.set(fr)

    def OnSetTriggerMode(self,event):
        widget = event.GetEventObject()
        val = widget.GetSelection()

        self.cam_cmd_queue.put(('TriggerMode Set',val))

    def OnUseHostTimestamps(self,event):
        widget = event.GetEventObject()
        val = widget.IsChecked()
        if val:
            self.cam_cmd_queue.put(('timestamp source','host clock'))
        else:
            self.cam_cmd_queue.put(('timestamp source','camera driver'))

    def OnSetROI(self, event):
        if self.ignore_text_events:
            return
        widget = event.GetEventObject()
        widget_left = xrc.XRCCTRL( self.cam_roi_panel, "ROI_LEFT" )
        widget_bottom = xrc.XRCCTRL( self.cam_roi_panel, "ROI_BOTTOM" )
        widget_right = xrc.XRCCTRL( self.cam_roi_panel, "ROI_RIGHT" )
        widget_top = xrc.XRCCTRL( self.cam_roi_panel, "ROI_TOP" )
        widget_width = xrc.XRCCTRL( self.cam_roi_panel, "ROI_WIDTH" )
        widget_height = xrc.XRCCTRL( self.cam_roi_panel, "ROI_HEIGHT" )
        if widget in (widget_right,widget_top):
            is_right_top = True
        else:
            is_right_top = False
        ####
        l = int(widget_left.GetValue())
        b = int(widget_bottom.GetValue())
        if is_right_top:
            r = int(widget_right.GetValue())
            t = int(widget_top.GetValue())
            if r<l: return
            if t<b: return
            w = r-l
            h = t-b
        else:
            w = int(widget_width.GetValue())
            h = int(widget_height.GetValue())
            r = l+w
            t = b+h
        ####
        if (l>=0 and r<=self.cam_max_width and b>=0 and t<=self.cam_max_height):
            lbrt = l,b,r,t
            self.cam_cmd_queue.put(('ROI set',lbrt))
            self.ignore_text_events = True # prevent infinte recursion
            widget_left.SetValue(str(l))
            self.xrcid2validator["ROI_LEFT"].set_state('valid')

            widget_bottom.SetValue(str(b))
            self.xrcid2validator["ROI_BOTTOM"].set_state('valid')

            widget_right.SetValue(str(r))
            self.xrcid2validator["ROI_RIGHT"].set_state('valid')

            widget_top.SetValue(str(t))
            self.xrcid2validator["ROI_TOP"].set_state('valid')

            widget_width.SetValue(str(w))
            self.xrcid2validator["ROI_WIDTH"].set_state('valid')

            widget_height.SetValue(str(h))
            self.xrcid2validator["ROI_HEIGHT"].set_state('valid')

            self.ignore_text_events = False

        else:
            print 'ignoring invalid ROI command',l,b,r,t
            self.OnUpdateROIPanel() # reset wx indicators

    def OnFullFrameROI(self,event):
        lbrt = 0,0,self.cam_max_width,self.cam_max_height
        self.cam_cmd_queue.put(('ROI set',lbrt))

    def OnReceiveROI(self,l,b,r,t):
        self._mainthread_roi = (l,b,r,t)
        self.OnQueryROI()
        self.OnUpdateROIPanel()

    def _get_lbrt(self):
        return self._mainthread_roi

    def OnQueryROI(self, event=None):
        lbrt=self._get_lbrt()
        self.cam_image_canvas.set_lbrt('camera',lbrt)

        # it's a hack to put this here, but doesn't really harm anything
        if self.max_priority_enabled.isSet():
            self.statusbar.SetStatusText('+',2)
        else:
            self.statusbar.SetStatusText('-',2)

    def OnUpdateROIPanel(self, event=None):
        result=self._get_lbrt()
        if result is None:
            return
        l,b,r,t = result
        self.ignore_text_events = True
        xrc.XRCCTRL( self.cam_roi_panel, "ROI_LEFT" ).SetValue(str(l))
        self.xrcid2validator["ROI_LEFT"].set_state('valid')

        xrc.XRCCTRL( self.cam_roi_panel, "ROI_BOTTOM" ).SetValue(str(b))
        self.xrcid2validator["ROI_BOTTOM"].set_state('valid')

        xrc.XRCCTRL( self.cam_roi_panel, "ROI_RIGHT" ).SetValue(str(r))
        self.xrcid2validator["ROI_RIGHT"].set_state('valid')

        xrc.XRCCTRL( self.cam_roi_panel, "ROI_TOP" ).SetValue(str(t))
        self.xrcid2validator["ROI_TOP"].set_state('valid')

        xrc.XRCCTRL( self.cam_roi_panel, "ROI_WIDTH" ).SetValue(str(r-l))
        self.xrcid2validator["ROI_WIDTH"].set_state('valid')

        xrc.XRCCTRL( self.cam_roi_panel, "ROI_HEIGHT" ).SetValue(str(t-b))
        self.xrcid2validator["ROI_HEIGHT"].set_state('valid')

        self.ignore_text_events = False

    def OnChangeSaveFNoAsTimestamp(self, event):
        self.save_fno=event.IsChecked()

    def OnToggleUpdateDisplayWhileSaving(self,event):
        self.update_display_while_saving = event.IsChecked()

    def OnNthFrameChange(self,event):
        pass # do nothing

    def OnStartRecord(self, event):
        if not self.save_images:

            nth_frame_ctrl = xrc.XRCCTRL(
                self.cam_record_panel, "NTH_FRAME_TEXT")

            try:
                nth_frame = int(nth_frame_ctrl.GetValue())
                if nth_frame < 1:
                    raise ValueError('only values >=1 allowed')
            except ValueError,err:
                dlg = wx.MessageDialog(
                    self.frame, 'Nth frame setting warning:\n   %s'%(str(err),),
                    'FView warning',
                    wx.OK | wx.ICON_INFORMATION
                    )
                dlg.Show()
                nth_frame = 1

            filename = time.strftime( 'movie%Y%m%d_%H%M%S.fmf' )
            fullpath = os.path.join( self.record_dir, filename )
            self.start_streaming(fullpath,nth_frame)
            if nth_frame == 1:
                self.statusbar.SetStatusText('saving to %s'%(filename,),0)
            else:
                self.statusbar.SetStatusText(
                    'saving to %s (every 1 of %d frames)'%(filename,nth_frame)
                    ,0)

    def OnStopRecord(self, event):
        if self.save_images:
            self.stop_streaming()
            self.statusbar.SetStatusText('',0)

    def OnFPS(self, evt):
        if self.grab_thread is not None:
            if not self.grab_thread.isAlive():
                self.grab_thread = None # only show this once
                dlg = wx.MessageDialog(
                    self.frame,
                    'the camera thread appears to have died unexpectedly. '
                    'The log file will have more details.',
                    'FView Error',
                    wx.OK | wx.ICON_ERROR)
                try:
                    dlg.ShowModal()
                finally:
                    dlg.Destroy()


        fps_value = self.cam_fps_value
        if fps_value.is_new_value_waiting():
            fps,good_fps = fps_value.get_nowait()
            if fps==good_fps:
                self.statusbar.SetStatusText('~%.1f fps'%(fps,),1)
            else:
                self.statusbar.SetStatusText('~%.1f/%.1f fps'%(good_fps,fps),1)

    def OnOpenCameraControlsWindow(self, evt):
        self.cam_control_frame.Show(True)
        self.cam_control_frame.Raise()
        wx.EVT_CLOSE(self.cam_control_frame, self.OnCloseCameraControlsWindow)

    def OnCloseCameraControlsWindow(self, evt):
        self.cam_control_frame.Show(False)

    def OnUpdateCameraView(self, evt):
#AR        self.app_ready.set() # tell grab thread to start
        try:

            self.update_view_num += 1
            if (self.update_view_num % self.view_interval) != 0:
                return

            if USE_DEBUG:
                sys.stdout.write('R')
                sys.stdout.flush()

            if self.save_images:
                if not self.update_display_while_saving:
                    return

            # copy stuff ASAP
            self.image_update_lock.acquire()
            if self.new_image:
                new_image = True
                last_image = self.last_image
                last_fullsize = self.last_image_fullsize
                last_offset = self.last_offset
                self.new_image = False
                points = self.plugin_points
                linesegs = self.plugin_linesegs
            else:
                new_image = False
            # release lock ASAP
            self.image_update_lock.release()

            # now draw
            if new_image:
                last_image = nx.asarray(last_image) # convert to numpy view

                fullw,fullh = last_fullsize
                if last_image.shape != (fullh,fullw):
                    xoffset=last_offset[0]
                    yoffset=last_offset[1]
                    h,w=last_image.shape
                    linesegs.extend(
                        [(xoffset,    yoffset,
                          xoffset,    yoffset+h),
                         (xoffset,    yoffset+h,
                          xoffset+w,  yoffset+h),
                         (xoffset+w,  yoffset+h,
                          xoffset+w,  yoffset),
                         (xoffset+w,  yoffset,
                          xoffset,    yoffset),
                         ] )

                self.cam_image_canvas.update_image_and_drawings(
                    'camera',
                    last_image,
                    format=self.pixel_coding,
                    points=points,
                    linesegs=linesegs,
                    xoffset=last_offset[0],
                    yoffset=last_offset[1],
                    )
                self.cam_image_canvas.Refresh(eraseBackground=False)
        except Exception,err:
            if self.log_filename is None:
                log_filename_str = ''
            else:
                log_filename_str = '%s\n\n'%(self.log_filename,)
            self.shutdown_error_info=(
                ('An unknown error updating the screen was '
                 'encountered. The log file will have details. '
                 '\n\n%sFView will now exit. The error '
                 'was:\n%s'%(log_filename_str,str(err),)),
                'FView error',)
            self.exit_code = 1
            event = wx.CommandEvent(FViewShutdownEvent)
            event.SetEventObject(self)
            wx.PostEvent(self, event)
            raise

    def OnWindowClose(self, event):
        self.timer2.Stop()
        self.quit_now.set()
        for plugin in self.plugins:
            plugin.quit()
        self.thread_done.wait(0.1) # block until grab thread is done...
        event.Skip() # propagate event up the chain...

    def OnQuit(self, dummy_event=None):
        self.quit_now.set()

        # normal or error exit
        if self.shutdown_error_info is not None:
            msg,title = self.shutdown_error_info
            dlg = wx.MessageDialog(self.frame,msg,title,
                                   wx.OK | wx.ICON_ERROR
                                   )
            dlg.ShowModal()
            dlg.Destroy()
        self.frame.Close() # results in call to OnWindowClose()
        if self.exit_code != 0:
            sys.exit(self.exit_code)

    def start_streaming(self,filename,nth_frame):
        # XXX bad to cross thread boundary!
        format = self.cam.get_pixel_coding()
        depth = self.cam.get_pixel_depth()
        assert (self.cam.get_pixel_depth() % 8 == 0)
        self.save_info_lock.acquire()
        self.fly_movie = FlyMovieFormat.FlyMovieSaver(filename,
                                                      version=3,
                                                      format=format,
                                                      bits_per_pixel=depth,
                                                      )
        self.save_images = nth_frame
        self.save_info_lock.release()

    def stop_streaming(self):
        self.save_info_lock.acquire()
        self.save_images = False
        self.fly_movie.close()
        self.fly_movie = None
        self.save_info_lock.release()

def main():
    global cam_iface
    if int(os.environ.get('FVIEW_NO_REDIRECT','0')):
        log_filename = None
        kw = {}
    else:
        log_filename = os.path.abspath( 'fview.log' )
	kw = dict(redirect=True,filename=log_filename)

    usage = '%prog [options]'

    parser = OptionParser(usage)
    parser.add_option("--plugins", type='string',
                      help="choose multiple plugins (e.g. '2,3')",
                      default=None)
    parser.add_option("--show-plugins", action='store_true',
                      help="show plugin numbers and names (then quit)",
                      default=False)
    global options
    (options, args) = parser.parse_args()

    if options.plugins is not None:
        options.plugins = [int(p) for p in options.plugins.split(',') if p != '']

    app = App(**kw)
    app.log_filename = log_filename

    if 0:
        # run under profiler
        import hotshot
        prof = hotshot.Profile("fview.hotshot")
        res = prof.runcall(app.MainLoop)
        prof.close()
    else:
        # run normally
        app.MainLoop()
    if hasattr(cam_iface,'shutdown'):
        cam_iface.shutdown()

if __name__=='__main__':
    main()
