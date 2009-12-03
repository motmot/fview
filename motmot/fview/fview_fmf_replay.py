import pkg_resources
import motmot.FlyMovieFormat.FlyMovieFormat as FlyMovieFormat
import numpy
import wx
import time, Queue, threading, os
if int(os.environ.get('FVIEW_NO_OPENGL','0')):
    import motmot.wxvideo.wxvideo as simple_overlay
else:
    import motmot.wxglvideo.simple_overlay as simple_overlay
import sys
import motmot.fview.plugin_manager as plugin_manager # fview's own plugin_manager
from optparse import OptionParser
import enthought.traits.api as traits
from enthought.traits.ui.api import View, Item, Group, Handler, HGroup, \
     VGroup, RangeEditor, InstanceEditor, ButtonEditor

global last_frame_info
last_frame_info = None

class ReplayApp(wx.App,traits.HasTraits):
    load_fmf_file = traits.Event
    play_frames = traits.Event
    play_and_save_frames = traits.Event
    next_play_is_saved = traits.Bool(False)
    play_single_frame = traits.Bool(False)
    play_single_frame_number = traits.Int
    save_output = traits.Bool(False)
    save_output_fmf = traits.Any
    play_thread = traits.Any
    show_every_frame = traits.Bool(False)
    flip_LR = traits.Bool(False)
    rotate_180 = traits.Bool(False)

    traits_view = View( Group( Item('load_fmf_file',
                                    editor=ButtonEditor(),show_label=False),
                               Group(Item('play_single_frame'),
                                     Item('play_single_frame_number'),
                                     orientation='horizontal'),
                               Item('play_frames',
                                    editor=ButtonEditor(),show_label=False),
                               Item('play_and_save_frames',
                                    editor=ButtonEditor(),show_label=False),
                                Group(Item('flip_LR'),Item('rotate_180'),orientation='horizontal'),
                               ))

    def OnInit(self,*args,**kw):
        usage = '%prog [options] fmf_filename'

        parser = OptionParser(usage)

        parser.add_option("--plugin", type='int',
                          help="choose plugins (use --show-plugins first)",
                          default=None)

        parser.add_option("--plugins", type='string',
                          help="choose multiple plugins (e.g. '2,3')",
                          default=None)

        parser.add_option("--play-n-times-and-quit", type='int',
                          help="replay movie N times, then quit")

        parser.add_option("--plugin-arg", type='string',
                          help="send string to plugin as arg")

        parser.add_option("--show-plugins", action='store_true',
                          help="show plugin numbers and names (then quit)",
                          default=False)

        parser.add_option("--quick", action='store_true',
                          help="disable showing points and line segments, and "
                          "turn off image updates",
                          default=False)

        parser.add_option("--pump", action='store_true',
                          help="pump frames occassionally to ensure plugin's "
                          "process_frame() method gets called",
                          default=False)

        (self.options, args) = parser.parse_args()

        if self.options.plugins is not None:
            assert self.options.plugin is None, "cannot give both --plugin and --plugins arguments"
            self.options.plugins = [
                int(p) for p in self.options.plugins.split(',') if p != '']
        else:
            if self.options.plugin is not None:
                self.options.plugins = [self.options.plugin]
            else:
                self.options.plugins = [0] # default to first plugin
        del self.options.plugin

        self.frame = wx.Frame(None,size=(800,600),title="fview_fmf_replay")
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

        self.plugins, plugin_dict, bad_plugins = result

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

        wx.InitAllImageHandlers()

        self.frame.Show()
        sizer = wx.BoxSizer(wx.VERTICAL)
        control = self.edit_traits( parent=self.frame,
                                    kind='subpanel',
                                    ).control
        sizer.Add(control, 0, wx.EXPAND)
        self.frame.SetSizer(sizer)
        self.frame.SetAutoLayout(True)

        self.loaded_fmf = None

        ####

        main_display_panel = wx.Panel(self.frame)
        sizer.Add(main_display_panel, 1, wx.EXPAND)

        box = wx.BoxSizer(wx.VERTICAL)
        main_display_panel.SetSizer(box)

        self.cam_image_canvas = simple_overlay.DynamicImageCanvas(main_display_panel,-1)
        self.cam_image_canvas.x_border_pixels = 0
        self.cam_image_canvas.y_border_pixels = 0

        box.Add(self.cam_image_canvas,1,wx.EXPAND)
        main_display_panel.SetAutoLayout(True)
        main_display_panel.Layout()

        self.inq = Queue.Queue()
        self.playing = threading.Event()

        # initialize Tracker
        for plugin in self.plugins:
            if hasattr(plugin,'set_all_fview_plugins'):
                plugin.set_all_fview_plugins(self.plugins)

        self.trackers = []

        for tracker in self.plugins:
            self.trackers.append( tracker )
            tracker.get_frame().Show()

        for tracker in self.trackers:
            wx.EVT_CLOSE(tracker.get_frame(),self.OnTrackerWindowClose)

        ID_Timer = wx.NewId()
        self.timer = wx.Timer(self, ID_Timer)
        wx.EVT_TIMER(self, ID_Timer, self.OnTimer)
        self.timer.Start(100)

        self.statusbar = self.frame.CreateStatusBar()
        self.statusbar.SetFieldsCount(2)
        self.statusbar.SetStatusText('no .fmf file loaded',0)

        if len(args) > 0:
            fmf_filename = args[0]
            self.load_fmf(fmf_filename)

        if self.options.play_n_times_and_quit is not None:
            if self.options.play_n_times_and_quit < 2:
                raise ValueError('must replay at least twice')
            for i in range(self.options.play_n_times_and_quit):
                if i==0:
                    time_start=time.time()
                play_func(self.loaded_fmf,
                          self.inq,
                          self.playing,
                          self.buf_allocator,
                          None)
                for j in range(self.inq.qsize()):
                    tup = self.inq.get_nowait()

            time_stop = time.time()
            self.frame.Close()
            dur = time_stop-time_start
            N = self.options.play_n_times_and_quit-1
            Nframes = N*self.loaded_fmf['n_frames']
            fps = Nframes/dur
            print('After warmup, %.1f fps (%.1f msec/frame)'%(fps,1000.0/fps))

        return True

    def OnTimer(self,event):
        global last_frame_info

        tup = None

        while True:
            had_input_image = False
            try:
                tup = self.inq.get_nowait()
                had_input_image = True
                while not self.show_every_frame:
                    tup = self.inq.get_nowait()
                if self.save_output_fmf is not None:
                    self.statusbar.SetStatusText(
                        'saving %s'%self.save_output_fmf.filename,1)
                else:
                    self.statusbar.SetStatusText('playing',1)
            except Queue.Empty:
                pass

            if (tup is None and
                self.options.pump and
                last_frame_info is not None):
                for tracker in self.trackers:
                    points,linesegs = tracker.process_frame(*last_frame_info)
                im = last_frame_info[1]
                timestamp = last_frame_info[3]
                tup = im, points, linesegs, timestamp

            if not self.options.quick:
                if tup is not None:
                    im, points, linesegs, timestamp = tup
                    # display on screen
                    self.cam_image_canvas.update_image_and_drawings('camera',
                                                                    im,
                                                                    format=self.loaded_fmf['format'],
                                                                    points=points,
                                                                    linesegs=linesegs,
                                                                    )
                    self.cam_image_canvas.Refresh(eraseBackground=False)
                    if self.save_output:
                        out_frame = self.cam_image_canvas.get_canvas_copy()
                        self.save_output_fmf.add_frame( out_frame, timestamp )

            if not self.playing.isSet():
                # stop vestiges of saving after done playing
                self.save_output = False
                self.show_every_frame = False
                if self.save_output_fmf is not None:
                    self.save_output_fmf.close()
                    self.save_output_fmf = None

            if not had_input_image:
                # no more frames were in inq
                break

    def _load_fmf_file_fired(self,event):
        doit=False
        dlg = wx.FileDialog( self.frame, "Select .fmf file",
                            style = wx.OPEN,
                            wildcard = '*.fmf',
                            )
        try:
            if dlg.ShowModal() == wx.ID_OK:
                fmf_filename = dlg.GetPath()
                doit = True
        finally:
            dlg.Destroy()
        if not doit:
            return
        self.load_fmf(fmf_filename)

    def load_fmf(self,fmf_filename):
        global last_frame_info
        fmf = FlyMovieFormat.FlyMovie(fmf_filename)#, check_integrity=True)
        n_frames = fmf.get_n_frames()
        cam_id='fake_camera'
        format=fmf.get_format()
        bg_image,timestamp0 = fmf.get_frame(0)

        self.buf_allocator = None
        for tracker in self.trackers:
            if hasattr(tracker,'get_buffer_allocator'):
                self.buf_allocator = tracker.get_buffer_allocator(cam_id)
                break

        for tracker in self.trackers:
            tracker.camera_starting_notification(cam_id,
                                                 pixel_format=format,
                                                 max_width=bg_image.shape[1],
                                                 max_height=bg_image.shape[0])

            if hasattr(tracker,'offline_startup_func'):
                tracker.offline_startup_func(self.options.plugin_arg)

        # save data for processing
        self.loaded_fmf = dict( fmf=fmf,
                                n_frames=n_frames,
                                bg_image=bg_image,
                                cam_id=cam_id,
                                format=format,
                                trackers=self.trackers,
                                )
        # new queue for each camera prevents potential confusion
        self.inq = Queue.Queue()

        # display on screen
        self.cam_image_canvas.update_image_and_drawings('camera',
                                                        bg_image,
                                                        format=format,
                                                        #points=points,
                                                        #linesegs=linesegs,
                                                        #xoffset=last_offset[0],
                                                        #yoffset=last_offset[1],
                                                        )
        self.cam_image_canvas.Refresh(eraseBackground=False)

        self.statusbar.SetStatusText('%s loaded'%(os.path.split(fmf_filename)[1],),0)

        if self.options.pump:
            last_frame_info = (cam_id,
                               bg_image,
                               (0,0),
                               timestamp0,
                               0)

    def _flip_LR_changed(self):
        self.cam_image_canvas.set_flip_LR(self.flip_LR)
        self.cam_image_canvas.update_image_and_drawings('camera',
                                                        self.loaded_fmf['bg_image'],
                                                        format=self.loaded_fmf['format'])
        self.cam_image_canvas.Refresh(eraseBackground=False)

    def _rotate_180_changed(self):
        self.cam_image_canvas.set_rotate_180(self.rotate_180)
        self.cam_image_canvas.update_image_and_drawings('camera',
                                                        self.loaded_fmf['bg_image'],
                                                        format=self.loaded_fmf['format'])
        self.cam_image_canvas.Refresh(eraseBackground=False)

    def OnTrackerWindowClose(self,event):
        if self.save_output_fmf is not None:
            self.save_output_fmf.close()
            self.save_output_fmf = None
        pass # don't close window (pointless in trax_replay)

    def _play_frames_fired(self,event):
        if self.loaded_fmf is None:
            print 'no .fmf file loaded'
            return
        if self.play_thread is not None:
            if self.play_thread.isAlive():
                raise RuntimeError('will not play frames when still playing frames')
        if self.next_play_is_saved:
            orig_fname = self.loaded_fmf['fmf'].filename
            save_base,save_ext = os.path.splitext(orig_fname)
            if save_ext=='.fmf':
                save_fname = save_base + '.replay.fmf'
            else:
                save_fname = orig_fname + '.replay.fmf'
            self.save_output_fmf = FlyMovieFormat.FlyMovieSaver(save_fname,
                                                                version=3,
                                                                format='RGB8')
            self.save_output = True
            self.show_every_frame = True # need to show every frame when saving
            self.next_play_is_saved = False

        if self.play_single_frame:
            single_frame_number = self.play_single_frame_number
        else:
            single_frame_number = None

        self.play_thread = threading.Thread( target=play_func, args=(self.loaded_fmf,
                                                                     self.inq,
                                                                     self.playing,
                                                                     self.buf_allocator,
                                                                     single_frame_number) )
        self.play_thread.setDaemon(True)#don't let this thread keep app alive
        self.play_thread.start()

    def _play_and_save_frames_fired(self,event):
        self.next_play_is_saved = True
        self.play_frames = True # fire event

def play_func(loaded_fmf, im_pts_segs_q, playing, buf_allocator, single_frame_number ):
    global last_frame_info
    playing.set()
    try:
        n_frames = loaded_fmf['n_frames']
        fmf = loaded_fmf['fmf']
        bg_image = loaded_fmf['bg_image']
        trackers = loaded_fmf['trackers']
        cam_id = loaded_fmf['cam_id']
        format = loaded_fmf['format']

        fmf.seek(0)
        if single_frame_number is None:
            all_fnos = range(n_frames)
        else:
            all_fnos = [single_frame_number]

        for fno in all_fnos:
            if im_pts_segs_q.qsize() >= 5:
                # don't fill buffer too much
                time.sleep(0.010)

            # reconstruct original frame #################
            fullsize_image,timestamp = fmf.get_frame(fno)
            loaded_fmf['bg_image'] = fullsize_image

            # process with trackers #################
            buf_offset=0,0
            framenumber=fno
            if buf_allocator is None:
                buf = fullsize_image
            else:
                # use plugin's buffer allocator
                w = fmf.get_width() # width of stride in bytes (not necessarily pixel width)
                h = fmf.get_height()
                buf = buf_allocator(w,h)
                npy_buf = numpy.asarray(buf)
                iw = fullsize_image.shape[1]
                for y in range(h):
                    npy_buf[y,:iw] = fullsize_image[y,:]

            last_frame_info = (cam_id,
                               buf,
                               buf_offset,
                               timestamp,
                               framenumber)

            points = []
            linesegs = []
            for tracker in trackers:
                pointsi,linesegsi = tracker.process_frame(*last_frame_info)
                points.extend(pointsi)
                linesegs.extend(linesegsi)
            tup = fullsize_image, points, linesegs, timestamp
            im_pts_segs_q.put( tup )
            time.sleep(1e-5)
    finally:
        playing.clear()

def main():

    app = ReplayApp(0)
    app.MainLoop()

    if app.loaded_fmf is not None:
        for tracker in app.trackers:
            tracker.quit()

if __name__=='__main__':
    main()
