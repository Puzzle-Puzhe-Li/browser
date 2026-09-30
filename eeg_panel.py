"""脑电面板：10 s 窗口，播放头固定在正中，数据随主时钟滚动。"""
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

import config


class EEGPanel(QtWidgets.QWidget):
    gainChanged = QtCore.Signal(float)     # 当前灵敏度 (µV / 通道间距)

    def __init__(self, eeg, clock, parent=None):
        super().__init__(parent)
        self.eeg = eeg
        self.clock = clock
        self.n_ch = eeg.data.shape[0]
        self.uv_per_spacing = config.UV_PER_SPACING
        self.remove_mean = config.REMOVE_WINDOW_MEAN
        self.half = config.WINDOW_SEC / 2.0
        self.n_win = int(round(config.WINDOW_SEC * eeg.fs))
        # 第 0 通道在最上方
        self.offsets = np.arange(self.n_ch - 1, -1, -1, dtype=np.float32)[:, None]

        self.plot = pg.PlotWidget()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.plot)

        pi = self.plot.getPlotItem()
        pi.setMouseEnabled(False, False)
        pi.setMenuEnabled(False)
        pi.hideButtons()
        pi.showGrid(x=True, y=False, alpha=0.25)
        pi.setLabel("bottom", "EEG 时间 (s)")

        ax = pi.getAxis("left")
        ax.setTicks([[(float(self.n_ch - 1 - i), n) for i, n in enumerate(eeg.names)]])
        ax.setWidth(55)
        font = QtGui.QFont()
        font.setPointSize(7)
        ax.setStyle(tickFont=font)
        pi.setYRange(-1, self.n_ch, padding=0)

        self.curve = pg.PlotCurveItem(pen=pg.mkPen(config.LINE_COLOR, width=1))
        pi.addItem(self.curve)
        self.playhead = pg.InfiniteLine(pos=0, angle=90, movable=False,
                                        pen=pg.mkPen("r", width=1.5))
        pi.addItem(self.playhead)

        clock.timeChanged.connect(self.update_view)
        self.update_view(clock.time)

    # ---- 对外接口 ----
    def change_gain(self, more_sensitive):
        f = config.GAIN_STEP
        self.uv_per_spacing = self.uv_per_spacing / f if more_sensitive else self.uv_per_spacing * f
        self.gainChanged.emit(self.uv_per_spacing)
        self.update_view(self.clock.time)

    def set_remove_mean(self, on):
        self.remove_mean = bool(on)
        self.update_view(self.clock.time)

    # ---- 绘制 ----
    def update_view(self, t):
        fs = self.eeg.fs
        i0 = int(round((t - self.half) * fs))
        a = max(i0, 0)
        b = min(i0 + self.n_win, self.eeg.data.shape[1])

        pi = self.plot.getPlotItem()
        pi.setXRange(t - self.half, t + self.half, padding=0)
        self.playhead.setPos(t)

        L = b - a
        if L < 2:
            self.curve.setData([], [])
            return

        seg = self.eeg.data[:, a:b]
        if self.remove_mean:
            seg = seg - seg.mean(axis=1, keepdims=True)

        # 所有通道拼成一条折线，通道之间用 NaN 断开，只需一次绘制调用
        y = np.empty((self.n_ch, L + 1), dtype=np.float32)
        np.multiply(seg, 1.0 / self.uv_per_spacing, out=y[:, :L])
        y[:, :L] += self.offsets
        y[:, L] = np.nan

        x = np.empty(L + 1, dtype=np.float64)
        x[:L] = np.arange(a, b) / fs
        x[L] = x[L - 1]
        xs = np.broadcast_to(x, (self.n_ch, L + 1)).ravel()

        self.curve.setData(xs, y.ravel(), connect="finite")
