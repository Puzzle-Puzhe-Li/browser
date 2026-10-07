"""入口：python main.py [session]      例如  python main.py A0"""
import sys

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets
import config
from clock import Clock
from eeg_loader import load_eeg
from motion_loader import load_speed_csv, load_blink_times, load_video_intercept
from signal_panel import SignalPanel, load_colors
from video_panel import VideoPanel
from tfr_panel import TFRPanel          # 新增


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
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

        # 运动数据的 0 时刻在 EEG 时间轴上的位置
        if eeg.sample_start is not None:
            self.t0, self.t0_src = eeg.sample_start, "BDF 标注"
        else:
            self.t0, self.t0_src = config.EEG_OFFSET, "默认偏移"

        # 视频 0 秒在 EEG 时间轴上的位置
        self.video_intercept = (load_video_intercept(config.sync_model_path(session))
                                if config.USE_VIDEO_SYNC else 0.0)
        print(f"[同步] 视频截距 {self.video_intercept:.4f} s")
        if eeg.video_start is not None:
            self.v0, self.v0_src = eeg.video_start + config.VIDEO_OFFSET + self.video_intercept, "BDF 标注"
        else:
            self.v0, self.v0_src = self.t0 + config.VIDEO_OFFSET + self.video_intercept, "sample_start 回退"  

        # 眨眼时刻：eog_time 相对 video_start，换算为 EEG 时间
        vbase = eeg.video_start if eeg.video_start is not None else self.t0
        blink_rel = load_blink_times(config.blink_path(session))
        self.blink_times = blink_rel + vbase
        print(f"[眨眼] {len(blink_rel)} 次，基准 {vbase:.3f} s")

        self.clock = Clock(eeg.duration, fps=config.FPS, parent=self)

        # 视频（缺失或打不开时跳过，其余功能照常）
        self.video_panel = None
        vpath = config.video_path(session)
        if vpath.exists():
            try:
                self.video_panel = VideoPanel(
                    vpath, self.clock, t_offset=self.v0)
            except OSError as ex:
                print(f"[视频] {ex}")
        else:
            print(f"[视频] 未找到 {vpath}")
            
        # 单帧步长使用的帧率：优先用视频真实帧率，没有视频则用 config.FPS
        self.frame_fps = self.video_panel.fps if self.video_panel is not None else config.FPS            
        W, H, video_w = self._plan_geometry()
        self.resize(W, H)

        self.speed_panel = SignalPanel(
            speed.data, speed.names, speed.fs, self.clock,
            colors=load_colors(config.JOINT_CMAP_PATH),
            t_offset=self.t0 + speed.t_start,
            unit_per_spacing=config.SPEED_PER_SPACING, remove_mean=False,
            zero_baseline=True, show_time_axis=False, axis_zero=self.t0)
        self.eeg_panel = SignalPanel(
            eeg.data, eeg.names, eeg.fs, self.clock,
            colors=load_colors(config.CHANNEL_CMAP_PATH),
            t_offset=0.0,
            unit_per_spacing=config.UV_PER_SPACING, remove_mean=config.REMOVE_WINDOW_MEAN,
            zero_baseline=False, show_time_axis=False, axis_zero=self.t0,
            marks=self.blink_times, mark_color=config.BLINK_COLOR,
            mark_height=config.BLINK_TICK_HEIGHT)
        self.tfr_panel = TFRPanel(
            eeg.data, eeg.names, eeg.fs, self.clock,
            axis_zero=self.t0, cache_tag=session,
            channel=config.DEFAULT_TFR_CHANNEL)        
        
        for p in (self.speed_panel, self.eeg_panel, self.tfr_panel):
            p.setMinimumSize(100, 50)

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
            "空格 播放/暂停   ←/→ ±1 s   Shift+←/→ ±10 s   Ctrl+←/→ ±1 帧   "
            "↑/↓ 脑电+速度灵敏度   Home/End 首/尾   双击脑电通道名 切换TFR通道")

        row = QtWidgets.QHBoxLayout()
        for w in (self.btn, self.slider, self.time_label, self.speed_box, self.mean_chk):
            row.addWidget(w, 1 if w is self.slider else 0)
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(self.hint, 1)
        row2.addWidget(self.info)

        right = QtWidgets.QVBoxLayout()
        right.addWidget(self.speed_panel, config.STRETCH_SPEED)
        right.addWidget(self.eeg_panel, config.STRETCH_EEG)
        right.addWidget(self.tfr_panel, config.STRETCH_TFR)

        top = QtWidgets.QHBoxLayout()
        if self.video_panel is not None:
            top.addWidget(self.video_panel, video_w)          # 视频在左
            top.addLayout(right, W - video_w)
        else:
            top.addLayout(right, 1)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(top, 1)
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
        self.eeg_panel.channelDoubleClicked.connect(self.tfr_panel.set_channel)

        self._on_time(0.0)
        self._refresh_info()
        self.setMinimumSize(640, 480)

    def place_normal(self):
        """show 之前调用：把"正常（非最大化）状态"的大小和位置设成屏幕可用区域内居中。"""
        screen = self.screen() or QtGui.QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        W, H, _ = self._plan_geometry()
        self.resize(W, H)
        x = geo.left() + (geo.width() - W) // 2
        y = geo.top() + max((geo.height() - H) // 2 - 20, 0)   # 为标题栏留点空间
        self.move(x, y)

    def changeEvent(self, e):
        # 从最大化/最小化还原为正常状态时，用真实外框尺寸重新校正位置和大小
        if e.type() == QtCore.QEvent.Type.WindowStateChange:
            old = e.oldState()
            if (old & QtCore.Qt.WindowState.WindowMaximized or
                    old & QtCore.Qt.WindowState.WindowMinimized) \
                    and self.windowState() == QtCore.Qt.WindowState.WindowNoState:
                QtCore.QTimer.singleShot(0, self.fit_to_screen)
        super().changeEvent(e)        

    def fit_to_screen(self):
        if self.isMaximized() or self.isFullScreen():
            return
        screen = self.screen() or QtGui.QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        fg, g = self.frameGeometry(), self.geometry()
        frame_w, frame_h = fg.width() - g.width(), fg.height() - g.height()

        # 外框总尺寸不超过可用区域，并留出少量边距
        w = min(fg.width(), geo.width())
        h = min(fg.height(), geo.height())
        self.resize(w - frame_w, h - frame_h)

        fg = self.frameGeometry()
        x = min(max(geo.center().x() - fg.width() // 2, geo.left()),
                geo.right() - fg.width() + 1)
        y = min(max(geo.center().y() - fg.height() // 2, geo.top()),
                geo.bottom() - fg.height() + 1)
        self.move(x, y)

    def _plan_geometry(self):
        """返回 (W, H, video_w)：W/H 为客户区的目标尺寸（已扣除窗口外框），
        video_w 为视频列宽度（像素，同时用作 stretch 比例）。"""
        screen = self.screen() or QtGui.QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()

        # 窗口外框（标题栏+边框）厚度：show() 之前 frameGeometry 不可靠，给个保守估计
        frame_w, frame_h = 16, 48
        fg, g = self.frameGeometry(), self.geometry()
        if fg.height() > g.height():                 # 已有真实数据时直接用
            frame_w, frame_h = fg.width() - g.width(), fg.height() - g.height()

        W = int(geo.width() * config.WINDOW_SCREEN_FRAC[0]) - frame_w
        H = int(geo.height() * config.WINDOW_SCREEN_FRAC[1]) - frame_h
        W, H = max(W, 640), max(H, 480)

        video_w = 0
        if self.video_panel is not None:
            avail_h = H - 110                            # 扣除底部控制栏
            ideal = self.video_panel.aspect * avail_h
            video_w = int(min(max(ideal, config.VIDEO_MIN_FRAC * W),
                              config.VIDEO_MAX_FRAC * W))
        return W, H, video_w

    def closeEvent(self, e):
        if self.video_panel is not None:
            self.video_panel.release()
        super().closeEvent(e)

    def _on_slider(self, v):
        if not self._updating:
            self.clock.seek(v / 10.0)

    def _on_time(self, t):
        self._updating = True
        self.slider.setValue(int(t * 10))
        self._updating = False
        self.time_label.setText(
            f"时间 {t - self.t0:8.2f} s   |   EEG {t:8.2f} / {self.clock.duration:.2f} s")

    def _refresh_info(self, *_):
        self.info.setText(
            f"脑电 {self.eeg_panel.unit_per_spacing:.0f} µV/行   "
            f"速度 {self.speed_panel.unit_per_spacing:.3g} cm·s^(-1)/行   "
            f"运动起点 {self.t0:.3f} s ({self.t0_src})")

    def keyPressEvent(self, e):
        K = QtCore.Qt.Key
        M = QtCore.Qt.KeyboardModifier
        shift = (e.modifiers() & M.ShiftModifier) == M.ShiftModifier
        ctrl = (e.modifiers() & M.ControlModifier) == M.ControlModifier        
        k = e.key()
        if k == K.Key_Space:
            self.clock.toggle()
        elif k in (K.Key_Left, K.Key_Right):
            sign = -1 if k == K.Key_Left else 1
            if ctrl:
                step = 1.0 / self.frame_fps            # 1 帧
            elif shift:
                step = 10.0
            else:
                step = 1.0
            self.clock.step(sign * step)
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
    win.place_normal()                       # 先设好"还原后"的大小与位置
    if config.START_MAXIMIZED:
        win.showMaximized()
    else:
        win.show()
        QtCore.QTimer.singleShot(0, win.fit_to_screen)
    win.setFocus()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
