"""Offline installation smoke check: Qt, fresh profile, templates and OCR; no game input."""
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ocr', action='store_true', help='Also start the installed OCR server and recognize generated text')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    from main import APP_VERSION, create_window
    from core import position
    from types import SimpleNamespace
    from core.runtime_state import atomic_json
    with TemporaryDirectory(prefix='mad-install-') as temporary:
        root = Path(temporary)
        app, window = create_window(root)
        window.show()
        app.processEvents()
        config = window.repository.load_config()
        assert config['device']['mumu_path'] == ''
        assert config['device']['adb_path'] == ''
        assert window.homeInterface.routine_button.isEnabled()
        result = {'version': APP_VERSION, 'python': sys.executable, 'root': str(ROOT),
                  'qt_window': window.isVisible(), 'fresh_profile': True}
        position.init_image_data(SimpleNamespace(identifier=position.IDENTIFIER))
        result['templates'] = len(position.image_dic[position.IDENTIFIER])
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(args.output.with_suffix('.png')))
        window.close()
        app.processEvents()
        if args.ocr:
            import cv2
            import numpy as np
            from PyQt5.QtGui import QImage, QPainter, QFont, QFontMetrics
            from PyQt5.QtCore import Qt
            from core.device.runtime import RunControl
            from core.ocr.baas_ocr_client.Client import BaasOcrClient
            from install_ocr import verify_runtime
            verify_runtime(ROOT/'runtime/ocr')
            text = '自动化测试 12345'
            font = QFont('Microsoft YaHei UI', 28)
            bounds = QFontMetrics(font).boundingRect(text)
            image = QImage(bounds.width()+16, bounds.height()+16, QImage.Format_RGB32)
            image.fill(Qt.white)
            painter = QPainter(image)
            painter.setPen(Qt.black)
            painter.setRenderHint(QPainter.TextAntialiasing)
            painter.setFont(font)
            painter.drawText(8-bounds.left(), 8-bounds.top(), text)
            painter.end()
            image.save(str(root/'ocr.png'))
            if args.output: image.save(str(args.output.with_name(args.output.stem+'-ocr.png')))
            frame = cv2.imdecode(np.frombuffer((root/'ocr.png').read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            client = BaasOcrClient(RunControl())
            try:
                client.start_server()
                text = client.single_line(frame, 'zh-cn')['text']
                assert '自动化测试' in text and '12345' in text, text
                result['ocr'] = text
            finally:
                client.stop_server()
    if args.output: atomic_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
