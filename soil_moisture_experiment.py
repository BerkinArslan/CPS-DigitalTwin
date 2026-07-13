import pandas as pd
import matplotlib.pyplot as plt

path_to_data = '/Users/berkinarslan/Documents/Lectures/CPS Lectures/Project/Experiment_1_doku/experiment_data.csv'
df = pd.read_csv(path_to_data)
print(df.head())
t = df['Time_s']
moisture = df['Calibrated']

events = [
    (300,  0,   0),    # 10:39 sensor placed in dry soil
    (960,  250, 0),    # 10:50
    (1260, 250, 0),    # 10:55
    (1440, 0,   180),  # 10:58
    (1560, 250, 0),    # 11:00
    (1860, 250, 0),    # 11:05
    (1980, 0,   300),  # 11:07
    (2160, 250, 0),    # 11:10
    (2460, 250, 0),    # 11:15
    (2580, 0,   380),  # 11:17
    (2760, 250, 0),    # 11:20
    (3060, 250, 0),    # 11:25
    (3240, 0,   400),  # 11:28
    (3360, 250, 0),    # 11:30
    (3660, 250, 0),    # 11:35
    (3840, 0,   330),  # 11:38
    (3960, 250, 0),    # 11:40
    (4260, 250, 0),    # 11:45
    (4560, 0,   480),  # 11:50
    (5400, 0,   0),    # 12:04 end of data recording
    (5520, 0,   10),   # 12:06
]

df = pd.DataFrame(events, columns=["time_s", "added_ml", "removed_ml"])


df["added_cum_ml"]   = df["added_ml"].cumsum()
df["removed_cum_ml"] = df["removed_ml"].cumsum()
df["net_water_ml"]   = df["added_cum_ml"] - df["removed_cum_ml"]


fig = plt.figure()
ax = fig.add_subplot(111)
ax2 = ax.twinx()
ax.plot(t, moisture, label="Moisture", color="red")
ax2.plot(df['time_s'], df['net_water_ml'], label="Net Water ml", color="blue")
ax2.set_ylabel("Net Water input [ml]")
ax.set_ylabel("Soil Moisture [-]")
fig.suptitle("Experiment: Soil Moisture vs Water Input")
ax.set_xlabel("Time [s]")
h1, l1 = ax.get_legend_handles_labels()
h2, l2 = ax2.get_legend_handles_labels()
ax.legend(h1 + h2, l1 + l2, loc="lower right")
ax.grid(True)
plt.savefig("Soil Moisture vs Water Input.png")
plt.show()
