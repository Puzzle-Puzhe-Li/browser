"""跨面板的时间段框选：暂停时在右侧任意面板按住左键拖动。"""
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets


class SelectionHost(QtWidgets.QWidget):
    """右侧面板的容器，上面盖一层透明的 overlay 用来画选区。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.overlay = None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.overlay is not None:
            self.overlay.setGeometry(self.rect())


class SelectionOverlay(QtWidgets.QWidget):
    def __init__(self, host, ref_panel, axis_zero):
        super().__init__(host)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.ref = ref_panel
        self.axis_zero = float(axis_zero)
        self.sel = None                         # (t_a, t_b)，EEG 时间
        host.overlay = self
        self.setGeometry(host.rect())
        self.raise_()

    def set_selection(self, a, b=None):
        self.sel = None if a is None else (min(a, b), max(a, b))
        self.update()

    def _x(self, t):
        pw = self.ref.plot
        vb = pw.getPlotItem().vb
        sp = vb.mapViewToScene(QtCore.QPointF(t - self.axis_zero, 0.0))
        vp = pw.mapFromScene(sp)
        return self.mapFromGlobal(pw.viewport().mapToGlobal(vp)).x()

    def paintEvent(self, e):
        if self.sel is None:
            return
        x0, x1 = self._x(self.sel[0]), self._x(self.sel[1])
        p = QtGui.QPainter(self)
        p.fillRect(QtCore.QRect(x0, 0, max(x1 - x0, 1), self.height()),
                   QtGui.QColor(30, 144, 255, 55))
        p.setPen(QtGui.QPen(QtGui.QColor(30, 144, 255), 1))
        p.drawLine(x0, 0, x0, self.height())
        p.drawLine(x1, 0, x1, self.height())


class SelectionController(QtCore.QObject):
    selectionMade = QtCore.Signal(float, float, QtCore.QPoint)   # 起, 止 (EEG 时间), 鼠标全局位置

    def __init__(self, panels, ref_panel, overlay, clock, axis_zero, duration, parent=None):
        super().__init__(parent)
        self.ref, self.overlay, self.clock = ref_panel, overlay, clock
        self.axis_zero, self.duration = float(axis_zero), float(duration)
        self._views = {}
        for p in panels:
            vp = p.plot.viewport()
            self._views[vp] = p.plot
            vp.installEventFilter(self)
        self._anchor = None

    def _t_at(self, gp):
        """全局坐标 → EEG 时间（所有面板 x 轴一致，用参考面板换算，并限制在当前窗口内）。"""
        pw = self.ref.plot
        sp = pw.mapToScene(pw.viewport().mapFromGlobal(gp))
        vb = pw.getPlotItem().vb
        x = vb.mapSceneToView(sp).x()
        lo, hi = vb.viewRange()[0]
        x = min(max(x, lo), hi) + self.axis_zero
        return min(max(x, 0.0), self.duration)

    def eventFilter(self, obj, ev):
        pw = self._views.get(obj)
        if pw is None:
            return False
        ET = QtCore.QEvent.Type
        LB = QtCore.Qt.MouseButton.LeftButton
        t = ev.type()
        if t == ET.MouseButtonPress:
            self._anchor = None
            if ev.button() == LB and not self.clock.playing:
                vb = pw.getPlotItem().vb
                if vb.sceneBoundingRect().contains(pw.mapToScene(ev.position().toPoint())):
                    self._anchor = self._t_at(ev.globalPosition().toPoint())
                    self.overlay.set_selection(None)
        elif t == ET.MouseMove and self._anchor is not None:
            if ev.buttons() & LB:
                self.overlay.set_selection(self._anchor, self._t_at(ev.globalPosition().toPoint()))
        elif t == ET.MouseButtonRelease and ev.button() == LB and self._anchor is not None:
            gp = ev.globalPosition().toPoint()
            a, b = sorted((self._anchor, self._t_at(gp)))
            self._anchor = None
            if b - a < 0.05:                      # 只是点击，不算框选
                self.overlay.set_selection(None)
            else:
                self.overlay.set_selection(a, b)
                self.selectionMade.emit(a, b, gp)
        return False