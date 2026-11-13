"""Remember confirmed steps of an interrupted pass, separate from stage counts."""
import json
from pathlib import Path
from core.runtime_state import atomic_json


class RoutineCheckpoint:
    def __init__(self, directory, continuous, selection, epoch):
        self.continuous = continuous
        mode = 'continuous' if continuous else ('selected' if selection else 'routine')
        self.path = Path(directory) / (mode + '-checkpoint.json')
        self.context = [sorted(selection or ()), epoch]
        saved = json.loads(self.path.read_text('utf-8')) if self.path.exists() else {}
        self.groups = saved.get('groups', {}) if saved.get('context') == self.context else {}
        self.material_context = saved.get('material_context') if saved.get('context') == self.context else None

    def group(self, root, tick):
        cycle = tick if self.continuous else None
        group = self.groups.get(root)
        if group is None or group['cycle'] != cycle:
            group = self.groups[root] = {'cycle': cycle, 'steps': [], 'next_time': 0, 'scheduled': False}
        return group

    def save(self):
        if self.groups or self.material_context:
            atomic_json(self.path, {'context': self.context, 'groups': self.groups,'material_context':self.material_context})
        else:
            self.path.unlink(missing_ok=True)

    def finish_group(self, root):
        if self.continuous:
            del self.groups[root]
        else:
            self.groups[root]['scheduled'] = True
        self.save()

    def finish_pass(self):
        self.groups.clear()
        self.material_context = None
        self.save()
