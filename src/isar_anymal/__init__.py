from importlib.metadata import version

from .robotinterface import Robot as Robot

__version__ = version(__package__ or __name__)
