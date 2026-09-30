"""脑电面板：10 s 窗口，播放头固定在正中，数据随主时钟滚动。"""
import json
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

import config

def load_channel_colors(path):
    """读取 {通道名: {"0": r, "1": g, "2": b}}（0~1）→ {通道名: (R, G, B)}（0~255）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for name, c in raw.items():
        out[name] = tuple(int(round(255 * min(max(float(c[k]), 0.0), 1.0))) for k in ("0", "1", "2"))
    return out

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

        cmap = load_channel_colors(config.CHANNEL_CMAP_PATH)
        self.curves = []                       # 每个通道一条曲线，各自上色
        for name in eeg.names:
            color = cmap.get(name.strip(), config.LINE_COLOR)
            c = pg.PlotCurveItem(pen=pg.mkPen(color, width=1))
            pi.addItem(c)
            self.curves.append(c)
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
            for c in self.curves:
                c.setData([], [])
            return

        seg = self.eeg.data[:, a:b]
        if self.remove_mean:
            seg = seg - seg.mean(axis=1, keepdims=True)

        y = seg * np.float32(1.0 / self.uv_per_spacing)
        y += self.offsets
        x = np.arange(a, b) / fs
        for i, c in enumerate(self.curves):
            c.setData(x, y[i], skipFiniteCheck=True)
