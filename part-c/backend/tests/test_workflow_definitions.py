import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('workflow_validation',ROOT/'scripts/validate_workflows.py')
validation=importlib.util.module_from_spec(spec);spec.loader.exec_module(validation)


class WorkflowGraphTests(unittest.TestCase):
    def test_generated_state_names_and_branch_references_are_valid(self):
        for filename in ('sf1-incident.asl.json','sf3-notifications.asl.json'):
            validation.check_graph(json.loads((ROOT/'infra/part-c'/filename).read_text()))

    def test_duplicate_names_in_different_parallel_branches_are_rejected(self):
        branch={'StartAt':'Run','States':{'Run':{'Type':'Succeed'}}}
        with self.assertRaisesRegex(ValueError,'duplicado'):
            validation.check_graph({'StartAt':'Parallel','States':{'Parallel':{'Type':'Parallel','Branches':[branch,branch],'End':True}}})

    def test_a_branch_cannot_jump_into_its_parent(self):
        with self.assertRaisesRegex(ValueError,'ámbito'):
            validation.check_graph({'StartAt':'Parent','States':{'Parent':{'Type':'Parallel','Branches':[{'StartAt':'Child','States':{'Child':{'Type':'Pass','Next':'Parent'}}}],'End':True}}})


if __name__=='__main__':unittest.main()
