"""MAD application lifecycle, BAAS worker and Qt bootstrap."""
from pathlib import Path
import argparse,json,sys,threading,traceback
from importlib.metadata import version,PackageNotFoundError
from core.paths import REPO_ROOT
from core.config import ProfileRepository
from core.tasks import TASKS

APP_VERSION='0.7.5'
UPSTREAM_COMMIT='1110e88df5955df277737ea9717869b9ca88362b'

class Main:
    """One OCR service per application, shared across worker runs."""
    def __init__(self,repository,emit=None):
        self.repository=repository
        self.emit=emit
        self.ocr_client=None
        self.worker=None
        self.lock=threading.Lock()
    def get_ocr(self,guard):
        from core.ocr.baas_ocr_client.Client import BaasOcrClient
        with self.lock:
            if self.ocr_client is None: self.ocr_client=BaasOcrClient(guard)
            self.ocr_client.guard=guard
            self.ocr_client.start_server()
            return self.ocr_client
    def start(self,continuous=False,task_ids=None,new_round=False):
        from core.Mad_thread import MadThread
        if self.worker and self.worker.is_running: return False
        self.worker=MadThread(self.repository,self.emit,self)
        return self.worker.start_tasks(continuous,task_ids,new_round)
    def close(self):
        if self.worker and self.worker.is_running:
            self.worker.request_stop()
            self.worker.join()
        if self.ocr_client: self.ocr_client.stop_server(); self.ocr_client=None

def repository(root): return ProfileRepository(Path(root)/'config/default')

def diagnostics(root):
    repo=repository(root)
    config=repo.load_config()
    dependencies={}
    for name in ('PyQt5','PyQt-Fluent-Widgets','numpy','opencv-python','adbutils','requests','tzdata'):
        try: dependencies[name]=version(name)
        except PackageNotFoundError: dependencies[name]=None
    return {'version':APP_VERSION,'upstream_commit':UPSTREAM_COMMIT,'schema':config['schema_version'],
            'tasks':[{**e,'supported':TASKS[e['func_name']].supported} for e in repo.load_events()],
            'unfinished_tasks':config['unfinished_tasks'],'dependencies':dependencies,'reset':config['scheduling']['reset']}

def create_window(root):
    from gui.qt_bootstrap import configure_qt
    configure_qt()
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app=QApplication.instance() or QApplication(['MADAutoScript'])
    from gui.theme import ui_font
    app.setFont(ui_font())
    app.setApplicationName('MADAutoScript')
    app.setApplicationVersion(APP_VERSION)
    from window import Window
    return app,Window(repository(root))

def main(argv=None):
    parser=argparse.ArgumentParser(description='MADAutoScript')
    parser.add_argument('--data-dir',type=Path,default=REPO_ROOT)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--diagnose',action='store_true')
    mode.add_argument('--run-routine',action='store_true',help='Run enabled tasks once, resuming unfinished stages')
    mode.add_argument('--continuous',action='store_true',help='Run due tasks using the same worker')
    parser.add_argument('--new-round',action='store_true')
    parser.add_argument('--tasks',nargs='+',choices=[k for k,v in TASKS.items() if v.supported])
    args=parser.parse_args(argv)
    if (args.new_round or args.tasks) and not args.run_routine: parser.error('--tasks/--new-round 需与 --run-routine 一起使用')
    if sys.stdout and hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    root=args.data_dir.resolve()
    try:
        if args.diagnose:
            print(json.dumps(diagnostics(root),ensure_ascii=False,indent=2)); return 0
        if args.run_routine or args.continuous:
            runtime=Main(repository(root),lambda e:print(json.dumps(e,ensure_ascii=False),flush=True))
            try:
                runtime.start(args.continuous,args.tasks,args.new_round)
                while not runtime.worker.join(.25): pass
                return 0 if runtime.worker.state in ('succeeded','stopped') else 2
            except KeyboardInterrupt: return 130
            finally: runtime.close()
        app,window=create_window(root)
        from PyQt5.QtCore import QLockFile
        from PyQt5.QtWidgets import QMessageBox
        (root/'state').mkdir(parents=True,exist_ok=True)
        lock=QLockFile(str(root/'state/MADAutoScript-ui.lock'))
        if not lock.tryLock(0):
            QMessageBox.information(None,'MADAutoScript','此数据目录的窗口已经打开。')
            window.close(); return 2
        try:
            window.show()
            return app.exec_()
        finally: window.runtime.close(); lock.unlock()
    except Exception as exc:
        detail=traceback.format_exc()
        (root/'state').mkdir(parents=True,exist_ok=True)
        (root/'state/startup-error.log').write_text(detail,'utf-8')
        if sys.stderr: print(detail,file=sys.stderr)
        if not (args.diagnose or args.run_routine or args.continuous):
            from gui.qt_bootstrap import configure_qt
            configure_qt()
            from PyQt5.QtWidgets import QApplication,QMessageBox
            notice=QApplication.instance() or QApplication(['MADAutoScript'])
            QMessageBox.critical(None,'MADAutoScript 启动失败',str(exc)+'\n详情：state/startup-error.log')
        return 2

if __name__=='__main__': raise SystemExit(main())
