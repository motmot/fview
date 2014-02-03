from setuptools import setup, find_packages

setup(name='motmot.fview',
      description='extensible camera viewer program (part of the motmot camera packages)',
      author='Andrew Straw',
      author_email='strawman@astraw.com',
      url='http://code.astraw.com/projects/motmot/fview.html',
      license='BSD',
      version='0.7.4', # keep in sync with motmot/fview/version.py
      namespace_packages = ['motmot'],
      packages = find_packages(),
      entry_points = {
    'gui_scripts': ['fview=motmot.fview.fview:main',
                    'fview_fmf_replay = motmot.fview.fview_fmf_replay:main',
                    ]},
      package_data = {'motmot.fview':['fview.xrc','fview.gif',
                                      'fview_icon2.png', # for .desktop icon
                                      ]},
      eager_resources = ['motmot/fview/fview.xrc',
                         'motmot/fview/fview.gif',
                         ],
      )
