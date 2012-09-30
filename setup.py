from setuptools import setup, find_packages
import os

version = '0.1'

long_description = (
    open('README.txt').read()
    + '\n' +
    'Contributors\n'
    '============\n'
    + '\n' +
    open('CONTRIBUTORS.txt').read()
    + '\n' +
    open('CHANGES.txt').read()
    + '\n')

requires = ['pyramid', 'PasteScript',]

setup(name='mist.monitor',
      version=version,
      description="Monitoring node for the https://mist.io service",
      long_description=long_description,
      # Get more strings from
      # http://pypi.python.org/pypi?%3Aaction=list_classifiers
      classifiers=[
        "Programming Language :: Python",
        ],
      keywords='',
      author='',
      author_email='',
      url='https://mist.io/',
      license='copyright',
      packages=find_packages('src'),
      package_dir = {'': 'src'},
      namespace_packages=['mist'],
      include_package_data=True,
      zip_safe=False,
      install_requires= requires,
      entry_points="""
      # -*- Entry points: -*-
      [paste.app_factory]
      main = mist.monitor:main
      """,
      )
