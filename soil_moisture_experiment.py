import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import json

def get_moisture_slope(m_start, m_end, net_added_l):
    return (m_end - m_start) / net_added_l

def get_drainage_slope(
        V_before_l: np.ndarray,
        V_added_l: np.ndarray,
        V_drained_l: np.ndarray,
):
    retained = np.array([added - drained for
                         added, drained in zip(V_added_l, V_drained_l)])

    slope, intercept = np.polyfit(V_before_l, retained, 1)
    return slope, intercept



if __name__ == '__main__':
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

    m_start = float(moisture[(t > 700) & (t < 900)].median())
    m_end = float(moisture.iloc[-30:].median())
    net_l = df["net_water_ml"].iloc[-1] / 1000.0


    slope = get_moisture_slope(m_start, m_end, net_l)
    print(f"Moisture slope: {slope:.4f}")

    V_before, V_added, V_drained = [], [], []
    V = added = 0.0
    for _, r in df.iterrows():
        added += r["added_ml"]
        if r["removed_ml"] > 0 and added > 0:
            V_before.append(V / 1000)
            V_added.append(added / 1000)
            V_drained.append(r["removed_ml"] / 1000)
            V += added - r["removed_ml"]
            added = 0.0

    V_before = np.array(V_before)
    V_added = np.array(V_added)
    V_drained = np.array(V_drained)

    d_slope, d_intercept = get_drainage_slope(V_before, V_added, V_drained)

    print(f"Drainage slope: {d_slope:.4f}")
    print(f"Drainage intercept: {d_intercept:.4f}")
    fig2, ax3 = plt.subplots()
    ax3.scatter(V_before, V_added - V_drained, label="retained (measured)")
    vv = np.linspace(0, -d_intercept / d_slope, 50)
    ax3.plot(vv, d_slope * vv + d_intercept, "r--", label="linear fit")
    ax3.set_xlabel("Water in pot before dose [L]")
    ax3.set_ylabel("Retained per dose [L]")
    ax3.set_title("Drainage: retained water vs pot fill level")
    ax3.legend();
    ax3.grid(True)
    plt.savefig("drainage_fit.png")
    plt.show()

    fig3, ax4 = plt.subplots()
    ax4.plot([0, net_l], [m_start, m_end], "ro-", label=f"mapping (slope = {slope:.3f}/L)")
    ax4.scatter([0, net_l], [m_start, m_end], color="red", zorder=3)
    ax4.set_xlabel("Retained water in pot [L]")
    ax4.set_ylabel("Soil moisture [-]")
    ax4.set_title("Mapping: retained water to soil moisture")
    ax4.legend();
    ax4.grid(True)
    plt.savefig("moisture_mapping.png")
    plt.show()




