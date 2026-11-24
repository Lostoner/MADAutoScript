"""HARD has its own plan and progress but shares the story screen and sweep controls."""
from module.sweep_utils import navigate_story, run_plans


def navigate(self,option):
    return navigate_story(self,option,'hard')


def implement(self):
    return run_plans(self,'mad.hard_sweep','normal_stage',navigate)
