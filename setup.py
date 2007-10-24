from setuptools import setup

import os, sys
import fview.version

install_requires = ['cam_iface>=0.3.dev280',
                    'FlyMovieFormat',
                    'wxglvideo>=0.3.dev283',
                    'wxvalidatedtext>=0.4.dev46',
                    ]
if sys.platform.startswith('linux'):
    # Not all POSIX platforms support sched_getparam().
    # See http://lists.apple.com/archives/Unix-porting/2005/Jul/msg00027.html
    install_requires.append('posix_sched')

setup(name='fview',
      description='extensible camera viewer program (part of the motmot camera packages)',
      author='Andrew Straw',
      author_email='strawman@astraw.com',
      url='http://code.astraw.com/projects/motmot',
      license='BSD',
      version=fview.version.__version__,
      zip_safe=True,
      packages = ['fview'],
      install_requires = install_requires,
      entry_points = {'gui_scripts': ['fview=fview:main',
                                      'fview_fmf_replay = fview.fview_fmf_replay:main',
                                      ]},
      package_data = {'fview':['fview.xrc','fview.gif',
                               # ImperX .xml files for config (used on Windows only)
                               'IPX-2M30-G.xml',
                               'IPX-2M30-L.xml',
                               # camera .conf files for camwire (used on linux only)
                               'A602f.conf',
                               'A622f.conf',
                               'Scorpion.conf',
                               'Fire-i BCL 1.2.conf',
                               'Fire-i BBW 1.3.conf',
                               'fview_icon2.png', # for .desktop icon
                              ]},
      eager_resources = ['fview/fview.xrc','fview/fview.gif',  # unpack files together
                         'fview/IPX-2M30-G.xml',
                         'fview/IPX-2M30-L.xml',
                         'fview/A602f.conf',
                         'fview/A622f.conf',
                         'fview/Scorpion.conf',
                         'fview/Fire-i BCL 1.2.conf',
                         'fview/Fire-i BBW 1.3.conf',
                         ],
      )
