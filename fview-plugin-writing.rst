.. _fview-plugin-writing:

*********************
Writing FView plugins
*********************

Overview
--------

The :mod:`fview` program provides a simple extensibility
mechanism. In outline, the steps required are:

* Create a subclass of :class:`fview.traited_plugin.HasTraits_FViewPlugin`.
* Implement your GUI interaction using traits_.
* Implement your realtime processing logic in your class's
  ``process_frame()`` method. Note that this code will be run in a
  separate thread of execution from the GUI, so be careful to avoid
  share memory structures without locking. The `buf` argument is a
  numpy array (or else supports the numpy array interface).
* Optionally, handle the various options allowed by FView.
* Finally, register your FView plugin.

To test your plugin, you can you the :command:`fview` command
directly, or you may use :command:`fview_fmf_replay` to test your
plugin on a saved video recording.

Register your FView plugin
--------------------------

In your ``setup.py``, use setuptools an add a ``motmot.fview.plugins``
key to ``entry_points``. For the above example, this would be::

  entry_points = {
    'motmot.fview.plugins':'fview_ext_trig = motmot.fview_ext_trig.fview_ext_trig:FviewExtTrig',
     }

.. _traits: http://code.enthought.com/projects/traits/

Tutorials
---------

.. toctree::

  fview-plugin-tutorial-histogram.rst
  fview-plugin-tutorial-periodic-trigger.rst
  fview-plugin-tutorial-change-trigger.rst
