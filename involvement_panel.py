"""动作类型色条面板：把 Resting / Partial-body / Whole-body 画成一条彩色横条，播放头固定在正中。"""
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtGui, QtWidgets

import config
from signal_panel import load_colors


class InvolvementPanel(QtWidgets.QWidget):
    def __init__(self, starts, ends, labels, clock, axis_zero=0.0, parent=None):
        """starts/ends: EEG 时间（秒）；labels: 与之等长的类别名。"""
        super().__init__(parent)
        self.clock = clock
        self.axis_zero = float(axis_zero)
        self.half = config.WINDOW_SEC / 2.0

        raw = load_colors(config.INVOLVEMENT_CMAP_PATH)
        self.colors = {k.lower(): v for k, v in raw.items()}

        def col(name):
            return self.colors.get(name.lower(), config.INVOLVEMENT_DEFAULT_COLOR)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 图例（小字，放在色条上方）
        legend = "&nbsp;&nbsp;".join(
            f"<span style='color:rgb{col(n)}'>■</span> {n}"
            for n in config.INVOLVEMENT_ORDER)
        self.legend = QtWidgets.QLabel(legend)
        self.legend.setStyleSheet("font-size: 9px;")
        self.legend.setContentsMargins(config.AXIS_WIDTH, 0, 0, 0)
        lay.addWidget(self.legend)

        self.plot = pg.PlotWidget()
        lay.addWidget(self.plot, 1)

        pi = self.plot.getPlotItem()
        pi.setMouseEnabled(False, False)
        pi.setMenuEnabled(False)
        pi.hideButtons()
        pi.showGrid(x=True, y=False, alpha=0.25)
        pi.setYRange(0, 1, padding=0)

        left = pi.getAxis("left")
        left.setTicks([[]])                       # 不显示刻度
        left.setWidth(config.AXIS_WIDTH)          # 与其他面板对齐
        left.setStyle(showValues=False)
        bottom = pi.getAxis("bottom")
        bottom.setStyle(showValues=False)
        bottom.setHeight(6)

        if len(starts) > 0:
            x0 = np.asarray(starts, dtype=float) - self.axis_zero
            x1 = np.asarray(ends, dtype=float) - self.axis_zero
            brushes = [pg.mkBrush(col(l)) for l in labels]
            self.bars = pg.BarGraphItem(x0=x0, x1=x1, y0=0, y1=1,
                                        brushes=brushes, pen=pg.mkPen(None))
            pi.addItem(self.bars)

        self.playhead = pg.InfiniteLine(pos=0, angle=90, movable=False,
                                        pen=pg.mkPen("r", width=1.5))
        pi.addItem(self.playhead)

        clock.timeChanged.connect(self.update_view)
        self.update_view(clock.time)

    def update_view(self, t):
        tz = t - self.axis_zero
        self.plot.getPlotItem().setXRange(tz - self.half, tz + self.half, padding=0)
        self.playhead.setPos(tz)