= Overview =

fview is an application to view and record data from uncompressed
digital video cameras. The name ''fview'' derives from "fly viewer" --
the software was developed within the [http://dickinson.caltech.edu/ Dickinson Lab]
at [http://www.caltech.edu/ Caltech] to record movies of flies.

= Features =

 * '''Plugins for realtime image analysis''' Plugins to perform
   realimage image analysis are straightforward to write, with
   templates included to get you started quickly. Plugins have been
   written, for example, to perform background subtraction very
   quickly by making use of Intel's Integrated Performance Primatives
   (IPP) library.

 * '''Many supported cameras''' fview uses [wiki:cam_iface] to
   interact with cameras. This means that if you use fview, your code
   is independent from the particular camera hardware you're using.

 * '''Written in Python''' [http://python.org/ Python] is used as the "glue" that hold the application together -- the
   underlying image processing and saving is performed by high
   performance C code. Flexible memory allocation is possible for easy
   integration with other languages and libraries.

= Running fview =

Fview has options which can be set via environment variables. These are:

 * '''FVIEW_NO_REDIRECT''' Set to non-zero to direct all output to the
   console (linux) or to a pop-up window (Windows, Mac OS X).

 * '''FVIEW_NO_OPENGL''' Set to non-zero to disable use of OpenGL for
   image display. This will be slower and take more CPU time, but will
   avoid any potential bugs with the OpenGL side of things.

 * '''FVIEW_SAVE_PATH''' Set to the directory name in which to record
   movies. (This can also be set with the Menu option "File->set
   record Directory...".)

= Current limitations =

fview currently only supports a single camera. Although the plugin
structure and the camera interface are inherently multi-camera ready,
fview itself has not been written to support capturing from multiple
cameras simultaneously.
