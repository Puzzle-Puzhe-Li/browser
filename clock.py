"""主时钟：唯一的时间来源，单位为秒（EEG 时间）。"""
import time
from pyqtgraph.Qt import QtCore


class Clock(QtCore.QObject):
    timeChanged = QtCore.Signal(float)
    playingChanged = QtCore.Signal(bool)

    def __init__(self, duration, fps=60, parent=None):
        super().__init__(parent)
        self._duration = float(duration)
        self._t = 0.0
        self._speed = 1.0
        self._playing = False
        self._wall0 = 0.0
        self._t0 = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.setTimerType(QtCore.Qt.TimerType.CoarseTimer)
        self._timer.setInterval(max(1, int(1000 / fps)))
        self._timer.timeout.connect(self._tick)

    # ---- 只读属性 ----
    @property
    def time(self):
        return self._t

    @property
    def duration(self):
        return self._duration

    @property
    def playing(self):
        return self._playing

    @property
    def speed(self):
        return self._speed

    # ---- 控制 ----
    def play(self):
        if self._playing:
            return
        if self._t >= self._duration - 1e-6:
            self._t = 0.0
        self._rebase()
        self._playing = True
        self._timer.start()
        self.playingChanged.emit(True)

    def pause(self):
        if not self._playing:
            return
        self._timer.stop()
        self._playing = False
        self.playingChanged.emit(False)

    def toggle(self):
        self.pause() if self._playing else self.play()

    def seek(self, t):
        self._t = min(max(float(t), 0.0), self._duration)
        self._rebase()
        self.timeChanged.emit(self._t)

    def step(self, dt):
        self.seek(self._t + dt)

    def set_speed(self, speed):
        self._rebase()
        self._speed = float(speed)

    # ---- 内部 ----
    def _rebase(self):
        self._wall0 = time.perf_counter()
        self._t0 = self._t

    def _tick(self):
        t = self._t0 + (time.perf_counter() - self._wall0) * self._speed
        if t >= self._duration:
            self._t = self._duration
            self.timeChanged.emit(self._t)
            self.pause()
        else:
            self._t = t
            self.timeChanged.emit(t)
