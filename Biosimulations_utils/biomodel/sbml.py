""" Utilities for working with SBML-encoded models

:Author: Jonathan Karr <karr@mssm.edu>
:Date: 2020-03-22
:Copyright: 2020, Center for Reproducible Biomedical Modeling
:License: MIT
"""

from ..data_model import Format, OntologyTerm, RemoteFile, Taxon, Type  # noqa: F401
from ..utils import pretty_print_units, crop_image, get_logger
from .core import BiomodelReader, BiomodelIoError
from .data_model import Biomodel, BiomodelParameter, BiomodelVariable, BiomodelingFramework, BiomodelFormat  # noqa: F401
import copy
import ete3
import libsbml
import logging
import os
import re
import requests
import requests.exceptions
import requests_cache.core  # noqa: F401

__all__ = ['SbmlBiomodelReader', 'visualize_biomodel']


class XmlName(object):
    """ Name of an XML node

    Attributes:
        prefix (:obj:`str`): prefix
        name (:obj:`str`): name
    """

    def __init__(self, prefix, name):
        """
        Args:
            prefix (:obj:`str`): prefix
            name (:obj:`str`): name
        """
        self.prefix = prefix
        self.name = name


class SbmlBiomodelReader(BiomodelReader):
    """ Read information about SBML-encoded models

    Attributes:
        _logger (:obj:`logging.Logger`): logger
    """

    def __init__(self):
        super(SbmlBiomodelReader, self).__init__()
        self._logger = get_logger('sbml')

    def _read_from_file(self, filename, model):
        """ Read a SBML-encoded model from a file

        Args:
            filename (:obj:`str`): path to a file which defines an SBML-encoded model

        Returns:
            :obj:`libsbml.Model`: SBML-encoded model

        Raises:
            :obj:`ValueError`: file doesn't exist
        """
        if not os.path.isfile(filename):
            raise ValueError('{} does not exist'.format(filename))
        model.file = RemoteFile(name=os.path.basename(filename), type='application/sbml+xml', size=os.path.getsize(filename))
        reader = libsbml.SBMLReader()
        doc = reader.readSBMLFromFile(filename)
        model_sbml = doc.getModel()
        if not model_sbml:
            raise ValueError('{} does not contain a valid model'.format(filename))
        return model_sbml

    def _read_format(self, model_sbml, model):
        """ Read the metadata of a model

        Args:
            model_sbml (:obj:`libsbml.Model`): SBML-encoded model
            model (:obj:`Biomodel`): model

        Returns:
            :obj:`Format`: format of the model
        """
        model.format = copy.copy(BiomodelFormat.sbml.value)
        model.format.version = 'L{}V{}'.format(model_sbml.getLevel(), model_sbml.getVersion())
        return model.format

    def _read_metadata(self, model_sbml, model):
        """ Read the metadata of a model

        Args:
            model_sbml (:obj:`libsbml.Model`): SBML-encoded model
            model (:obj:`Biomodel`): model

        Returns:
            :obj:`Biomodel`: model with additional metadata

        Raises:
            :obj:`BiomodelIoError`: if the model uses an unsupported SBML package or any unsupported combination of packages
        """
        model.id = model_sbml.getId() or None
        model.name = model_sbml.getName() or None

        annot_xml = model_sbml.getAnnotation()
        desc_xml = self._get_xml_child_by_names(annot_xml, [
            XmlName('rdf', 'RDF'),
            XmlName('rdf', 'Description'),
        ])

        # modeling framework
        packages = set()
        for i_plugin in range(model_sbml.getNumPlugins()):
            plugin_sbml = model_sbml.getPlugin(i_plugin)
            packages.add(plugin_sbml.getPackageName())

        unsupported_packages = packages.difference(set(['annot', 'comp', 'fbc', 'groups', 'layout', 'multi', 'qual', 'render', 'req']))
        if unsupported_packages:
            raise BiomodelIoError("{} package(s) are not supported".format(
                ', '.join(unsupported_packages))
            )  # pragma: no cover # unreachable with libSBML 5.18 which doesn't support additional packages

        plugin = model_sbml.getSBMLDocument().getPlugin('comp')
        if plugin:
            if plugin.getNumModelDefinitions() or plugin.getNumExternalModelDefinitions():
                raise BiomodelIoError('comp package is not supported')
        plugin = model_sbml.getPlugin('comp')
        if plugin:
            if plugin.getNumSubmodels():
                raise BiomodelIoError('comp package is not supported')

        if len(packages.intersection(set(['fbc', 'multi', 'qual']))) > 1:
            raise BiomodelIoError('Unable to determine modeling framework')
        if 'fbc' in packages:
            framework = BiomodelingFramework.flux_balance
        elif 'multi' in packages:
            framework = BiomodelingFramework.non_spatial_discrete
        elif 'qual' in packages:
            framework = BiomodelingFramework.logical
        else:
            framework = BiomodelingFramework.non_spatial_continuous
        model.framework = framework.value

        # taxon
        taxon_xml = self._get_xml_child_by_names(desc_xml, [
            XmlName('bqbiol', 'hasTaxon'),
            XmlName('rdf', 'Bag'),
            XmlName('rdf', 'li'),
        ])
        model.taxon = None
        if taxon_xml:
            taxon_url = self._get_xml_attr_by_name(taxon_xml, XmlName('rdf', 'resource'))
            match = re.match(r'https?://identifiers.org/taxonomy/(\d+)', taxon_url)
            if match:
                taxon_id = int(match.group(1))
                ncbi_taxa = ete3.NCBITaxa()
                taxon_name = ncbi_taxa.get_taxid_translator([taxon_id]).get(taxon_id, None)
                if taxon_name:
                    model.taxon = Taxon(
                        id=taxon_id,
                        name=taxon_name,
                    )

        return model

    def _read_units(self, model_sbml, model):
        """ Read the units of a model

        Args:
            model_sbml (:obj:`libsbml.Model`): SBML-encoded model
            model (:obj:`Biomodel`): model

        Returns:
            :obj:`dict`: dictionary that maps the ids of units to their definitions
        """
        units = {}
        for unit_def_sbml in model_sbml.getListOfUnitDefinitions():
            units[unit_def_sbml.getId()] = self._format_unit_def(unit_def_sbml.getDerivedUnitDefinition())

        return units

    def _read_parameters(self, model_sbml, model, units):
        """ Read information about the parameters of a model

        Args:
            model_sbml (:obj:`libsbml.Model`): SBML-encoded model
            model (:obj:`Biomodel`): model
            units (:obj:`dict`): dictionary that maps the ids of units to their definitions

        Returns:
            :obj:`list` of :obj:`BiomodelParameter`: information about parameters

        Raises:
            :obj:`AssertionError`: if any of the following conditions are met:

                * A compartment, species, or reaction doesn't have an id
                * The id of the active flux objective is the empty string
        """
        parameters = {}

        # global parameters
        for param_sbml in model_sbml.getListOfParameters():
            parameters[param_sbml.getId()] = self._read_parameter(param_sbml, model)

        # local parameters of reactions
        for rxn_sbml in model_sbml.getListOfReactions():
            kin_law_sbml = rxn_sbml.getKineticLaw()
            if kin_law_sbml:
                rxn_id = rxn_sbml.getId()
                rxn_name = rxn_sbml.getName() or None

                for param_sbml in kin_law_sbml.getListOfParameters():
                    assert rxn_id
                    parameters[(rxn_id, param_sbml.getId())] = self._read_parameter(
                        param_sbml, model, rxn_sbml=rxn_sbml, rxn_id=rxn_id, rxn_name=rxn_name)

        # compartment sizes
        for comp_sbml in model_sbml.getListOfCompartments():
            # ignore compartments with multi:isType="true"
            comp_multi_smbl = comp_sbml.getPlugin('multi')
            if comp_multi_smbl is not None and comp_multi_smbl.getIsType():
                continue

            # ignore compartments that don't have a set size
            if not comp_sbml.isSetSize():
                continue

            comp_id = comp_sbml.getId()
            assert comp_id
            comp_name = comp_sbml.getName() or comp_id

            value = comp_sbml.getSize()
            parameters[comp_id] = BiomodelParameter(
                target="/sbml:sbml/sbml:model/sbml:listOfCompartments/sbml:compartment[@id='{}']/@size".format(comp_id),
                group='Initial compartment sizes',
                id="init_size_{}".format(comp_id),
                name='Initial size of {}'.format(comp_name),
                description=None,
                identifiers=[],
                type=Type.float,
                value=value,
                recommended_range=self._calc_recommended_param_range(value),
                units=self._format_unit_def(comp_sbml.getDerivedUnitDefinition()),
            )

        # initial amounts / concentrations of species
        for species_sbml in model_sbml.getListOfSpecies():
            if not (species_sbml.isSetInitialAmount() or species_sbml.isSetInitialConcentration()):
                continue

            species_id = species_sbml.getId()
            assert species_id

            species_name = species_sbml.getName() or species_id

            species_substance_units = units.get(species_sbml.getSubstanceUnits() or model_sbml.getSubstanceUnits(), None)
            if not species_substance_units:
                species_substance_units = species_sbml.getSubstanceUnits() or model_sbml.getSubstanceUnits()
                self._logger.log(logging.ERROR, '{}: species {} does not have valid units'.format(self._filename, species_sbml.getId()))
            if species_sbml.isSetInitialAmount():
                species_initial_type = 'Amount'
                species_initial_val = species_sbml.getInitialAmount()
                species_initial_units = species_substance_units
            else:
                species_initial_type = 'Concentration'
                species_initial_val = species_sbml.getInitialConcentration()

                comp_sbml = self._get_compartment(model_sbml, species_sbml.getCompartment())

                if species_substance_units:
                    species_initial_units = pretty_print_units('({}) / ({})'.format(
                        species_substance_units,
                        self._format_unit_def(comp_sbml.getDerivedUnitDefinition())
                    ))
                else:
                    species_initial_units = None

            parameters[species_id] = BiomodelParameter(
                target='/' + '/'.join([
                    "sbml:sbml",
                    "sbml:model",
                    "sbml:listOfSpecies",
                    "sbml:species[@id='{}']".format(species_id),
                    "@initial{}".format(species_initial_type),
                ]),
                group='Initial species amounts/concentrations',
                id="init_{}_{}".format(species_initial_type.lower(), species_id),
                name='Initial {} of {}'.format(species_initial_type.lower(), species_name),
                description=None,
                identifiers=[],
                type=Type.float,
                value=species_initial_val,
                recommended_range=self._calc_recommended_param_range(species_initial_val),
                units=species_initial_units,
            )

        # initial assignments
        for init_assignment_sbml in model_sbml.getListOfInitialAssignments():
            symbol_id = init_assignment_sbml.getSymbol()
            symbol_sbml = model_sbml.getElementBySId(symbol_id)

            type, init_value = self._read_constant_from_math(init_assignment_sbml.getMath())
            if not type:
                continue

            parameters["init_assignment_{}".format(symbol_id)] = BiomodelParameter(
                target='/' + '/'.join([
                    "sbml:sbml",
                    "sbml:model",
                    "sbml:listOfInitialAssignments",
                    "sbml:initialAssignment[@symbol='{}']".format(symbol_id),
                    "mathml:math",
                    "mathml:cn",
                    "text",
                ]),
                group='Initial assignments',
                id="init_assignment_{}".format(symbol_id),
                name='Initial assignment of {}'.format(symbol_sbml.getName() or symbol_id),
                description=None,
                identifiers=[],
                type=type,
                value=init_value,
                recommended_range=self._calc_recommended_param_range(init_value),
                units=self._format_unit_def(symbol_sbml.getDerivedUnitDefinition()),
            )

        # assignment rules
        for rule_sbml in model_sbml.getListOfRules():
            if rule_sbml.isScalar():
                var_id = rule_sbml.getVariable()
                var_sbml = model_sbml.getElementBySId(var_id)

                type, value = self._read_constant_from_math(rule_sbml.getMath())
                if not type:
                    continue

                parameters["assignment_{}".format(var_id)] = BiomodelParameter(
                    target='/' + '/'.join([
                        "sbml:sbml",
                        "sbml:model",
                        "sbml:listOfRules",
                        "sbml:assignmentRule[@variable='{}']".format(var_id),
                        "mathml:math",
                        "mathml:cn",
                        "text",
                    ]),
                    group='Assignments',
                    id="assignment_{}".format(var_id),
                    name='Assignment of {}'.format(var_sbml.getName() or var_id),
                    description=None,
                    identifiers=[],
                    type=type,
                    value=value,
                    recommended_range=self._calc_recommended_param_range(value),
                    units=self._format_unit_def(var_sbml.getDerivedUnitDefinition()),
                )

        # fbc package
        plugin_sbml = model_sbml.getPlugin('fbc')
        if plugin_sbml:
            obj_sbml = plugin_sbml.getActiveObjective()
            assert obj_sbml

            obj_id = obj_sbml.getId()
            obj_name = obj_sbml.getName() or obj_id
            for flux_obj_sbml in obj_sbml.getListOfFluxObjectives():
                rxn_id = flux_obj_sbml.getReaction()
                rxn_sbml = self._get_reaction(model_sbml, rxn_id)
                rxn_name = rxn_sbml.getName() or rxn_id
                value = flux_obj_sbml.getCoefficient()
                parameters[species_id] = BiomodelParameter(
                    target='/' + '/'.join([
                        "sbml:sbml",
                        "sbml:model",
                        "fbc:listOfObjectives",
                        "fbc:objective[@fbc:id='{}']".format(obj_id),
                        "fbc:listOfFluxObjectives",
                        "fbc:fluxObjective[@fbc:reaction='{}']".format(rxn_id),
                        "@fbc:coefficient",
                    ]),
                    group='Flux objective coefficients',
                    id="{}/{}".format(obj_id, rxn_id),
                    name='Coefficient of {} of {}'.format(obj_name, rxn_name),
                    description=None,
                    identifiers=[],
                    type=Type.float,
                    value=value,
                    recommended_range=self._calc_recommended_param_range(value),
                    units='dimensionless',
                )

        # qual package
        plugin_sbml = model_sbml.getPlugin('qual')
        if plugin_sbml:
            for species_sbml in plugin_sbml.getListOfQualitativeSpecies():
                species_id = species_sbml.getId()
                init_level = species_sbml.getInitialLevel()
                if species_sbml.isSetMaxLevel():
                    max_level = species_sbml.getMaxLevel()
                else:
                    max_level = max(1, init_level)

                parameters[species_id] = BiomodelParameter(
                    target='/' + '/'.join([
                        "sbml:sbml",
                        "sbml:model",
                        "qual:listOfQualitativeSpecies",
                        "qual:qualitativeSpecies[@qual:id='{}']".format(species_id),
                        "@qual:initialLevel",
                    ]),
                    group='Initial species levels',
                    id='init_level_' + species_id,
                    name='Initial level of {}'.format(species_sbml.getName() or species_id),
                    description=None,
                    identifiers=[],
                    type=Type.integer,
                    value=init_level,
                    recommended_range=[0, max_level],
                    units='dimensionless',
                )

        # ignore parameters set via assignment rules and initial assignments
        for rule_sbml in model_sbml.getListOfRules():
            if rule_sbml.isScalar():
                param_id = rule_sbml.getVariable()
                if param_id in parameters:
                    parameters.pop(param_id)

        for init_assign_sbml in model_sbml.getListOfInitialAssignments():
            param_id = init_assign_sbml.getSymbol()
            if param_id in parameters:
                parameters.pop(param_id)

        # return parameters
        model.parameters = parameters.values()
        return model.parameters

    def _read_parameter(self, param_sbml, model, rxn_sbml=None, rxn_id=None, rxn_name=None):
        """ Read information about a SBML parameter

        Args:
            param_sbml (:obj:`libsbml.BiomodelParameter`): SBML parameter
            model (:obj:`Biomodel`): model
            rxn_sbml (:obj:`libsbml.Reaction`, optional): SBML reaction
            rxn_id (:obj:`str`, optional): id of the parent reaction (used by local parameters)
            rxn_name (:obj:`str`, optional): name of the parent reaction (used by local parameters)

        Returns:
            :obj:`BiomodelParameter`: information about the parameter

        Raises:
            :obj:`AssertionError`: the parameter doesn't have an id
        """
        assert param_sbml.getId()

        value = param_sbml.getValue()
        param = BiomodelParameter(
            target=None,
            group=None,
            id=param_sbml.getId(),
            name=param_sbml.getName() or param_sbml.getId(),
            description=None,
            identifiers=[],
            type=Type.float,
            value=value,
            recommended_range=self._calc_recommended_param_range(value),
            units=self._format_unit_def(param_sbml.getDerivedUnitDefinition()),
        )

        if rxn_sbml:
            if int(model.format.version[1]) >= 3:
                target = [
                    "sbml:sbml",
                    "sbml:model",
                    "sbml:listOfReactions",
                    "{}:{}[@id='{}']".format(rxn_sbml.getPrefix() or 'sbml', rxn_sbml.getElementName(), rxn_id),
                    "sbml:kineticLaw",
                    "sbml:listOfLocalParameters",
                    "sbml:{}[@id='{}']".format(param_sbml.getElementName(), param.id),
                    "@value",
                ]
            else:
                target = [
                    "sbml:sbml",
                    "sbml:model",
                    "sbml:listOfReactions",
                    "{}:{}[@id='{}']".format(rxn_sbml.getPrefix() or 'sbml', rxn_sbml.getElementName(), rxn_id),
                    "sbml:kineticLaw",
                    "sbml:listOfParameters",
                    "sbml:{}[@id='{}']".format(param_sbml.getElementName(), param.id),
                    "@value",
                ]
            group = '{} rate constants'.format(rxn_name or rxn_id)
        else:
            target = [
                "sbml:sbml",
                "sbml:model",
                "sbml:listOfParameters",
                "sbml:parameter[@id='{}']".format(param.id),
                "@value",
            ]
            group = 'Other global parameters'
        param.target = '/' + '/'.join(target)
        param.group = group

        if rxn_id:
            param.id = rxn_id + '/' + param.id
            param.name = (rxn_name or rxn_id) + ': ' + (param.name or param.id)

        return param

    def _read_variables(self, model_sbml, model, units):
        """ Read the variables of a model

        Args:
            model_sbml (:obj:`libsbml.Model`): SBML-encoded model
            model (:obj:`Biomodel`): model
            units (:obj:`dict`): dictionary that maps the ids of units to their definitions

        Returns:
            :obj:`list` of :obj:`BiomodelVariable`: information about the variables of the model

        Raises:
            :obj:`AssertionError`: there is no active objective or the active flux objective has no id
        """
        model.variables = vars = []

        fbc_plugin_sbml = model_sbml.getPlugin('fbc')

        if fbc_plugin_sbml:
            extent_units = units.get(model_sbml.getExtentUnits(), None)
            if not extent_units:
                extent_units = model_sbml.getExtentUnits()
                self._logger.log(logging.ERROR, '{}: model does not have valid extent units'.format(self._filename))

            time_units = units.get(model_sbml.getTimeUnits(), None)
            if not time_units:
                time_units = model_sbml.getTimeUnits()
                self._logger.log(logging.ERROR, '{}: model does not have valid time units'.format(self._filename))

            flux_units = pretty_print_units('({}) / ({})'.format(extent_units, time_units))

            # objective
            obj_sbml = fbc_plugin_sbml.getActiveObjective()
            assert obj_sbml

            obj_id = obj_sbml.getId()
            assert obj_id

            vars.append(BiomodelVariable(
                target="/sbml:sbml/sbml:model/fbc:listOfObjectives/fbc:objective[@fbc:id='{}']".format(obj_id),
                group='Objectives',
                id=obj_id,
                name=obj_sbml.getName() or obj_id,
                description=None,
                identifiers=[],
                type=Type.float,
                units=flux_units,
            ))

            # reaction fluxes
            for rxn_sbml in model_sbml.getListOfReactions():
                rxn_id = rxn_sbml.getId()
                vars.append(BiomodelVariable(
                    target="/sbml:sbml/sbml:model/sbml:listOfReactions/{}:{}[@id='{}']".format(
                        rxn_sbml.getPrefix() or 'sbml', rxn_sbml.getElementName(), rxn_id),
                    group='Reaction fluxes',
                    id=rxn_id,
                    name=rxn_sbml.getName() or None,
                    description=None,
                    identifiers=[],
                    type=Type.float,
                    units=flux_units,
                ))

        else:
            # regular species
            for species_sbml in model_sbml.getListOfSpecies():
                vars.append(self._read_variable(model_sbml, species_sbml, model))

            # compartments, parameters set via assignment rules
            for rule_sbml in model_sbml.getListOfRules():
                type, _ = self._read_constant_from_math(rule_sbml.getMath())
                if type:
                    continue

                if rule_sbml.isScalar():
                    var_id = rule_sbml.getVariable()
                    var_sbml = model_sbml.getElementBySId(var_id)
                    if isinstance(var_sbml, libsbml.Parameter):
                        vars.append(BiomodelVariable(
                            target=("/sbml:sbml/sbml:model/sbml:listOfParameters"
                                    "/sbml:parameter[@id='{}']").format(var_id),
                            group='Other',
                            id=var_id,
                            name=var_sbml.getName() or None,
                            description=None,
                            identifiers=[],
                            type=Type.float,
                            units=self._format_unit_def(var_sbml.getDerivedUnitDefinition()),
                        ))
                    elif isinstance(var_sbml, libsbml.Compartment):
                        vars.append(BiomodelVariable(
                            target=("/sbml:sbml/sbml:model/sbml:listOfCompartments"
                                    "/sbml:compartment[@id='{}']").format(var_id),
                            group='Compartment sizes',
                            id=var_id,
                            name=var_sbml.getName() or None,
                            description=None,
                            identifiers=[],
                            type=Type.float,
                            units=self._format_unit_def(var_sbml.getDerivedUnitDefinition()),
                        ))

            # qualitative species of qual package
            qual_plugin = model_sbml.getPlugin('qual')
            if qual_plugin:
                for species_sbml in qual_plugin.getListOfQualitativeSpecies():
                    species_id = species_sbml.getId()

                    vars.append(BiomodelVariable(
                        target=("/sbml:sbml/sbml:model/qual:listOfQualitativeSpecies"
                                "/qual:qualitativeSpecies[@qual:id='{}']").format(species_id),
                        group='Species levels',
                        id=species_id,
                        name=species_sbml.getName() or None,
                        description=None,
                        identifiers=[],
                        type=Type.integer,
                        units='dimensionless',
                    ))

        return vars

    def _read_variable(self, model_sbml, species_sbml, model):
        """ Read information about a SBML species

        Args:
            model_sbml (:obj:`libsbml.Biomodel`): SBML-encoded model
            species_sbml (:obj:`libsbml.Species`): SBML species
            model (:obj:`Biomodel`): model

        Returns:
            :obj:`BiomodelVariable`: information about the species

        Raises:
            :obj:`AssertionError`: the species has no id
        """
        id = species_sbml.getId()
        assert id

        var = BiomodelVariable(
            target="/sbml:sbml/sbml:model/sbml:listOfSpecies/sbml:species[@id='{}']".format(id),
            group='Species amounts/concentrations',
            id=id,
            name=species_sbml.getName() or None,
            description=None,
            identifiers=[],
            type=Type.float,
            units=self._format_unit_def(species_sbml.getDerivedUnitDefinition()),
        )

        return var

    def _read_constant_from_math(self, math_sbml):
        """Read the constant value of a mathematical expression

        Args:
            math_sbml (:obj:`libsbml.ASTNode`): mathematical expression

        Returns:
            :obj:`tuple`:

                * :obj:`Type`: type
                * :obj:`int` or :obj:`float`: value
        """
        math_type = math_sbml.getType()
        if math_type in [libsbml.AST_INTEGER]:
            type = Type.integer
            value = math_sbml.getInteger()
            return (type, value)
        elif math_type in [libsbml.AST_REAL, libsbml.AST_REAL_E]:
            type = Type.float
            value = math_sbml.getReal()
            return (type, value)
        elif math_type in [libsbml.AST_RATIONAL]:
            # todo: support rational numbers
            return (None, None)
        else:
            return (None, None)

    def _get_compartment(self, model_sbml, comp_id):
        """ Get a compartment

        Args:
            model_sbml (:obj:`libsbml.Model`): SBML-encoded model
            comp_id (:obj:`str`): compartment id

        Returns:
            :obj:`libsbml.Compartment`: compartment
        """
        for comp_sbml in model_sbml.getListOfCompartments():
            if comp_sbml.getId() == comp_id:
                return comp_sbml

    def _get_reaction(self, model_sbml, rxn_id):
        """ Get a reaction

        Args:
            model_sbml (:obj:`libsbml.Model`): SBML-encoded model
            rxn_id (:obj:`str`): reaction id

        Returns:
            :obj:`libsbml.Reaction`: reaction
        """
        for rxn_sbml in model_sbml.getListOfReactions():
            if rxn_sbml.getId() == rxn_id:
                return rxn_sbml

    def _format_unit_def(self, unit_def_sbml):
        """ Get a human-readable representation of a unit definition

        Args:
            unit_def_sbml (:obj:`libsbml.UnitDefinition`): unit definition

        Returns:
            :obj:`str`: human-readable string representation of the unit definition
        """
        if not unit_def_sbml:
            return None

        unit_def_str = unit_def_sbml.printUnits(unit_def_sbml, True)
        if unit_def_str == 'indeterminable':
            self._logger.log(logging.ERROR, '{}: unit definition {} is invalid'.format(self._filename, unit_def_sbml.getId()))
            return None

        return pretty_print_units(unit_def_str.replace(', ', ' * '))

    def _calc_recommended_param_range(self, value, zero_fold=10., non_zero_fold=10.):
        """ Calculate a recommended range for the value of a parameter

        Args:
            value (:obj:`float`): Default value
            non_zero_fold (:obj:`float`, optional): Multiplicative factor, :math:`f`, for the recommended minimum and maximum
                values relative to the default value, :math:`d`, producing the recommend range :math:`d / f - d * f`.

        Returns:
            :obj:`list` of :obj:`float`: recommended minimum and maximum values of the parameter
        """
        if value == 0:
            return [0., zero_fold]

        else:
            return [
                value * non_zero_fold ** -1,
                value * non_zero_fold,
            ]

    @classmethod
    def _get_xml_child_by_names(cls, node, names):
        """ Get the child of an XML element with a prefix and name

        Args:
            node (:obj:`libsbml.XMLNode`): XML node
            names (:obj:`list` of :obj:`XmlName`): names

        Returns:
            :obj:`libsbml.XMLNode`: child with prefix and name
        """
        for name in names:
            if not node:
                break
            node = cls._get_xml_child_by_name(node, name)
        return node

    @classmethod
    def _get_xml_child_by_name(cls, node, name):
        """ Get the child of an XML element with a prefix and name

        Args:
            node (:obj:`libsbml.XMLNode`): XML node
            name (:obj:`XmlName`): name

        Returns:
            :obj:`libsbml.XMLNode`: child with prefix and name
        """
        matching_children = []
        for i_child in range(node.getNumChildren()):
            child = node.getChild(i_child)
            if child.getPrefix() == name.prefix and child.getName() == name.name:
                matching_children.append(child)
        if len(matching_children) == 1:
            return matching_children[0]
        else:
            return None

    @classmethod
    def _get_xml_attr_by_name(cls, node, name):
        """ Get an attribute of an XML element with a prefix and name

        Args:
            node (:obj:`libsbml.XMLNode`): XML node
            name (:obj:`XmlName`): attribute name

        Returns:
            :obj:`str`: attribute value
        """
        for i_attr in range(node.getAttributesLength()):
            if node.getAttrPrefix(i_attr) == name.prefix and node.getAttrName(i_attr) == name.name:
                return node.getAttrValue(i_attr)


MINERVA_ENDPOINT = 'https://minerva-dev.lcsb.uni.lu/minerva/api/convert/image/{}:{}'


def visualize_biomodel(model_filename, img_filename, requests_session=None, remove_layouts=True, remove_units=True):
    """ Use `MINERVA <https://minerva.pages.uni.lu/>`_ to visualize a model and save the visualization to a PNG file.

    Args:
        model_filename (:obj:`str`): path to the SBML-encoded model
        img_filename (:obj:`str`): path to save the visualization of the model
        requests_session (:obj:`requests_cache.core.CachedSession`, optional): cached requests session
        remove_layouts (:obj:`bool`, optional): if :obj:`True`, remove layouts from model
        remove_units (:obj:`bool`, optional): if :obj:`True`, remove units from model

    Returns:
        :obj:`RemoteFile`: image

    Raises:
        :obj:`BiomodelIoError`: if an image could not be generated
    """
    if not os.path.isfile(img_filename):
        # read the model
        doc = libsbml.readSBMLFromFile(model_filename)
        model = doc.getModel()

        # remove layouts from the model
        if remove_layouts:
            plugin = model.getPlugin('layout')
            if plugin:
                for i_layout in range(plugin.getNumLayouts()):
                    plugin.removeLayout(i_layout)

        # remove units from model
        if remove_units:
            for unit_def in model.getListOfUnitDefinitions():
                for unit in range(unit_def.getNumUnits()):
                    unit_def.removeUnit(0)
                unit = unit_def.createUnit()
                unit.setExponent(0)
                unit.setKind(libsbml.UNIT_KIND_DIMENSIONLESS)
                unit.setMultiplier(1)
                unit.setScale(0)

        # encode corrected model to XML
        corrected_model = libsbml.writeSBMLToString(doc)

        # use MINERVA to generate a visualization of the model
        if requests_session is None:
            requests_session = requests

        url = MINERVA_ENDPOINT.format('SBML', 'png')
        response = requests_session.post(
            url, headers={'Content-Type': 'application/sbml+xml; charset=utf-8'}, data=corrected_model.encode('utf-8'))
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            logger = get_logger('minerva')
            logger.log(logging.ERROR, '{}: unable to generate image: {}'.format(os.path.basename(model_filename), response.content))
            raise BiomodelIoError('Unable to generate image for {}: {}'.format(os.path.basename(model_filename), response.content))
        with open(img_filename, 'wb') as file:
            file.write(response.content)
        crop_image(img_filename, background_to_transparent=[255, 255, 255])

    return RemoteFile(name=os.path.basename(img_filename), type='image/png', size=os.path.getsize(img_filename))
