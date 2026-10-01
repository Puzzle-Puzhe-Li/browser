"""通用多通道曲线面板（脑电、速度共用）。

窗口 WINDOW_SEC 秒，播放头固定在正中，数据随主时钟滚动。
数据时间 = 主时钟时间 - t_offset（即数据的 0 时刻对应主时钟的哪一秒）。
"""
import json

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

import config


def load_colors(path):
    """读取 {名字: {"0": r, "1": g, "2": b}}（0~1）→ {名字: (R, G, B)}（0~255）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for name, c in raw.items():
        out[name] = tuple(int(round(255 * min(max(float(c[k]), 0.0), 1.0))) for k in ("0", "1", "2"))
    return out


class SignalPanel(QtWidgets.QWidget):
    gainChanged = QtCore.Signal(float)     # 当前灵敏度 (数据单位 / 通道间距)

    def __init__(self, data, names, fs, clock, colors=None, t_offset=0.0,
                 unit_per_spacing=100.0, remove_mean=False, zero_baseline=False,
                 show_time_axis=True, parent=None):
        super().__init__(parent)
        self.data = data
        self.names = names
        self.fs = float(fs)
        self.clock = clock
        self.t_offset = float(t_offset)
        self.unit_per_spacing = float(unit_per_spacing)
        self.remove_mean = remove_mean
        self.n_ch, self.n_samp = data.shape
        self.has_nan = bool(np.isnan(data).any())
        self.half = config.WINDOW_SEC / 2.0
        self.n_win = int(round(config.WINDOW_SEC * self.fs))
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
        pi.showGrid(x=True, y=zero_baseline, alpha=0.25)

        bottom = pi.getAxis("bottom")
        if show_time_axis:
            pi.setLabel("bottom", "EEG 时间 (s)")
        else:                                   # 保留网格线，只隐藏刻度数字
            bottom.setStyle(showValues=False)
            bottom.setHeight(6)

        ax = pi.getAxis("left")
        ax.setTicks([[(float(self.n_ch - 1 - i), n) for i, n in enumerate(names)]])
        ax.setWidth(config.AXIS_WIDTH)
        font = QtGui.QFont()
        font.setPointSize(5)
        ax.setStyle(tickFont=font)
        if zero_baseline:
            pi.setYRange(-0.6, self.n_ch + 0.6, padding=0)
        else:
            pi.setYRange(-1, self.n_ch, padding=0)

        colors = colors or {}
        self.curves = []                       # 每个通道一条曲线，各自上色
        for name in names:
            color = colors.get(name.strip(), config.LINE_COLOR)
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
        self.unit_per_spacing = self.unit_per_spacing / f if more_sensitive else self.unit_per_spacing * f
        self.gainChanged.emit(self.unit_per_spacing)
        self.update_view(self.clock.time)

    def set_remove_mean(self, on):
        self.remove_mean = bool(on)
        self.update_view(self.clock.time)

    # ---- 绘制 ----
    def update_view(self, t):
        td = t - self.t_offset                          # 数据自己的时间
        i0 = int(round((td - self.half) * self.fs))
        a = max(i0 - 1, 0)                              # 两端多取一个样本，避免边缘断线
        b = min(i0 + self.n_win + 1, self.n_samp)

        pi = self.plot.getPlotItem()
        pi.setXRange(t - self.half, t + self.half, padding=0)
        self.playhead.setPos(t)

        if b - a < 2:
            for c in self.curves:
                c.setData([], [])
            return

        seg = self.data[:, a:b]
        if self.remove_mean:
            m = np.nanmean(seg, axis=1, keepdims=True) if self.has_nan else seg.mean(axis=1, keepdims=True)
            seg = seg - m

        y = seg * np.float32(1.0 / self.unit_per_spacing)
        y += self.offsets
        x = np.arange(a, b) / self.fs + self.t_offset
        for i, c in enumerate(self.curves):
            if self.has_nan:
                c.setData(x, y[i], connect="finite")
            else:
                c.setData(x, y[i], skipFiniteCheck=True)