"""MAD defaults, independent of Qt and device discovery.

Retains BAAS's per-profile config/event files, replacing its game-specific
defaults from commit 1110e88df5955df277737ea9717869b9ca88362b.
"""
from core.tasks import TASKS
from core.routine_catalog import default_routine

SCHEMA_VERSION = 5


def default_config(profile_id: str = "default") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "profile_id": profile_id,
        "display_name": "MAD 默认配置",
        "game": {
            "game_id": "mad", "channel": "onestore", "language": "zh-cn",
            "package": "com.wemadeconnect.aos.makedrama.onestore",
            "activity": "com.hive.HiveUnityPlayerActivity",
        },
        "device": {
            "emulator": "mumu",
            "mumu_path": "",
            "instance_id": 0,
            "adb_path": "",
            "screenshot_method": "adb", "control_method": "adb",
            "reference_size": [1920, 1080],
        },
        "runtime": {"screenshot_interval": 0.3},
        "routine": default_routine(),
        "unfinished_tasks": {}, "last_refresh_config_time": 0,
        "scheduling": {"timezone": "Asia/Hong_Kong",
                       "reset": {"enabled": True, "server_timezone": "Asia/Hong_Kong", "reset_at": "04:00"}},
    }


def default_events() -> list:
    return [{"func_name":key,"event_name":spec.title,"enabled":spec.default_enabled,
             "priority":index,"next_tick":0,"interval":86400,"daily_reset":[],
             "pre_task":[],"post_task":[],"disabled_time_range":[]}
            for index,(key,spec) in enumerate(TASKS.items())]


def default_app_settings() -> dict:
    return {"schema_version": SCHEMA_VERSION, "revision": 0,
            "ui": {"theme": "system"}}
