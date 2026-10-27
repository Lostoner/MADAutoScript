"""BAAS ConfigSet get/set/dynamic_update, adapted to MAD's existing JSON keys."""
from copy import deepcopy
from .repository import ProfileRepository

class ConfigSet:
    def __init__(self,config_dir):
        self.repository=config_dir if isinstance(config_dir,ProfileRepository) else ProfileRepository(config_dir)
        self.config_dir=str(self.repository.profile_dir)
        self.inject_comp_list=[]
        self.inject_config_list=[]
        self.config=self.repository.load_config()
    def get(self,key,default=None):
        self.config=self.repository.load_config()
        return deepcopy(self.config.get(key,default))
    def has(self,key): return key in self.repository.load_config()
    def set(self,key,value):
        self.config=self.repository.patch_config({key:value})
        self.dynamic_update(key)
    update=set
    def dynamic_update(self,key):
        if key in self.inject_config_list:
            for component in self.inject_comp_list: component.config_updated(key)
    def __getitem__(self,key): return self.get(key)
