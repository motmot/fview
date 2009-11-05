from setuptools import setup, find_packages

setup(name='motmot.fview',
      description='extensible camera viewer program (part of the motmot camera packages)',
      author='Andrew Straw',
      author_email='strawman@astraw.com',
      url='http://code.astraw.com/projects/motmot/fview.html',
      license='BSD',
      version='0.6.1', # keep in sync with motmot/fview/version.py
      zip_safe=True,
      namespace_packages = ['motmot','motmot.fview'],
      packages = find_packages(),
      entry_points = {'gui_scripts': ['fview=motmot.fview.fview:main',
                                      'fview_fmf_replay = motmot.fview.fview_fmf_replay:main',
                                      ]},
      package_data = {'motmot.fview':['fview.xrc','fview.gif',
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
      eager_resources = ['motmot/fview/fview.xrc','motmot/fview/fview.gif',  # unpack files together
                         'motmot/fview/IPX-2M30-G.xml',
                         'motmot/fview/IPX-2M30-L.xml',
                         'motmot/fview/A602f.conf',
                         'motmot/fview/A622f.conf',
                         'motmot/fview/Scorpion.conf',
                         'motmot/fview/Fire-i BCL 1.2.conf',
                         'motmot/fview/Fire-i BBW 1.3.conf',
                         ],
      )
