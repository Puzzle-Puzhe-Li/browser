"""全局配置。需要调参数时只改这个文件。"""
from pathlib import Path

# ---- 数据位置 ----
DATA_ROOT = Path(r"F:\bmi_free_01\data")
SESSIONS = ["A0", "B1"]


def eeg_path(session):
    return DATA_ROOT / "ecog" / f"ecog_{session}_prep.bdf"


def speed_path(session):
    return DATA_ROOT / "coor" / f"cartesian_vel_norm_{session}.csv"


TARGET_FS = 500                # 脑电显示用采样率 (Hz)
CACHE_DIR = Path(__file__).resolve().parent / "cache"   # 降采样结果缓存

# ---- 时间 ----
WINDOW_SEC = 10.0              # 窗口长度 (s)，播放头固定在正中
SAMPLE_START_KEY = "sample_start"   # BDF 标注里代表“运动数据 0 时刻”的名字
VIDEO_START_KEY = "video_start"     # BDF 标注里代表"视频 0 秒"的名字
EEG_OFFSET = 5.0               # 找不到 sample_start 标注时的默认值 (s)
FPS = 30
SPEEDS = [0.25, 0.5, 1, 2, 4, 8]

# ---- 布局 ----
STRETCH_SPEED = 2              # 速度:脑电 的纵向比例（之后加 TFR 为 2:6:3）
STRETCH_EEG = 6
STRETCH_TFR = 3              # TFR 的纵向比例（速度:脑电:TFR = 2:6:3）
AXIS_WIDTH = 90                # 左侧通道名区域宽度，各面板一致以保证时间轴对齐
START_MAXIMIZED = True         # 启动时直接最大化

# ---- 脑电显示 ----
UV_PER_SPACING = 20.0          # 初始灵敏度：多少 µV 对应一个通道间距
GAIN_STEP = 1.25               # 每次按 ↑/↓ 的灵敏度倍率
REMOVE_WINDOW_MEAN = True      # 显示时减去窗口内均值，避免基线漂移把曲线推出画面

# ---- 眨眼标记 ----
def blink_path(session):
    return DATA_ROOT / "sync" / f"blink_frames_{session}.xlsx"

BLINK_COLOR = (70, 70, 70)     # 深灰色
BLINK_TICK_HEIGHT = 0.35       # 短刻度高度（单位：通道间距）

# ---- 视频 ----
def video_path(session):
    return DATA_ROOT / "videos" / "viz" / f"kinetics_video_grid_layout_{session}.mp4"

def sync_model_path(session):
    return DATA_ROOT / "sync" / f"model_sync_{session}_video2ecog.pkl"

USE_VIDEO_SYNC = True          # 是否用同步模型的截距修正视频时间轴

VIDEO_OFFSET = 0.0             # 视频 0 秒相对"运动 0 时刻"的偏移 (s)；视频与运动数据对齐时为 0
VIDEO_MAX_SKIP = 15            # 前进不超过该帧数时用顺序读取，否则 seek
VIDEO_MIN_FRAC = 0.22          # 视频列占窗口宽度的最小比例
VIDEO_MAX_FRAC = 0.45          # 视频列占窗口宽度的最大比例
WINDOW_SCREEN_FRAC = (0.95, 0.92)   # 窗口占屏幕可用区域的 (宽, 高) 比例

# ---- 速度显示 ----
SPEED_PER_SPACING = 20     # 初始灵敏度：取全部速度值的该百分位作为一个通道间距

# ---- TFR ----
import numpy as np
TFR_FREQS = np.arange(2, 150, 2)       # 频率 (Hz)
TFR_N_CYCLES_RANGE = (3, 15)           # n_cycles = freqs/2，并限制在该范围内
TFR_FS = 50                            # TFR 时间分辨率 (Hz)，须能整除 TARGET_FS
TFR_DB_RANGE = (-120, -80)             # 色标范围 (dB, 相对 1 V²)
DEFAULT_TFR_CHANNEL = "L12"

# ---- 颜色 ----
LINE_COLOR = (30, 30, 30)        # 找不到颜色时的默认线色
_ROOT = Path(__file__).resolve().parent
CHANNEL_CMAP_PATH = _ROOT / "channel_cmap.json"   # 脑电通道颜色表
JOINT_CMAP_PATH = _ROOT / "joint_cmap.json"       # 关节颜色表
USE_OPENGL = False             # 曲线卡顿时可尝试改 True
