""" Utilities for working with models

:Author: Jonathan Karr <karr@mssm.edu>
:Date: 2020-03-22
:Copyright: 2020, Center for Reproducible Biomedical Modeling
:License: MIT
"""

from ..data_model import Format  # noqa: F401
from .data_model import Biomodel, BiomodelParameter, BiomodelVariable  # noqa: F401
import abc

__all__ = ['BiomodelReader', 'BiomodelIoError', 'BiomodelIoWarning']


class BiomodelReader(abc.ABC):
    """ Read information about models

    Attributes:
        _filename (:obj:`str`): path to a file which defines a model
    """

    def __init__(self):
        self._filename = None

    def run(self, filename):
        """ Read a model from a file

        Args:
            filename (:obj:`str`): path to a file which defines a model

        Returns:
            :obj:`Biomodel`: model
        """
        self._filename = filename

        model = Biomodel()
        model_orig = self._read_from_file(filename, model)
        self._read_format(model_orig, model)
        self._read_metadata(model_orig, model)
        units = self._read_units(model_orig, model)
        self._read_parameters(model_orig, model, units)
        self._read_variables(model_orig, model, units)

        return model

    @abc.abstractmethod
    def _read_from_file(self, filename, model):
        """ Read a model from a file

        Args:
            filename (:obj:`str`): path to a file which defines a model
            model (:obj:`Biomodel`): model

        Returns:
            :obj:`object`: model encoded in a format such as SBML
        """
        pass  # pragma: no cover

    @abc.abstractmethod
    def _read_format(self, model_orig, model):
        """ Read the format of a model

        Args:
            model_orig (:obj:`object`): original model encoded in a format such as SBML
            model (:obj:`Biomodel`): model

        Returns:
            :obj:`Format`: format of the model
        """
        pass  # pragma: no cover

    @abc.abstractmethod
    def _read_metadata(self, model_orig, model):
        """ Read the metadata of a model

        Args:
            model_orig (:obj:`object`): original model encoded in a format such as SBML
            model (:obj:`Biomodel`): model

        Returns:
            :obj:`Biomodel`: model with additional metadata
        """
        pass  # pragma: no cover

    @abc.abstractmethod
    def _read_units(self, model_orig, model):
        """ Read the units of a model

        Args:
            model_orig (:obj:`object`): original model encoded in a format such as SBML
            model (:obj:`Biomodel`): model

        Returns:
            :obj:`dict`: dictionary that maps the ids of units to their definitions
        """
        pass  # pragma: no cover

    @abc.abstractmethod
    def _read_parameters(self, model_orig, model):
        """ Read the parameters of a model

        Args:
            model_orig (:obj:`object`): original model encoded in a format such as SBML
            model (:obj:`Biomodel`): model

        Returns:
            :obj:`list` of :obj:`BiomodelParameter`: information about parameters
        """
        pass  # pragma: no cover

    @abc.abstractmethod
    def _read_variables(self, model_orig, model):
        """ Read the variables of a model

        Args:
            model_orig (:obj:`object`): original model encoded in a format such as SBML
            model (:obj:`Biomodel`): model

        Returns:
            :obj:`list` of :obj:`BiomodelVariable`: information about the variables of the model
        """
        pass  # pragma: no cover


class BiomodelIoError(Exception):
    """ Model IO error """
    pass


class BiomodelIoWarning(UserWarning):
    """ Model IO warning """
    pass
