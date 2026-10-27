"""Flara entry for the shared academy-exchange sweep."""
from module.academy_sweep import implement as academy_sweep
def implement(self): return academy_sweep(self,'mad.flara_sweep','flara_stage')
