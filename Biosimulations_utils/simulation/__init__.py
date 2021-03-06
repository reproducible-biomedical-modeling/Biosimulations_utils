""" Utilities for working with simulation experiments

:Author: Jonathan Karr <karr@mssm.edu>
:Date: 2020-03-22
:Copyright: 2020, Center for Reproducible Biomedical Modeling
:License: MIT
"""

from .data_model import SimulationFormat
from ..visualization.data_model import Visualization  # noqa: F401
from .sedml import SedMlSimulationWriter, SedMlSimulationReader

__all__ = ['write_simulation', 'read_simulation']


def write_simulation(sim, filename, format=SimulationFormat.sedml, visualization=None, **format_opts):
    """ Write a simulation experiment to a file

    Args:
        sim (:obj:`dict`): Simulation experiment
        filename (:obj:`str`): Path to save simulation experiment in SED-ML format
        visualization (:obj:`Visualization`, optional): visualization
        format (:obj:`SimulationFormat`, optional): simulation experiment format
        format_opts (:obj:`dict`, optional): options to the simulation experiment format (e.g., level, version)

    Raises:
        :obj:`NotImplementedError`: the format is not supported
    """
    if format == SimulationFormat.sedml:
        Writer = SedMlSimulationWriter
    else:
        raise NotImplementedError("Simulation experiment format {} is not supported".format(format.name))
    return Writer().run(sim, filename, visualization=visualization, **format_opts)


def read_simulation(filename, format=SimulationFormat.sedml):
    """ Read a simulation experiment from a file

    Args:
        filename (:obj:`str`): path to save simulation
        format (:obj:`SimulationFormat`, optional): simulation experiment format

    Returns:
        :obj:`tuple`

            * :obj:`list` of :obj:`Simulation`: simulations
            * :obj:`Visualization`: visualization

    Raises:
        :obj:`NotImplementedError`: the format is not supported
    """
    if format == SimulationFormat.sedml:
        Reader = SedMlSimulationReader
    else:
        raise NotImplementedError("Simulation experiment format {} is not supported".format(format.name))
    return Reader().run(filename)
