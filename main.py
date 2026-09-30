"""入口：python main.py [文件.bdf]"""
import sys

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

import config
from clock import Clock
from eeg_loader import load_eeg
from eeg_panel import EEGPanel


class JumpSlider(QtWidgets.QSlider):
    """点击滑条任意位置直接跳转。"""

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.MouseButton.LeftButton:
            v = QtWidgets.QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), int(e.position().x()), self.width())
            self.setValue(v)
        super().mousePressEvent(e)


class MainWindow(QtWidgets.QWidget):
    def __init__(self, eeg, title):
        super().__init__()
        self.setWindowTitle(f"EEG Browser - {title}")
        self.resize(1500, 900)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

        self.clock = Clock(eeg.duration, fps=config.FPS, parent=self)
        self.panel = EEGPanel(eeg, self.clock)
        self._updating = False
        NF = QtCore.Qt.FocusPolicy.NoFocus     # 让方向键、空格始终由主窗口接收

        self.btn = QtWidgets.QPushButton("▶ 播放")
        self.btn.setFocusPolicy(NF)
        self.btn.setFixedWidth(80)

        self.slider = JumpSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(0, int(eeg.duration * 10))
        self.slider.setFocusPolicy(NF)

        self.time_label = QtWidgets.QLabel()
        self.time_label.setMinimumWidth(330)

        self.speed_box = QtWidgets.QComboBox()
        self.speed_box.setFocusPolicy(NF)
        for s in config.SPEEDS:
            self.speed_box.addItem(f"{s:g}x", s)
        self.speed_box.setCurrentIndex(config.SPEEDS.index(1))

        self.mean_chk = QtWidgets.QCheckBox("去窗口均值")
        self.mean_chk.setChecked(config.REMOVE_WINDOW_MEAN)
        self.mean_chk.setFocusPolicy(NF)

        self.info = QtWidgets.QLabel()
        self.hint = QtWidgets.QLabel(
            "空格 播放/暂停   ←/→ ±1 s   Shift+←/→ ±10 s   ↑/↓ 调灵敏度   Home/End 跳到首/尾")

        row = QtWidgets.QHBoxLayout()
        for w in (self.btn, self.slider, self.time_label, self.speed_box, self.mean_chk):
            row.addWidget(w, 1 if w is self.slider else 0)
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(self.hint, 1)
        row2.addWidget(self.info)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.panel, 1)
        lay.addLayout(row)
        lay.addLayout(row2)

        self.btn.clicked.connect(self.clock.toggle)
        self.slider.valueChanged.connect(self._on_slider)
        self.speed_box.currentIndexChanged.connect(
            lambda: self.clock.set_speed(self.speed_box.currentData()))
        self.mean_chk.toggled.connect(self.panel.set_remove_mean)
        self.clock.timeChanged.connect(self._on_time)
        self.clock.playingChanged.connect(
            lambda p: self.btn.setText("⏸ 暂停" if p else "▶ 播放"))
        self.panel.gainChanged.connect(self._on_gain)

        self._on_time(0.0)
        self._on_gain(self.panel.uv_per_spacing)

    def _on_slider(self, v):
        if not self._updating:
            self.clock.seek(v / 10.0)

    def _on_time(self, t):
        self._updating = True
        self.slider.setValue(int(t * 10))
        self._updating = False
        self.time_label.setText(
            f"EEG {t:8.2f} / {self.clock.duration:.2f} s   |   视频 {t - config.EEG_OFFSET:8.2f} s")

    def _on_gain(self, uv):
        self.info.setText(f"灵敏度: {uv:.0f} µV / 通道间距   通道数: {self.panel.n_ch}")

    def keyPressEvent(self, e):
        K = QtCore.Qt.Key
        M = QtCore.Qt.KeyboardModifier
        shift = (e.modifiers() & M.ShiftModifier) == M.ShiftModifier
        k = e.key()
        if k == K.Key_Space:
            self.clock.toggle()
        elif k == K.Key_Left:
            self.clock.step(-10 if shift else -1)
        elif k == K.Key_Right:
            self.clock.step(10 if shift else 1)
        elif k == K.Key_Up:
            self.panel.change_gain(True)
        elif k == K.Key_Down:
            self.panel.change_gain(False)
        elif k == K.Key_Home:
            self.clock.seek(0)
        elif k == K.Key_End:
            self.clock.seek(self.clock.duration)
        else:
            super().keyPressEvent(e)


def load_with_dialog(path):
    dlg = QtWidgets.QProgressDialog("正在加载…", "取消", 0, 100)
    dlg.setCancelButton(None)
    dlg.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setValue(0)

    def cb(frac, msg):
        dlg.setLabelText(msg)
        dlg.setValue(int(frac * 100))
        QtWidgets.QApplication.processEvents()

    eeg = load_eeg(path, progress=cb)
    dlg.close()
    return eeg


def main():
    pg.setConfigOptions(antialias=False, background="w", foreground="k",
                        useOpenGL=config.USE_OPENGL)
    app = pg.mkQApp("EEG Browser")

    path = sys.argv[1] if len(sys.argv) > 1 else config.DEFAULT_BDF_PATH
    if not path:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            None, "选择 BDF / EDF 文件", "", "EEG (*.bdf *.edf)")
    if not path:
        return

    eeg = load_with_dialog(path)
    win = MainWindow(eeg, path)
    win.show()
    win.setFocus()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
