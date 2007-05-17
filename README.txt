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

= Limitations =

fview currently only supports a single camera. Although the plugin
structure and the camera interface are inherently multi-camera ready,
fview itself has not been written to support capturing from multiple
cameras simultaneously.
