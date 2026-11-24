"""MAD normal stages; material observation also uses the checked navigation path."""
from module.sweep_utils import navigate_story, run_plans


def navigate(self,option,*,check_locked=False):
    return navigate_story(self,option,'normal',check_locked=check_locked)


def implement(self):
    return run_plans(self,'mad.normal_sweep','normal_stage',navigate)
