# encoding: utf-8

from sdsstools import get_config, get_package_version


# pip package name
NAME = "sdss-yao"

# Loads config. config name is the package name.
config = get_config("yao")


# package name should be pip package name
__version__ = get_package_version(path=__file__, package_name=NAME)


from .actor import YaoActor, YaoCommand
from .delegate import YaoDelegate
from .mech_commands import *
from .mech_controller import MechController
