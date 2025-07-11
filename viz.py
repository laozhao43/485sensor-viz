import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.animation import FuncAnimation
from datetime import datetime
import re

# --- Configuration ---
csv_file_path = "sensor_data.csv"
line_y_values = [175, 150, 200]
data_window_s = 3
TIMESTAMP_COL_NAME = "Timestamp"
Y_LABEL_UNIT = "Height (mm)"
target_fps = 30
animation_interval_ms = int(1000 / target_fps)  # 30Hz

# --- Load Data ---
try:
    df = pd.read_csv(csv_file_path)
    df[TIMESTAMP_COL_NAME] = pd.to_datetime(df[TIMESTAMP_COL_NAME],
                                            format='%Y-%m-%d %H:%M:%S.%f',
                                            errors='coerce')
    if df[TIMESTAMP_COL_NAME].isnull().any():
        print(f"Warning: Some '{TIMESTAMP_COL_NAME}' values could not be parsed and were converted to NaT.")
        df.dropna(subset=[TIMESTAMP_COL_NAME], inplace=True)
        if df.empty:
            print("Error: No valid time data remaining after dropping unparseable rows. Exiting.")
            exit()
    sensor_cols = [col for col in df.columns if re.search(r'\(mm\)$', col)]
    if not sensor_cols:
        raise ValueError("No sensor columns ending with '(mm)' found in the CSV. Please check your column names.")
    ride_height_data = df[sensor_cols].values
    time_data = df[TIMESTAMP_COL_NAME].values
except Exception as e:
    print(f"Error loading data: {e}")
    exit()

num_sensors = len(sensor_cols)
if num_sensors == 0:
    print("Error: No sensor data to plot. Exiting.")
    exit()
elif num_sensors < 4:
    if num_sensors == 1:
        fig, axs = plt.subplots(1, 1, figsize=(8, 6))
        axs = [axs]
    elif num_sensors == 2:
        fig, axs = plt.subplots(1, 2, figsize=(16, 6))
        axs = axs.flatten()
    elif num_sensors == 3:
        fig, axs = plt.subplots(1, 3, figsize=(18, 6))
        axs = axs.flatten()
else:
    fig, axs = plt.subplots(2, 2, figsize=(12, 10))
    axs = axs.flatten()
    if num_sensors > 4:
        sensor_cols = sensor_cols[:4]
        ride_height_data = ride_height_data[:, :4]
        num_sensors = 4

time_formatter = mdates.DateFormatter('%H:%M:%S')
lines = []
for i in range(num_sensors):
    ax = axs[i]
    sensor_col_name = sensor_cols[i]
    line, = ax.plot([], [], label='Ride Height', color='blue')
    lines.append(line)
    for y_val in line_y_values:
        linestyle = '-' if y_val == 0 else '--'
        color = 'grey' if y_val == 0 else 'red'
        ax.axhline(y_val, color=color, linestyle=linestyle, linewidth=1, label=f'Y={y_val} mm')
    ax.set_ylabel(Y_LABEL_UNIT)
    ax.set_title(f"{sensor_col_name.replace(' (mm)', '')} Ride Height (Last {data_window_s}s)")
    ax.legend(loc="upper right", fontsize='small')
    ax.xaxis.set_major_formatter(time_formatter)
    ax.tick_params(axis='x', rotation=45)
    ax.grid(True, linestyle=":", alpha=0.7)
    ax.set_xlabel("Time (HH:MM:SS)", color='gray', fontsize='small')

plt.tight_layout()

# Add a static timestamp text (shows the first timestamp in the data)
static_time_str = str(time_data[0]) if len(time_data) > 0 else "No Data"
static_time_text = fig.text(
    0.5, 0.96, f"Start Time: {static_time_str}", ha='center', va='top', fontsize=12, color='black'
)

# --- Frame mapping for accurate time alignment ---
# Calculate the total duration in seconds
if len(time_data) > 1:
    total_duration_s = (time_data[-1] - time_data[0]) / np.timedelta64(1, 's')
else:
    total_duration_s = 0

# Number of frames for the animation
n_frames = int(np.ceil(total_duration_s * target_fps)) if total_duration_s > 0 else len(time_data)

def get_frame_time_idx(frame):
    """Map animation frame to the closest timestamp index for accurate time alignment."""
    if total_duration_s == 0 or len(time_data) == 1:
        return 0
    # Calculate the target time for this frame
    t0 = time_data[0]
    target_time = t0 + np.timedelta64(int(frame * 1000 / target_fps), 'ms')
    # Find the closest index in time_data
    idx = np.searchsorted(time_data, target_time, side='right') - 1
    idx = np.clip(idx, 0, len(time_data) - 1)
    return idx

def animate(frame):
    idx = get_frame_time_idx(frame)
    end_time = time_data[idx]
    start_time_window = end_time - np.timedelta64(data_window_s, 's')
    mask = (time_data >= start_time_window) & (time_data <= end_time)
    t = time_data[mask]
    for i, line in enumerate(lines):
        y = ride_height_data[mask, i]
        line.set_data(t, y)
        axs[i].set_xlim(t[0] if len(t) > 0 else end_time, t[-1] if len(t) > 0 else end_time)
        axs[i].relim()
        axs[i].autoscale_view(scalex=False, scaley=True)
    return lines

anim = FuncAnimation(
    fig, animate, frames=n_frames, interval=animation_interval_ms, blit=False
)

# Save the animation as an MP4 file (requires ffmpeg installed)
try:
    anim.save('ride_height_animation.mp4', writer='ffmpeg', bitrate=700, fps=target_fps)
    print("Animation saved as ride_height_animation.mp4")
except Exception as e:
    print(f"Error saving animation: {e}")
    print("Please ensure ffmpeg is installed and available in your system PATH.")