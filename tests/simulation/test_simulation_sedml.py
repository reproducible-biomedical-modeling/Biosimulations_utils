""" Test of SED-ML utilities

:Author: Jonathan Karr <karr@mssm.edu>
:Date: 2020-03-20
:Copyright: 2020, Center for Reproducible Biomedical Modeling
:License: MIT
"""

from Biosimulations_format_utils.chart.data_model import Chart, ChartDataField, ChartDataFieldShape, ChartDataFieldType
from Biosimulations_format_utils.data_model import Format
from Biosimulations_format_utils.biomodel.data_model import BiomodelFormat, Biomodel, BiomodelVariable
from Biosimulations_format_utils.simulation import write_simulation, read_simulation, sedml
from Biosimulations_format_utils.simulation.core import SimulationIoError, SimulationIoWarning
from Biosimulations_format_utils.simulation.data_model import SimulationFormat, TimecourseSimulation, SimulationResult
from Biosimulations_format_utils.visualization.data_model import Visualization, VisualizationLayoutElement, VisualizationDataField
import json
import libsedml
import os
import shutil
import tempfile
import unittest


class WriteSedMlTestCase(unittest.TestCase):
    def setUp(self):
        self.dirname = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dirname)

    def test_gen_sedml(self):
        model_vars = [
            BiomodelVariable(id='species_1', target="/sbml:sbml/sbml:model/sbml:listOfSpecies/sbml:species[@id='species_1']"),
            BiomodelVariable(id='species_2', target="/sbml:sbml/sbml:model/sbml:listOfSpecies/sbml:species[@id='species_2']"),
        ]
        with open('tests/fixtures/simulation.json', 'rb') as file:
            sim = TimecourseSimulation.from_json(json.load(file))
        model_filename = os.path.join(self.dirname, 'model.sbml.xml')
        sim_filename = os.path.join(self.dirname, 'simulation.sed-ml.xml')
        write_simulation(model_vars, sim, model_filename, sim_filename,
                         SimulationFormat.sedml, level=1, version=3)

        sims_2, _ = read_simulation(
            sim_filename, BiomodelFormat.sbml, SimulationFormat.sedml)
        self.assertEqual(len(sims_2), 1)
        sim_2 = sims_2[0]
        self.assertEqual(
            set(v.id for v in sim_2.model.variables),
            set(v.id for v in model_vars))
        self.assertEqual(sim_2.model.file.name, model_filename)
        sim_2.model.file = None
        sim_2.model.variables = []
        self.assertEqual(sim_2, sim)
        self.assertEqual(sim_2.format.version, 'L1V3')

        with self.assertRaisesRegex(NotImplementedError, 'not supported'):
            read_simulation(None, BiomodelFormat.sbml, SimulationFormat.sessl)

        with self.assertRaisesRegex(NotImplementedError, 'not supported'):
            read_simulation(None, BiomodelFormat.cellml, SimulationFormat.sedml)

    def test_gen_sedml_errors(self):
        # Other versions/levels of SED-ML are not supported
        sim = TimecourseSimulation(
            model=Biomodel(
                format=Format(
                    name='SBML'
                )
            ),
            format=Format(
                name='SED-ML',
                version='L1V2',
            )
        )
        with self.assertRaisesRegex(ValueError, 'Format must be SED-ML'):
            write_simulation(None, sim, None, None, SimulationFormat.sedml, level=1, version=3)

        # other simulation experiments formats (e.g., SESSL) are not supported
        sim = TimecourseSimulation(
            model=Biomodel(
                format=Format(
                    name='SBML'
                )
            ),
            format=Format(
                name='SESSL'
            )
        )
        with self.assertRaisesRegex(NotImplementedError, 'is not supported'):
            write_simulation(None, sim, None, None, SimulationFormat.sessl, level=1, version=3)
        with self.assertRaisesRegex(ValueError, 'Format must be SED-ML'):
            write_simulation(None, sim, None, None, SimulationFormat.sedml, level=1, version=3)

        # other simulation experiments formats (e.g., SESSL) are not supported
        sim = TimecourseSimulation(
            model=Biomodel(
                format=Format(
                    name='CellML'
                )
            ),
            format=Format(
                name='SED-ML',
                version='L1V3',
            ),
        )
        with self.assertRaisesRegex(NotImplementedError, 'is not supported'):
            write_simulation(None, sim, 'model.sbml.xml', None, SimulationFormat.sedml, level=1, version=3)

    def test__get_obj_annotation(self):
        reader = sedml.SedMlSimulationReader()

        doc = libsedml.SedDocument()
        self.assertEqual(reader._get_obj_annotation(doc), [])

        doc.setAnnotation('<annotation></annotation>')
        self.assertEqual(reader._get_obj_annotation(doc), [])

        doc.setAnnotation('<annotation><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"></rdf:RDF></annotation>')
        self.assertEqual(reader._get_obj_annotation(doc), [])

        doc.setAnnotation(
            '<annotation><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            '<rdf:Description></rdf:Description>'
            '</rdf:RDF></annotation>')
        self.assertEqual(reader._get_obj_annotation(doc), [])

    def test__call_sedml_error(self):
        doc = libsedml.SedDocument()
        with self.assertRaisesRegex(ValueError, 'libsedml error:'):
            sedml.SedMlSimulationWriter._call_libsedml_method(doc, doc, 'setAnnotation', '<rdf')

        with self.assertRaisesRegex(SimulationIoError, 'libsedml error'):
            sedml.SedMlSimulationReader().run('non-existant-file')

    def test_read_with_multiple_models_and_sims_and_unsupported_task(self):
        filename = 'tests/fixtures/Simon2019-with-multiple-models-and-sims.sedml'
        with self.assertWarnsRegex(SimulationIoWarning, 'is not supported'):
            read_simulation(filename, BiomodelFormat.sbml, SimulationFormat.sedml)

    def test_read_with_unsupported_simulation(self):
        filename = 'tests/fixtures/Simon2019-with-one-step-sim.sedml'
        with self.assertRaisesRegex(SimulationIoError, 'Unsupported simulation type'):
            read_simulation(filename, BiomodelFormat.sbml, SimulationFormat.sedml)

    def test_read_biomodels_sims(self):
        sims, _ = read_simulation('tests/fixtures/Simon2019.sedml', BiomodelFormat.sbml, SimulationFormat.sedml)
        self.assertEqual(len(sims), 1)
        sim = sims[0]
        self.assertEqual(sim.model_parameter_changes, [])
        self.assertEqual(sim.start_time, 0.)
        self.assertEqual(sim.output_start_time, 0.)
        self.assertEqual(sim.end_time, 1.)
        self.assertEqual(sim.num_time_points, 100)
        self.assertEqual(sim.algorithm.kisao_id, 'KISAO:0000019')
        self.assertEqual(sim.algorithm_parameter_changes, [])

    def test_read_visualizations(self):
        filename = 'tests/fixtures/BIOMD0000000297.sedml'
        sims, viz = read_simulation(filename, BiomodelFormat.sbml, SimulationFormat.sedml)
        self.assertEqual(len(viz.layout), 4)

        viz.layout = viz.layout[slice(0, 1)]
        expected = Visualization(
            layout=[
                VisualizationLayoutElement(
                    chart=Chart(id='line'),
                    data=[
                        VisualizationDataField(
                            data_field=ChartDataField(
                                name='x',
                                shape=ChartDataFieldShape.array,
                                type=ChartDataFieldType.dynamic_simulation_result,
                            ),
                            simulation_results=[
                                SimulationResult(simulation=sims[0], variable=BiomodelVariable(id='time', target='urn:sedml:symbol:time')),
                            ],
                        ),
                        VisualizationDataField(
                            data_field=ChartDataField(
                                name='y',
                                shape=ChartDataFieldShape.array,
                                type=ChartDataFieldType.dynamic_simulation_result,
                            ),
                            simulation_results=[
                                SimulationResult(simulation=sims[0], variable=BiomodelVariable(
                                    id='p1_BE_task1',
                                    target="/sbml:sbml/sbml:model/sbml:listOfSpecies/sbml:species[@id='BE']")),
                                SimulationResult(simulation=sims[0], variable=BiomodelVariable(
                                    id='p1_BUD_task1',
                                    target="/sbml:sbml/sbml:model/sbml:listOfSpecies/sbml:species[@id='BUD']")),
                                # SimulationResult(simulation=sims[0], variable=BiomodelVariable(
                                #    id='p1_Clb2_task1',
                                #    target="/sbml:sbml/sbml:model/sbml:listOfSpecies/sbml:species[@id='Clb2']")),
                                SimulationResult(simulation=sims[0], variable=BiomodelVariable(
                                    id='p1_Cln_task1',
                                    target="/sbml:sbml/sbml:model/sbml:listOfSpecies/sbml:species[@id='Cln']")),
                                SimulationResult(simulation=sims[0], variable=BiomodelVariable(
                                    id='p1_SBF_a_task1',
                                    target="/sbml:sbml/sbml:model/sbml:listOfSpecies/sbml:species[@id='SBF_a']")),
                                SimulationResult(simulation=sims[0], variable=BiomodelVariable(
                                    id='p1_Sic1_task1',
                                    target="/sbml:sbml/sbml:model/sbml:listOfSpecies/sbml:species[@id='Sic1']")),
                            ],
                        ),
                    ],
                ),
            ],
        )
        self.assertEqual(viz, expected)

    def test_read_visualizations_with_log_axis(self):
        filename = 'tests/fixtures/BIOMD0000000297-with-log-axis.sedml'
        _, viz = read_simulation(filename, BiomodelFormat.sbml, SimulationFormat.sedml)
        self.assertEqual(viz.layout[0].chart.id, 'line-logX-logY')

    def test_read_visualizations_with_consistent_x_axes(self):
        filename = 'tests/fixtures/BIOMD0000000739.sedml'
        read_simulation(filename, BiomodelFormat.sbml, SimulationFormat.sedml)

    def test_read_visualizations_with_inconsistent_x_axes(self):
        filename = 'tests/fixtures/BIOMD0000000297-with-invalid-x-axis.sedml'
        with self.assertWarnsRegex(SimulationIoWarning, 'Curves must have the same X axis'):
            read_simulation(filename, BiomodelFormat.sbml, SimulationFormat.sedml)

    def test_read_visualizations_with_inconsistent_y_axes(self):
        filename = 'tests/fixtures/BIOMD0000000297-with-invalid-y-axis.sedml'
        with self.assertWarnsRegex(SimulationIoWarning, 'Curves must have the same Y axis'):
            read_simulation(filename, BiomodelFormat.sbml, SimulationFormat.sedml)
