"""入口：python main.py [session]      例如  python main.py A0"""
import sys

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets
import config
from clock import Clock
from eeg_loader import load_eeg, apply_channel_order
from signal_panel import SignalPanel, load_colors
from video_panel import VideoPanel
from tfr_panel import TFRPanel
from involvement_panel import InvolvementPanel

from motion_loader import (load_speed_csv, load_blink_times,
                           load_video_intercept, load_involvement_table)
from involvement_model import InvolvementModel, CLEAR_LABEL
from selection import SelectionHost, SelectionOverlay, SelectionController
from ica_colors import compute_ica_colors
from overview_bar import OverviewBar

class HelpDialog(QtWidgets.QDialog):
    ROWS = [
        ("键盘", None),
        ("空格", "播放 / 暂停"),
        ("← / →", "后退 / 前进 1 s"),
        ("PgUp / PgDn", "后退 / 前进 10 s"),
        ("Shift + ← / →", "上一段 / 下一段起点"),
        ("Ctrl + ← / →", "后退 / 前进 1 帧"),
        ("G", "时间定位（样本时间 / 视频时间，回车定位）"),
        ("小键盘 + / -", "放大 / 缩小纵轴比例尺"),
        ("* / /", "播放速度加 / 减"),
        ("Home / End", "跳到开头 / 结尾"),
        ("Ctrl + Z", "撤销动作类型修改"),
        ("H", "打开 / 关闭本帮助"),
        ("鼠标", None),
        ("双击脑电通道名", "切换 TFR 通道"),
        ("暂停时拖动框选", "选择时间段并设置动作类型"),
        ("右键动作类型栏", "撤销 / 导入 / 导出"),
        ("点击进度条或色条", "跳转到对应时间"),
        ("Alt + 左键点 ICA 通道名", "查看该 IC 的详细图"),
        ("点击 ICA 纵轴标签", "查看全部 IC 的 topomap"),        
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("快捷键与操作说明")
        html = ["<table cellspacing='4'>"]
        for k, v in self.ROWS:
            if v is None:
                html.append(f"<tr><td colspan='2'><b>{k}</b></td></tr>")
            else:
                html.append(
                    f"<tr><td><code>{k}</code>&nbsp;&nbsp;&nbsp;</td><td>{v}</td></tr>")
        html.append("</table>")
        lab = QtWidgets.QLabel("".join(html))
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(lab)

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key.Key_H:
            self.accept()
        else:
            super().keyPressEvent(e)


class GotoDialog(QtWidgets.QDialog):
    def __init__(self, t_sample, t_video, parent=None):
        super().__init__(parent)
        self.setWindowTitle("时间定位")
        self.kind = None
        self.value = 0.0
        self.sample_edit = QtWidgets.QLineEdit(f"{t_sample:.2f}")
        self.video_edit = QtWidgets.QLineEdit(self._fmt_mmss(t_video))
        form = QtWidgets.QFormLayout(self)
        form.addRow("样本时间 (s)", self.sample_edit)
        form.addRow("视频时间 (mm:ss)", self.video_edit)
        self.sample_edit.returnPressed.connect(
            lambda: self._submit("sample", self.sample_edit))
        self.video_edit.returnPressed.connect(
            lambda: self._submit("video", self.video_edit))
        self.sample_edit.selectAll()

    @staticmethod
    def _fmt_mmss(s):
        cs = int(round(abs(s) * 100))
        m, r = divmod(cs, 6000)
        return f"{'-' if s < 0 else ''}{m:02d}:{r / 100:05.2f}"

    @staticmethod
    def _parse_mmss(text):
        text = text.strip()
        neg = text.startswith("-")
        v = 0.0
        for p in text.lstrip("-").split(":"):
            v = v * 60 + float(p)
        return -v if neg else v

    def _submit(self, kind, edit):
        try:
            v = self._parse_mmss(edit.text()) if kind == "video" else float(
                edit.text().strip())
        except ValueError:
            return
        self.kind, self.value = kind, v
        self.accept()


class JumpSlider(QtWidgets.QSlider):
    """点击滑条任意位置直接跳转。"""

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.MouseButton.LeftButton:
            v = QtWidgets.QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), int(e.position().x()), self.width())
            self.setValue(v)
        super().mousePressEvent(e)


class MainWindow(QtWidgets.QWidget):

    def __init__(self, eeg, speed, session, ica=None):
        super().__init__()
        self.setWindowTitle(f"EEG Browser - session {session}")
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        QtWidgets.QApplication.instance().focusChanged.connect(lambda *_: self.setFocus() if not self.isActiveWindow()
                                                               or not isinstance(QtWidgets.QApplication.focusWidget(), QtWidgets.QLineEdit) else None)

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
            self.v0, self.v0_src = eeg.video_start + \
                config.VIDEO_OFFSET + self.video_intercept, "BDF 标注"
        else:
            self.v0, self.v0_src = self.t0 + config.VIDEO_OFFSET + \
                self.video_intercept, "sample_start 回退"

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
            zero_baseline=True, show_time_axis=False, axis_zero=self.t0,
            ylabel="Joint velocity (cm/s)", y_top_pad=config.SPEED_YPAD_TOP)

        self.eeg_panel = SignalPanel(
            eeg.data, eeg.names, eeg.fs, self.clock,
            colors=load_colors(config.CHANNEL_CMAP_PATH),
            t_offset=0.0,
            unit_per_spacing=config.UV_PER_SPACING, remove_mean=config.REMOVE_WINDOW_MEAN,
            zero_baseline=False, show_time_axis=False, axis_zero=self.t0,
            marks=self.blink_times, mark_color=config.BLINK_COLOR,
            mark_height=config.BLINK_TICK_HEIGHT,
            ylabel="EEG (μV)")

        self.ica_panel = None
        if ica is not None:
            if ica.sample_start is not None:
                ica_off = self.t0 - ica.sample_start
            else:
                print("[ICA] 未找到 sample_start 标注，按 t_offset=0 处理")
                ica_off = 0.0
            print(f"[ICA] {ica.data.shape[0]} 个成分, {ica.duration:.2f} s, "
                  f"sample_start = {ica.sample_start}, t_offset = {ica_off:.3f}")

            # ---- 按通道权重给成分上色 ----
            ica_colors, ica_labels = {}, {}
            fp = config.ica_fif_path(session)
            if fp.exists():
                try:
                    ica_colors, ica_labels = compute_ica_colors(
                        fp, ica.names, load_colors(config.CHANNEL_CMAP_PATH))
                except Exception as ex:
                    print(f"[ICA] 权重读取失败，不上色: {ex}")
            else:
                print(f"[ICA] 未找到 {fp}，不上色")

            disp_names = [ica_labels.get(n.strip(), n) for n in ica.names]
            self._ica_name_map = {d: n.strip() for d, n in zip(disp_names, ica.names)}            
            self.ica_panel = SignalPanel(
                ica.data, disp_names, ica.fs, self.clock,
                colors={ica_labels[k]: v for k, v in ica_colors.items()},
                t_offset=ica_off,
                unit_per_spacing=config.ICA_UV_PER_SPACING,
                remove_mean=config.REMOVE_WINDOW_MEAN,
                zero_baseline=False, show_time_axis=False, axis_zero=self.t0,
                ylabel="ICA")
            self.ica_panel.setMinimumSize(100, 50)

        inv_df = load_involvement_table(config.involvement_path(session))
        self.inv_model = InvolvementModel(inv_df, self.t0, parent=self)
        print(f"[动作类型] {len(self.inv_model.segs)} 段")
        self.inv_panel = InvolvementPanel(self.inv_model, self.clock,
                                          axis_zero=self.t0, session=session)
        if self.video_panel is not None:
            self.video_panel.inv_color_at = self._inv_color_at
            self.inv_model.changed.connect(self.video_panel.update)

        extra = None
        if ica is not None:
            extra = {f"{session}_ica": (ica.data, [n.strip() for n in ica.names], ica_off)}
        self.tfr_panel = TFRPanel(
            eeg.data, eeg.names, eeg.fs, self.clock,
            axis_zero=self.t0, cache_tag=session,
            channel=config.DEFAULT_TFR_CHANNEL,
            video_t0=self.v0 if self.video_panel is not None else None,
            extra=extra)

        for p in (self.speed_panel, self.eeg_panel, self.tfr_panel):
            p.setMinimumSize(100, 50)
        self.inv_panel.setMinimumSize(100, 28)      # 新增

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
        self.hint = QtWidgets.QLabel("H 快捷键与操作说明")

        self.overview = OverviewBar(self.inv_model, self.clock, height=4)
        slider_col = QtWidgets.QVBoxLayout()
        slider_col.setSpacing(1)
        slider_col.setContentsMargins(0, 0, 0, 0)
        slider_col.addWidget(self.overview)
        slider_col.addWidget(self.slider)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn)
        row.addLayout(slider_col, 1)
        for w in (self.time_label, self.speed_box, self.mean_chk):
            row.addWidget(w)
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(self.hint, 1)
        row2.addWidget(self.info)

        self.right_w = SelectionHost()
        right = QtWidgets.QVBoxLayout(self.right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.addWidget(self.speed_panel, config.STRETCH_SPEED)
        right.addWidget(self.eeg_panel, config.STRETCH_EEG)
        if self.ica_panel is not None:
            right.addWidget(self.ica_panel, config.STRETCH_ICA)
        right.addWidget(self.inv_panel, config.STRETCH_INV)
        right.addWidget(self.tfr_panel, config.STRETCH_TFR)

        top = QtWidgets.QHBoxLayout()
        if self.video_panel is not None:
            top.addWidget(self.video_panel, video_w)
            top.addWidget(self.right_w, W - video_w)
        else:
            top.addWidget(self.right_w, 1)

        # 框选
        self.overlay = SelectionOverlay(self.right_w, self.eeg_panel, self.t0)
        sel_panels = [self.speed_panel, self.eeg_panel,
                      self.inv_panel, self.tfr_panel]
        if self.ica_panel is not None:
            sel_panels.append(self.ica_panel)
        self.selector = SelectionController(
            tuple(sel_panels),
            self.eeg_panel, self.overlay, self.clock, self.t0, eeg.duration, parent=self)
        self.selector.selectionMade.connect(self._on_selection)
        self.clock.timeChanged.connect(
            lambda _: self.overlay.set_selection(None))
        self.clock.playingChanged.connect(
            lambda _: self.overlay.set_selection(None))
        self.inv_model.dirtyChanged.connect(self._update_title)
        self._session = session

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(top, 1)
        lay.addLayout(row)
        lay.addLayout(row2)

        self.btn.clicked.connect(self.clock.toggle)
        self.slider.valueChanged.connect(self._on_slider)
        self.speed_box.currentIndexChanged.connect(
            lambda: self.clock.set_speed(self.speed_box.currentData()))
        self.mean_chk.toggled.connect(self.eeg_panel.set_remove_mean)
        if self.ica_panel is not None:
            self.mean_chk.toggled.connect(self.ica_panel.set_remove_mean)
        self.clock.timeChanged.connect(self._on_time)
        self.clock.playingChanged.connect(
            lambda p: self.btn.setText("⏸ 暂停" if p else "▶ 播放"))
        self.eeg_panel.gainChanged.connect(self._refresh_info)
        self.speed_panel.gainChanged.connect(self._refresh_info)
        self.eeg_panel.channelDoubleClicked.connect(self.tfr_panel.set_channel)
        if self.ica_panel is not None:
            self.ica_panel.channelDoubleClicked.connect(self._ica_tfr)        
            self.ica_panel.channelAltClicked.connect(self._show_ic)
            self.ica_panel.axisLabelClicked.connect(self._show_topomap)

        self._on_time(0.0)
        self._refresh_info()
        self.setMinimumSize(640, 480)
        
    def _inv_color_at(self, t):
        for s, e, l, _ in self.inv_model.segs:
            if s <= t < e:
                return self.inv_panel.color_of(l)
        return None

    def _ica_tfr(self, disp_name):
        self.tfr_panel.set_channel(self._ica_name_map.get(disp_name, disp_name))  

    def _show_image(self, path, title):
        if not path.exists():
            QtWidgets.QMessageBox.warning(self, "找不到图片", str(path))
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _show_ic(self, disp_name):
        i = list(self._ica_name_map).index(disp_name)
        self._show_image(config.ica_img_dir(self._session) / f"IC{i:03d}.png", disp_name)

    def _show_topomap(self):
        self._show_image(config.ica_img_dir(self._session) / config.ICA_TOPOMAP_NAME, "ICA topomap")              

    def _goto(self):
        t = self.clock.time
        dlg = GotoDialog(t - self.t0, t - self.v0, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            base = self.t0 if dlg.kind == "sample" else self.v0
            self.clock.seek(base + dlg.value)
        self.setFocus()

    def _update_title(self, dirty=None):
        d = self.inv_model.dirty if dirty is None else dirty
        self.setWindowTitle(
            f"EEG Browser - session {self._session}" + (" *" if d else ""))

    def _on_selection(self, a, b, gp):
        # 延后到事件循环里弹菜单，避免在 eventFilter 内阻塞
        QtCore.QTimer.singleShot(0, lambda: self._show_assign_menu(a, b, gp))

    def _show_assign_menu(self, a, b, gp):
        m = QtWidgets.QMenu(self)
        title = m.addAction(
            f"{a - self.t0:.2f} – {b - self.t0:.2f} s（{b - a:.2f} s）设为：")
        title.setEnabled(False)
        m.addSeparator()
        for name in config.INVOLVEMENT_ORDER:
            pm = QtGui.QPixmap(12, 12)
            pm.fill(QtGui.QColor(*self.inv_panel.color_of(name)))
            act = m.addAction(QtGui.QIcon(pm), name)
            act.triggered.connect(
                lambda _=False, n=name: self.inv_model.assign(a, b, n))
        pm = QtGui.QPixmap(12, 12)
        pm.fill(QtGui.QColor(255, 255, 255))
        act = m.addAction(QtGui.QIcon(pm), CLEAR_LABEL)
        act.triggered.connect(
            lambda _=False: self.inv_model.assign(a, b, CLEAR_LABEL))            
        m.addSeparator()
        m.addAction("取消")
        m.exec(gp)
        self.overlay.set_selection(None)

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
            f"纵轴比例尺  脑电 {self.eeg_panel.unit_per_spacing:.0f} µV/行   "
            f"速度 {self.speed_panel.unit_per_spacing:.3g} cm·s^(-1)/行   "
            f"运动起点 {self.t0:.3f} s ({self.t0_src})")

    def _jump_segment(self, direction):
        """跳到下一段(direction>0)或上一段(direction<0)的起点。"""
        starts = sorted(s[0] for s in self.inv_model.segs)
        t, eps = self.clock.time, 1e-3
        if direction > 0:
            cand = [s for s in starts if s > t + eps]
            target = cand[0] if cand else None
        else:
            cand = [s for s in starts if s < t - eps]
            target = cand[-1] if cand else None
        if target is not None:
            self.clock.seek(target)

    def _change_play_speed(self, delta):
        i = self.speed_box.currentIndex() + delta
        i = min(max(i, 0), self.speed_box.count() - 1)
        self.speed_box.setCurrentIndex(i)      # 会触发 clock.set_speed

    def keyPressEvent(self, e):
        K = QtCore.Qt.Key
        M = QtCore.Qt.KeyboardModifier
        shift = (e.modifiers() & M.ShiftModifier) == M.ShiftModifier
        ctrl = (e.modifiers() & M.ControlModifier) == M.ControlModifier
        k = e.key()
        if k == K.Key_Space:
            self.clock.toggle()
        elif ctrl and k == K.Key_Z:
            self.inv_model.undo()
        elif k in (K.Key_Left, K.Key_Right):
            sign = -1 if k == K.Key_Left else 1
            if ctrl:
                self.clock.step(sign / self.frame_fps)      # ±1 帧
            elif shift:
                self._jump_segment(sign)                    # 上/下一段起点
            else:
                self.clock.step(sign * 1.0)                 # ±1 s
        elif k == K.Key_PageUp:
            self.clock.step(-10.0)
        elif k == K.Key_PageDown:
            self.clock.step(10.0)
        elif k in (K.Key_Plus, K.Key_Minus):
            more = (k == K.Key_Plus)                        # + 放大波形，- 缩小
            self.speed_panel.change_gain(more)
            self.eeg_panel.change_gain(more)
            if self.ica_panel is not None:
                self.ica_panel.change_gain(more)
        elif k == K.Key_Asterisk:
            self._change_play_speed(+1)
        elif k == K.Key_Slash:
            self._change_play_speed(-1)
        elif k == K.Key_Home:
            self.clock.seek(0)
        elif k == K.Key_End:
            self.clock.seek(self.clock.duration)
        elif k == K.Key_G:
            self._goto()
        elif k == K.Key_H:
            HelpDialog(self).exec()
            self.setFocus()
        elif k in (K.Key_Plus, K.Key_Equal, K.Key_Minus):
            more = (k in (K.Key_Plus, K.Key_Equal))
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        if self.inv_model.dirty:
            r = QtWidgets.QMessageBox.question(
                self, "有未导出的修改", "动作类型已修改但尚未导出，确定退出吗？")
            if r != QtWidgets.QMessageBox.StandardButton.Yes:
                e.ignore()
                return
        if self.video_panel is not None:
            self.video_panel.release()
        super().closeEvent(e)


def load_with_dialog(path, **kw):
    dlg = QtWidgets.QProgressDialog("正在加载…", "取消", 0, 100)
    dlg.setCancelButton(None)
    dlg.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setValue(0)

    def cb(frac, msg):
        dlg.setLabelText(msg)
        dlg.setValue(int(frac * 100))
        QtWidgets.QApplication.processEvents()

    eeg = load_eeg(path, progress=cb, **kw)
    dlg.close()
    return eeg


def main():
    pg.setConfigOptions(antialias=True, background="w", foreground="k",
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
    eeg = apply_channel_order(eeg, config.CHANNEL_ORDER_PATH)    
    speed = load_speed_csv(speed_path)
    ica = None
    ica_p = config.ica_path(session)
    if ica_p.exists():
        ica = load_with_dialog(ica_p, ch_prefix=config.ICA_PREFIX)
    else:
        print(f"[ICA] 未找到 {ica_p}")

    # 诊断信息（控制台）
    print(
        f"[EEG] {eeg.data.shape[0]} 通道, {eeg.duration:.2f} s, sample_start = {eeg.sample_start}")
    print(f"[EEG] 标注(前10条): {(eeg.annotations or [])[:10]}")
    print(f"[速度] {speed.data.shape[0]} 关节, {speed.fs:g} Hz, {speed.duration:.2f} s, "
          f"起点 {speed.t_start:g} s")

    win = MainWindow(eeg, speed, session, ica=ica)
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
