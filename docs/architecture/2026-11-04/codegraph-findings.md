# CodeGraph 查询摘录

工具 1.6.2。在同日冻结的 source 快照（含未提交代码）上运行。以下是五次查询返回的流、动态边界及影响范围，保留工具原话。工具启发式识别的“caller”数量及边类型不等于实机调用次数；Qt 信号与任务注册表按绑定代码另行核对。

### orchestrate

**Flow (call path among the symbols you queried)**

1. thread_starter (core/Mad_thread.py:112)
   ↓ calls (when self.solve('restart'))
2. prepare_pass (core/Mad_thread.py:126)
   ↓ calls (when !continuous)
3. eligible (core/scheduler.py:44)

> Full source for these symbols is below — the call flow among them, followed by their bodies.
**Exploration: Main.start MadThread.thread_starter MadThread.run_group Scheduler.eligible RoutineCheckpoint.finish_pass**

Found 47 symbols across 4 files.

**Blast radius — what depends on these (update/verify before editing)**

- `start` (main.py:27) — 1 caller in `main.py`; no tests found within 3 caller hops
- `thread_starter` (core/Mad_thread.py:112) — 4 callers in `core/Mad_thread.py`; tests: `tests/test_ui_workspace.py`, `tests/test_daily_refresh.py`, `tests/test_instance_execution.py`
- `run_group` (core/Mad_thread.py:185) — 1 caller in `core/Mad_thread.py`; tested via callers: `tests/test_ui_workspace.py`, `tests/test_daily_refresh.py` +1
- `eligible` (core/scheduler.py:44) — 2 callers in `core/Mad_thread.py`, `core/scheduler.py`; tested via callers: `tests/test_ui_workspace.py`, `tests/test_daily_refresh.py` +1
- `finish_pass` (core/routine_checkpoint.py:36) — 1 caller in `core/Mad_thread.py`; tested via callers: `tests/test_ui_workspace.py`, `tests/test_daily_refresh.py` +1

### ui_flow

**Dynamic boundaries (the static path ends at runtime dispatch)**

- `save_changes` (gui/fragments/switch.py:104) — string-keyed dispatch (runtime key): `self.cancel_changes(); self.feedback.setText('已保存；下次调度读取新值。'); self.saved.emit(saved)`

> These sites choose their call target at runtime (registry / bus / reflection) — the site shown IS where the flow continues. To follow it, run codegraph_explore or codegraph_node on a candidate; source for the sites above is included below.

> Full source for these symbols is below — the call flow among them, followed by their bodies.
**Exploration: Window._start Window._on_runtime_event RoutineFragment.save_changes SwitchFragment.save_changes Main.start**

Found 62 symbols across 4 files.

**Blast radius — what depends on these (update/verify before editing)**

- `_start` (window.py:124) — 1 caller in `window.py`; no tests found within 3 caller hops
- `_on_runtime_event` (window.py:152) — 4 callers in `window.py`; tests: `tests/test_ui_workspace.py`
- `save_changes` (gui/fragments/routine.py:539) — 1 caller in `gui/fragments/routine.py`; no tests found within 3 caller hops
- `save_changes` (gui/fragments/switch.py:90) — 1 caller in `gui/fragments/switch.py`; no tests found within 3 caller hops
- `start` (main.py:27) — 1 caller in `main.py`; no tests found within 3 caller hops

### dispatch

**Flow (call path among the symbols you queried)**

1. open_page (core/Mad_thread.py:316)
   ↓ calls
2. open_page (module/restart.py:24)
   ↓ calls (when !self.match(name))
3. co_detect (core/picture.py:9)

**Dynamic boundaries (the static path ends at runtime dispatch)**

- `solve` (core/Mad_thread.py:221) — computed member call: `try: return self.func_dict[activity](self)`

> These sites choose their call target at runtime (registry / bus / reflection) — the site shown IS where the flow continues. To follow it, run codegraph_explore or codegraph_node on a candidate; source for the sites above is included below.

> Full source for these symbols is below — the call flow among them, followed by their bodies.
**Exploration: MadThread.solve function_table normal_sweep.implement MadThread.open_page FEATURES co_detect**

Found 44 symbols across 4 files.

**Blast radius — what depends on these (update/verify before editing)**

- `solve` (core/Mad_thread.py:217) — 3 callers in `core/Mad_thread.py`; tests: `tests/test_daily_refresh.py`
- `implement` (module/normal_sweep.py:19) — 1 caller in `core/tasks.py`; tested via callers: `tests/test_daily_refresh.py`, `tests/test_instance_execution.py` +1
- `co_detect` (core/picture.py:9) — 36 callers in `module/pass_rewards.py`, `module/restart.py`, `module/stamina_claim.py`, `module/gold_shop.py` +8 more; tested via callers: `tests/test_shop_and_picker.py`, `tests/test_stage_search.py` +3
- `open_page` (module/restart.py:24) — 8 callers in `module/gold_shop.py`, `module/mail.py`, `module/daily_rewards.py`, `module/mall.py` +4 more; tested via callers: `tests/test_shop_and_picker.py`

### device

**Flow (call path among the symbols you queried)**

1. run_plans (module/sweep_utils.py:135)
   ↓ calls (when plans && select_stage(self,task,stage_id) && self.template('m4_sweep_button') && not actual && batch.stage_limited)
2. to_main_page (module/restart.py:13)
   ↓ calls
3. co_detect (core/picture.py:9)

> Full source for these symbols is below — the call flow among them, followed by their bodies.
**Exploration: MadThread.connect Connection Screenshot co_detect BaasOcrClient start_sweep run_plans function_table**

Found 52 symbols across 5 files.

**Blast radius — what depends on these (update/verify before editing)**

- `connect` (core/Mad_thread.py:98) — 1 caller in `core/Mad_thread.py`; tested via callers: `tests/test_ui_workspace.py`, `tests/test_daily_refresh.py` +1
- `start_sweep` (module/sweep_utils.py:102) — 1 caller in `module/sweep_utils.py`; tested via callers: `tests/test_release_core.py`, `tests/test_sweep_boundaries.py`
- `run_plans` (module/sweep_utils.py:135) — 6 callers in `module/academy_sweep.py`, `module/normal_sweep.py`; tests: `tests/test_release_core.py`, `tests/test_sweep_boundaries.py`
- `co_detect` (core/picture.py:9) — 36 callers in `module/pass_rewards.py`, `module/restart.py`, `module/stamina_claim.py`, `module/gold_shop.py` +8 more; tested via callers: `tests/test_shop_and_picker.py`, `tests/test_stage_search.py` +3
- `function_table` (core/tasks.py:29) — 2 callers in `core/Mad_thread.py`; tested via callers: `tests/test_daily_refresh.py`, `tests/test_instance_execution.py` +1

### storage

**Exploration: ProfileRepository.save_routine_instances complete_sweep reset_progress Scheduler.systole**

Found 68 symbols across 5 files.

**Blast radius — what depends on these (update/verify before editing)**

- `systole` (core/scheduler.py:87) — 2 callers in `core/Mad_thread.py`; tests: `tests/test_daily_refresh.py`
- `ProfileRepository` (core/config/repository.py:96) — 22 callers in `core/Mad_thread.py`, `core/config/__init__.py`, `core/config/config_set.py`, `core/scheduler.py` +1 more; tests: `tests/test_daily_refresh.py`, `tests/test_instance_execution.py`, `tests/test_instance_storage.py`, `tests/test_release_core.py` +1
