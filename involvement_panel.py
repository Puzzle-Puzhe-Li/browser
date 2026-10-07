"""动作类型色条面板：随 InvolvementModel 重绘；右键可撤销 / 导出。"""
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

import config
from signal_panel import load_colors


class InvolvementPanel(QtWidgets.QWidget):
    def __init__(self, model, clock, axis_zero=0.0, session="", parent=None):
        super().__init__(parent)
        self.model = model
        self.clock = clock
        self.session = session
        self.axis_zero = float(axis_zero)
        self.half = config.WINDOW_SEC / 2.0
        self.bars = None

        raw = load_colors(config.INVOLVEMENT_CMAP_PATH)
        self.colors = {k.lower(): v for k, v in raw.items()}

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        legend = "&nbsp;&nbsp;".join(
            f"<span style='color:rgb{self.color_of(n)}'>■</span> {n}"
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
        left.setTicks([[]])
        left.setWidth(config.AXIS_WIDTH)
        left.setStyle(showValues=False)
        bottom = pi.getAxis("bottom")
        bottom.setStyle(showValues=False)
        bottom.setHeight(6)

        self.playhead = pg.InfiniteLine(pos=0, angle=90, movable=False,
                                        pen=pg.mkPen("r", width=1.5))
        pi.addItem(self.playhead)

        self._rebuild()
        model.changed.connect(self._rebuild)
        self.plot.viewport().installEventFilter(self)      # 右键菜单
        clock.timeChanged.connect(self.update_view)
        self.update_view(clock.time)

    def color_of(self, name):
        return self.colors.get(name.lower(), config.INVOLVEMENT_DEFAULT_COLOR)

    def _rebuild(self):
        pi = self.plot.getPlotItem()
        if self.bars is not None:
            pi.removeItem(self.bars)
            self.bars = None
        s, e, labels = self.model.arrays()
        if len(s) == 0:
            return
        brushes = [pg.mkBrush(self.color_of(l)) for l in labels]
        self.bars = pg.BarGraphItem(x0=s - self.axis_zero, x1=e - self.axis_zero,
                                    y0=0, y1=1, brushes=brushes, pen=pg.mkPen(None))
        self.bars.setZValue(-1)                            # 播放头始终在上层
        pi.addItem(self.bars)

    def update_view(self, t):
        tz = t - self.axis_zero
        self.plot.getPlotItem().setXRange(tz - self.half, tz + self.half, padding=0)
        self.playhead.setPos(tz)

    # ---- 右键菜单 ----
    def eventFilter(self, obj, ev):
        if (obj is self.plot.viewport()
                and ev.type() == QtCore.QEvent.Type.MouseButtonRelease
                and ev.button() == QtCore.Qt.MouseButton.RightButton):
            self._context_menu(ev.globalPosition().toPoint())
            return True
        return super().eventFilter(obj, ev)

    def _context_menu(self, gp):
        m = QtWidgets.QMenu(self)
        a_undo = m.addAction("撤销上一次修改 (Ctrl+Z)")
        a_undo.setEnabled(self.model.can_undo)
        a_undo.triggered.connect(self.model.undo)
        a_exp = m.addAction(f"导出 involvement_{self.session}_edited.xlsx …")
        a_exp.triggered.connect(self.export_dialog)
        m.exec(gp)

    def export_dialog(self):
        default = config.involvement_path(self.session).parent / f"involvement_{self.session}_edited.xlsx"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出动作类型", str(default), "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            self.model.export(path)
        except Exception as ex:
            QtWidgets.QMessageBox.critical(self, "导出失败", str(ex))
            return
        QtWidgets.QMessageBox.information(self, "导出完成", f"已保存到：\n{path}")