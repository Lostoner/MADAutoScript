"""Portable defaults, MuMu paths and progress persistence without private fixtures."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from core.config.repository import ProfileRepository
from core.device.mumu_cli import find_adb
from core.Mad_thread import MadThread
from module import sweep_utils

class ReleaseCore(TestCase):
    def test_clean_defaults_and_adb_in_selected_installation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = ProfileRepository(root/'config/default')
            self.assertEqual(repo.load_config()['device']['mumu_path'], '')
            self.assertEqual(repo.load_config()['device']['adb_path'], '')
            adb = root/'MuMu/nx_device/12.0/shell/adb.exe'
            adb.parent.mkdir(parents=True)
            adb.touch()
            config = {'mumu_path': str(root/'MuMu/nx_main/mumu-cli.exe'), 'adb_path': ''}
            self.assertEqual(find_adb(config), adb)
            alternate = root/'custom-adb.exe'
            alternate.touch()
            config['adb_path'] = str(alternate)
            self.assertEqual(find_adb(config), alternate)

    def test_order_progress_and_stale_settings_save(self):
        with TemporaryDirectory() as temporary:
            repo = ProfileRepository(Path(temporary)/'config/default')
            config = repo.load_config()
            plans = [{'stage_id': 'normal:4-1', 'count': 2}, {'stage_id': 'normal:4-2', 'count': 3}]
            routine = deepcopy(config['routine'])
            routine['normal_sweep']['plans'] = plans
            before = repo.patch_config({'routine': routine})
            worker = MadThread(repo)
            worker.template = Mock(return_value=True)
            counts = []
            worker.to_main_page = Mock()
            with patch.object(sweep_utils, 'enter'), patch.object(sweep_utils, 'select_stage', return_value=True), patch.object(sweep_utils, 'return_to_list'), patch.object(sweep_utils, 'start_sweep', side_effect=lambda w, n: (counts.append(n) or True, n)):
                self.assertTrue(sweep_utils.run_plans(worker, 'mad.normal_sweep', 'normal_stage', Mock()))
            self.assertEqual(counts, [2, 3])
            worker.to_main_page.assert_not_called()
            stale = deepcopy(before)
            stale['display_name'] = 'Saved settings'
            repo.save_config(stale, base=before)
            reopened = ProfileRepository(repo.profile_dir).load_config()
            self.assertEqual(reopened['unfinished_tasks']['mad.normal_sweep'], [])
            self.assertEqual(reopened['routine']['normal_sweep']['plans'], plans)
