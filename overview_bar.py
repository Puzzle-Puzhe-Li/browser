"""进度条上方的窄色条：显示全程动作类型分段 + 当前位置。点击/拖动可跳转。"""
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

import config
from signal_panel import load_colors


class OverviewBar(QtWidgets.QWidget):
    def __init__(self, model, clock, height=8, side_margin=6, parent=None):
        super().__init__(parent)
        self.model, self.clock = model, clock
        self.margin = side_margin            # 与滑条凹槽对齐（滑块半宽）
        self.setFixedHeight(height)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        raw = load_colors(config.INVOLVEMENT_CMAP_PATH)
        self.colors = {k.lower(): v for k, v in raw.items()}
        model.changed.connect(self.update)
        clock.timeChanged.connect(lambda _: self.update())

    def _color(self, name):
        return QtGui.QColor(*self.colors.get(name.lower(), config.INVOLVEMENT_DEFAULT_COLOR))

    def _x(self, t):
        w = max(self.width() - 2 * self.margin, 1)
        return self.margin + w * t / max(self.clock.duration, 1e-9)

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(235, 235, 235))
        s, en, labels = self.model.arrays()
        for a, b, l in zip(s, en, labels):
            x0, x1 = self._x(a), self._x(b)
            p.fillRect(QtCore.QRectF(x0, 0, max(x1 - x0, 1.0), self.height()), self._color(l))
        x = self._x(self.clock.time)                 # 当前位置
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 1.5))
        p.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, self.height()))

    def _seek(self, ev):
        w = max(self.width() - 2 * self.margin, 1)
        f = (ev.position().x() - self.margin) / w
        self.clock.seek(min(max(f, 0.0), 1.0) * self.clock.duration)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.MouseButton.LeftButton:
            self._seek(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._seek(e)