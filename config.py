"""全局配置。需要调参数时只改这个文件。"""
from pathlib import Path

# ---- 数据 ----
DEFAULT_BDF_PATH = ""          # 留空则启动时弹出文件选择框；也可用命令行参数传入
TARGET_FS = 500                # 显示用采样率 (Hz)
CACHE_DIR = Path(__file__).resolve().parent / "cache"   # 降采样结果缓存

# ---- 时间 ----
WINDOW_SEC = 10.0              # 窗口长度 (s)，播放头固定在正中
EEG_OFFSET = 5.0               # 视频时间 = EEG 时间 - EEG_OFFSET（目前只用于显示）
FPS = 60                       # 界面刷新率
SPEEDS = [0.25, 0.5, 1, 2, 4, 8]

# ---- 显示 ----
UV_PER_SPACING = 150.0         # 初始灵敏度：多少 µV 对应一个通道间距
GAIN_STEP = 1.25               # 每次按 ↑/↓ 的灵敏度倍率
REMOVE_WINDOW_MEAN = True      # 显示时减去窗口内均值，避免基线漂移把曲线推出画面
LINE_COLOR = (30, 30, 30)        # 找不到颜色时的默认线色
CHANNEL_CMAP_PATH = Path(__file__).resolve().parent / "channel_cmap.json"   # 通道颜色表
USE_OPENGL = False             # 曲线卡顿时可尝试改 True
