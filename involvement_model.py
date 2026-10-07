"""可编辑的 Involvement 分段模型。内部时间统一用 EEG 时间（秒）。"""
import numpy as np
import pandas as pd
from pyqtgraph.Qt import QtCore

MERGE_EPS = 1e-6   # 两段首尾相差不超过该值（秒）即视为相连
REQUIRED_COLS = {"Onset", "Duration", "Annotation", "Involvement"}


class InvolvementModel(QtCore.QObject):
    changed = QtCore.Signal()          # 分段变化 → 面板重绘
    dirtyChanged = QtCore.Signal(bool)  # 未导出的修改状态

    def __init__(self, df, t0, parent=None):
        """df: 原始 involvement 表（可为 None）；t0: sample_start 在 EEG 时间轴上的位置。"""
        super().__init__(parent)
        self.t0 = float(t0)
        self.ss_onset = 0.0
        self.columns = ["Onset", "Duration", "Annotation", "Involvement"]
        self.others = pd.DataFrame(columns=self.columns)   # sample_start 等非分段行，原样保留
        self.segs = []                  # [(s, e, label, meta_dict)]
        self._undo = []
        self.dirty = False

        if df is None:
            return
        try:
            self._apply(self._parse(df))
        except ValueError as ex:
            print(f"[动作类型] {ex}")

    # ---- 解析 / 快照 ----
    def _parse(self, df):
        """把表解析成 (columns, others, segs, ss_onset)；格式不对抛 ValueError，不修改自身状态。"""
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        if not REQUIRED_COLS.issubset(df.columns):
            raise ValueError(f"缺少列 {REQUIRED_COLS - set(df.columns)}，现有列: {list(df.columns)}")
        columns = list(df.columns)

        ann = df["Annotation"].astype(str).str.strip().str.lower()
        is_ss = ann == "sample_start"
        ss_onset = float(pd.to_numeric(df.loc[is_ss, "Onset"], errors="coerce").iloc[0]) if is_ss.any() else 0.0
        if not np.isfinite(ss_onset):
            ss_onset = 0.0
        onset = pd.to_numeric(df["Onset"], errors="coerce")
        dur = pd.to_numeric(df["Duration"], errors="coerce")
        is_seg = ~is_ss & df["Involvement"].notna() & onset.notna() & dur.notna()

        others = df[~is_seg].copy()
        segs = []
        for idx in df.index[is_seg]:
            meta = df.loc[idx].drop(["Onset", "Duration", "Involvement"]).to_dict()
            s = self.t0 + float(onset[idx]) - ss_onset
            segs.append((s, s + float(dur[idx]), str(df.at[idx, "Involvement"]).strip(), meta))
        segs.sort(key=lambda x: x[0])
        return columns, others, segs, ss_onset

    def _apply(self, state):
        self.columns, self.others, self.segs, self.ss_onset = state

    def _snapshot(self):
        return (list(self.columns), self.others.copy(), list(self.segs), self.ss_onset)

    # ---- 读取 ----
    def arrays(self):
        s = np.array([x[0] for x in self.segs], dtype=float)
        e = np.array([x[1] for x in self.segs], dtype=float)
        return s, e, [x[2] for x in self.segs]

    @property
    def can_undo(self):
        return bool(self._undo)

    # ---- 编辑 ----
    def assign(self, t0, t1, label):
        """把 [t0, t1] 区间设为 label：与之重叠的旧分段被裁剪/切开，新区间覆盖其上；
        若新区间与前/后相邻且类型相同的分段首尾相连，则自动合并为一段。"""
        if t1 - t0 <= 0:
            return

        pre, post = [], []                 # 新区间左侧 / 右侧保留下来的分段
        for s, e, l, meta in self.segs:
            if e <= t0:
                pre.append((s, e, l, meta))
            elif s >= t1:
                post.append((s, e, l, meta))
            else:                          # 与新区间重叠：裁剪 / 切开
                if s < t0:
                    pre.append((s, t0, l, meta))
                if e > t1:
                    post.append((t1, e, l, meta))

        ns, ne = t0, t1
        merged_meta = None
        while pre and pre[-1][2] == label and abs(pre[-1][1] - ns) <= MERGE_EPS:
            s, e, l, meta = pre.pop()
            ns = min(ns, s)
            merged_meta = dict(meta)
        while post and post[0][2] == label and abs(post[0][0] - ne) <= MERGE_EPS:
            s, e, l, meta = post.pop(0)
            ne = max(ne, e)
            if merged_meta is None:
                merged_meta = dict(meta)

        if merged_meta is None:
            merged_meta = {"Annotation": "manual_edit"}
        else:
            merged_meta["Annotation"] = "manual_edit"

        out = pre + [(ns, ne, label, merged_meta)] + post
        out.sort(key=lambda x: x[0])
        if out == self.segs:
            return

        self._undo.append(self._snapshot())
        self.segs = out
        self._set_dirty(True)
        self.changed.emit()

    def undo(self):
        if self._undo:
            self._apply(self._undo.pop())
            self._set_dirty(True)
            self.changed.emit()

    def _set_dirty(self, v):
        if self.dirty != v:
            self.dirty = v
            self.dirtyChanged.emit(v)

    # ---- 导入 / 导出 ----
    def import_df(self, df):
        """用导入的表替换当前全部分段（可撤销）。格式不对抛 ValueError。"""
        state = self._parse(df)
        self._undo.append(self._snapshot())
        self._apply(state)
        self._set_dirty(False)             # 刚从文件读入，与磁盘一致
        self.changed.emit()
        return len(self.segs)

    def to_dataframe(self):
        rows = []
        for s, e, l, meta in self.segs:
            r = dict(meta)
            r["Onset"] = round(s - self.t0 + self.ss_onset, 6)
            r["Duration"] = round(e - s, 6)
            r["Involvement"] = l
            rows.append(r)
        seg_df = pd.DataFrame(rows, columns=self.columns)
        parts = [d for d in (self.others, seg_df) if len(d)]
        df = pd.concat(parts, ignore_index=True) if parts else seg_df
        df["_o"] = pd.to_numeric(df["Onset"], errors="coerce")
        df = df.sort_values("_o", kind="stable", na_position="last").drop(columns="_o")
        return df[self.columns]

    def export(self, path):
        # utf-8-sig：Excel 直接打开不乱码，pandas 用 encoding="utf-8-sig" 也能读回
        self.to_dataframe().to_csv(path, index=False, encoding="utf-8-sig")
        self._set_dirty(False)