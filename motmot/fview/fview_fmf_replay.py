import pkg_resources
import motmot.FlyMovieFormat.FlyMovieFormat as FlyMovieFormat
import numpy
import wx
import wx.xrc as xrc
import motmot.wxglvideo.simple_overlay as simple_overlay
import time, Queue, threading, os
import sys
import motmot.fview.plugin_manager as plugin_manager # fview's own plugin_manager
from optparse import OptionParser

RESFILE = pkg_resources.resource_filename(__name__,"fview_fmf_replay.xrc") # trigger extraction
RESDIR = os.path.split(RESFILE)[0]
RES = xrc.EmptyXmlResource()
RES.LoadFromString(open(RESFILE).read())

global last_frame_info
last_frame_info = None

class ReplayApp(wx.App):

    def OnInit(self,*args,**kw):
        usage = '%prog [options] fmf_filename'

        parser = OptionParser(usage)

        parser.add_option("--plugin", type='int',
                          help="choose plugin (use --show-plugins first)",
                          default=0)

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

        self.frame = RES.LoadFrame(None,"FVIEW_FMF_REPLAY_FRAME") # make frame main panel
        self.plugins, plugin_dict = plugin_manager.load_plugins(self.frame)

        if self.options.show_plugins:
            print 'plugin description'
            print '------ -----------'
            for i,plugin in enumerate(self.plugins):
                print '    ',i,plugin
            sys.exit(0)

        wx.InitAllImageHandlers()

        self.frame.Show()

        widget = xrc.XRCCTRL(self.frame,"LOAD_FMF_BUTTON")
        wx.EVT_BUTTON(widget, widget.GetId(), self.OnLoadFmf)

        widget = xrc.XRCCTRL(self.frame,"PLAY_FRAMES")
        wx.EVT_BUTTON(widget, widget.GetId(), self.OnPlayFrames)

        self.loaded_fmf = None

        ####

        main_display_panel = xrc.XRCCTRL(self.frame,"MAIN_DISPLAY_PANEL")
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
        if not len(self.plugins):
            raise ValueError('There are no plugins. Therefore, '
                             'there is no point in running fmf replay')
        for plugin in self.plugins:
            if hasattr(plugin,'set_all_fview_plugins'):
                plugin.set_all_fview_plugins(self.plugins)
        self.tracker = self.plugins[self.options.plugin]
        self.tracker.get_frame().Show()

        self.play_thread = None


        wx.EVT_CLOSE(self.tracker.get_frame(),self.OnTrackerWindowClose)

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
                if i==1:
                    time_start=time.time()
                play_func(self.loaded_fmf,
                          self.inq,
                          self.playing,
                          self.buf_allocator)
                for j in range(self.inq.qsize()):
                    tup = self.inq.get(0)

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

        try:
            while 1:
                tup = self.inq.get(0)
                self.statusbar.SetStatusText('playing',1)
        except Queue.Empty:
            pass

        if (tup is None and
            self.options.pump and
            last_frame_info is not None):
            points,linesegs = self.tracker.process_frame(*last_frame_info)
            im = last_frame_info[1]
            tup = im, points, linesegs

        if not self.options.quick:
            if tup is not None:
                im, points, linesegs = tup
                # display on screen
                self.cam_image_canvas.update_image_and_drawings('camera',
                                                                im,
                                                                format=self.loaded_fmf['format'],
                                                                points=points,
                                                                linesegs=linesegs,
                                                                )

    def OnLoadFmf(self,event):
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
        if hasattr(self.tracker,'get_buffer_allocator'):
            self.buf_allocator = self.tracker.get_buffer_allocator(cam_id)

        self.tracker.camera_starting_notification(cam_id,
                                                  pixel_format=format,
                                                  max_width=bg_image.shape[1],
                                                  max_height=bg_image.shape[0])

        if hasattr(self.tracker,'offline_startup_func'):
            self.tracker.offline_startup_func(self.options.plugin_arg)

        # save data for processing
        self.loaded_fmf = dict( fmf=fmf,
                                n_frames=n_frames,
                                bg_image=bg_image,
                                cam_id=cam_id,
                                format=format,
                                tracker=self.tracker,
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

        self.statusbar.SetStatusText('%s loaded'%(os.path.split(fmf_filename)[1],),0)

        if self.options.pump:
            last_frame_info = (cam_id,
                               bg_image,
                               (0,0),
                               timestamp0,
                               0)


    def OnTrackerWindowClose(self,event):
        pass # don't close window (pointless in trax_replay)

    def OnPlayFrames(self,event):
        if self.loaded_fmf is None:
            print 'no .fmf file loaded'
            return
        self.play_thread = threading.Thread( target=play_func, args=(self.loaded_fmf,
                                                                     self.inq,
                                                                     self.playing,
                                                                     self.buf_allocator) )
        self.play_thread.setDaemon(True)#don't let this thread keep app alive
        self.play_thread.start()

def play_func(loaded_fmf, im_pts_segs_q, playing, buf_allocator ):
    global last_frame_info
    playing.set()
    try:
        n_frames = loaded_fmf['n_frames']
        fmf = loaded_fmf['fmf']
        bg_image = loaded_fmf['bg_image']
        tracker = loaded_fmf['tracker']
        cam_id = loaded_fmf['cam_id']
        format = loaded_fmf['format']

        fmf.seek(0)
        for fno in range(n_frames):
            # reconstruct original frame #################
            fullsize_image,timestamp = fmf.get_frame(fno)
            loaded_fmf['bg_image'] = fullsize_image

            # process with tracker #################
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

            points,linesegs = tracker.process_frame(*last_frame_info)
            tup = fullsize_image, points, linesegs
            im_pts_segs_q.put( tup )
            #time.sleep(1e-2)
    finally:
        playing.clear()

def main():

    app = ReplayApp(0)
    app.MainLoop()

    if app.loaded_fmf is not None:
        app.tracker.quit()

if __name__=='__main__':
    main()
