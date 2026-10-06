"""入口：python main.py [session]      例如  python main.py A0"""
import sys

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

import config
from clock import Clock
from eeg_loader import load_eeg
from motion_loader import load_speed_csv
from signal_panel import SignalPanel, load_colors


class JumpSlider(QtWidgets.QSlider):
    """点击滑条任意位置直接跳转。"""

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.MouseButton.LeftButton:
            v = QtWidgets.QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), int(e.position().x()), self.width())
            self.setValue(v)
        super().mousePressEvent(e)


class MainWindow(QtWidgets.QWidget):
    def __init__(self, eeg, speed, session):
        super().__init__()
        self.setWindowTitle(f"EEG Browser - session {session}")
        self.resize(1500, 950)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

        # 运动数据的 0 时刻在 EEG 时间轴上的位置
        if eeg.sample_start is not None:
            self.t0, self.t0_src = eeg.sample_start, "BDF 标注"
        else:
            self.t0, self.t0_src = config.EEG_OFFSET, "默认偏移"

        self.clock = Clock(eeg.duration, fps=config.FPS, parent=self)

        self.speed_panel = SignalPanel(
            speed.data, speed.names, speed.fs, self.clock,
            colors=load_colors(config.JOINT_CMAP_PATH),
            t_offset=self.t0 + speed.t_start,
            unit_per_spacing=config.SPEED_PER_SPACING, remove_mean=False,
            zero_baseline=True, show_time_axis=False)
        self.eeg_panel = SignalPanel(
            eeg.data, eeg.names, eeg.fs, self.clock,
            colors=load_colors(config.CHANNEL_CMAP_PATH),
            t_offset=0.0,
            unit_per_spacing=config.UV_PER_SPACING, remove_mean=config.REMOVE_WINDOW_MEAN,
            zero_baseline=False, show_time_axis=True)

        self._updating = False
        NF = QtCore.Qt.FocusPolicy.NoFocus     # 让方向键、空格始终由主窗口接收

        self.btn = QtWidgets.QPushButton("▶ 播放")
        self.btn.setFocusPolicy(NF)
        self.btn.setFixedWidth(80)

        self.slider = JumpSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(0, int(eeg.duration * 10))
        self.slider.setFocusPolicy(NF)

        self.time_label = QtWidgets.QLabel()
        self.time_label.setMinimumWidth(340)

        self.speed_box = QtWidgets.QComboBox()
        self.speed_box.setFocusPolicy(NF)
        for s in config.SPEEDS:
            self.speed_box.addItem(f"{s:g}x", s)
        self.speed_box.setCurrentIndex(config.SPEEDS.index(1))

        self.mean_chk = QtWidgets.QCheckBox("脑电去窗口均值")
        self.mean_chk.setChecked(config.REMOVE_WINDOW_MEAN)
        self.mean_chk.setFocusPolicy(NF)

        self.info = QtWidgets.QLabel()
        self.hint = QtWidgets.QLabel(
            "空格 播放/暂停   ←/→ ±1 s   Shift+←/→ ±10 s   "
            "↑/↓ 脑电+速度灵敏度   Home/End 首/尾")

        row = QtWidgets.QHBoxLayout()
        for w in (self.btn, self.slider, self.time_label, self.speed_box, self.mean_chk):
            row.addWidget(w, 1 if w is self.slider else 0)
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(self.hint, 1)
        row2.addWidget(self.info)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.speed_panel, config.STRETCH_SPEED)
        lay.addWidget(self.eeg_panel, config.STRETCH_EEG)
        lay.addLayout(row)
        lay.addLayout(row2)

        self.btn.clicked.connect(self.clock.toggle)
        self.slider.valueChanged.connect(self._on_slider)
        self.speed_box.currentIndexChanged.connect(
            lambda: self.clock.set_speed(self.speed_box.currentData()))
        self.mean_chk.toggled.connect(self.eeg_panel.set_remove_mean)
        self.clock.timeChanged.connect(self._on_time)
        self.clock.playingChanged.connect(
            lambda p: self.btn.setText("⏸ 暂停" if p else "▶ 播放"))
        self.eeg_panel.gainChanged.connect(self._refresh_info)
        self.speed_panel.gainChanged.connect(self._refresh_info)

        self._on_time(0.0)
        self._refresh_info()

    def _on_slider(self, v):
        if not self._updating:
            self.clock.seek(v / 10.0)

    def _on_time(self, t):
        self._updating = True
        self.slider.setValue(int(t * 10))
        self._updating = False
        self.time_label.setText(
            f"EEG {t:8.2f} / {self.clock.duration:.2f} s   |   运动 {t - self.t0:8.2f} s")

    def _refresh_info(self, *_):
        self.info.setText(
            f"脑电 {self.eeg_panel.unit_per_spacing:.0f} µV/行   "
            f"速度 {self.speed_panel.unit_per_spacing:.3g} cm·s^(-1)/行   "
            f"运动起点 {self.t0:.3f} s ({self.t0_src})")

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
        elif k in (K.Key_Up, K.Key_Down):
            self.speed_panel.change_gain(k == K.Key_Up)
            self.eeg_panel.change_gain(k == K.Key_Up)
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

    session = sys.argv[1] if len(sys.argv) > 1 else None
    if session is None:
        session, ok = QtWidgets.QInputDialog.getItem(
            None, "选择 session", "Session:", config.SESSIONS, 0, False)
        if not ok:
            return

    eeg_path, speed_path = config.eeg_path(session), config.speed_path(session)
    missing = [str(p) for p in (eeg_path, speed_path) if not p.exists()]
    if missing:
        QtWidgets.QMessageBox.critical(None, "找不到文件", "\n".join(missing))
        return

    eeg = load_with_dialog(eeg_path)
    speed = load_speed_csv(speed_path)

    # 诊断信息（控制台）
    print(f"[EEG] {eeg.data.shape[0]} 通道, {eeg.duration:.2f} s, sample_start = {eeg.sample_start}")
    print(f"[EEG] 标注(前10条): {(eeg.annotations or [])[:10]}")
    print(f"[速度] {speed.data.shape[0]} 关节, {speed.fs:g} Hz, {speed.duration:.2f} s, "
          f"起点 {speed.t_start:g} s")

    win = MainWindow(eeg, speed, session)
    win.show()
    win.setFocus()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
