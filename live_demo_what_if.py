import time
import datetime
import threading
import queue
import matplotlib
from matplotlib.widgets import Button, Slider
import mplcyberpunk
matplotlib.use('MacOSX')
import matplotlib.pyplot as plt
from system import IrrigationSystem
from simulator import Auto_Predict_Simulator
from Data_pipeline.pipeline_with_fallback import EnvironmentPipeline, WeatherFallback
from Data_pipeline.run_pipeline import on_new_reading
from environment_settings import INITIAL_LATITUDE, INITIAL_LONGITUDE, BROKER, PORT

if __name__ == "__main__":

    system = IrrigationSystem()

    system.add_water_tank(
        name='Tank1',
        coordinates=(0, 0),
        elevation=0,
        max_head=10,
        min_head=0,
        max_volume=100,
        initial_volume=50,
    )

    system.add_node(
        name='Node1',
        coordinates=(0, 20),
        elevation=0,
    )

    system.add_pump(
        name='Pipe1',
        start_node='Tank1',
        end_node='Node1',
        length=20,
        diameter=10,
        roughness=None,
        power=None,
        flow_rate=0.5,
        activation_time=5,
    )

    system.add_node(
        name='Node2',
        coordinates=(0, 20),
        elevation=10,
    )

    system.add_pipe(
        name='Pipe2',
        start_node='Node1',
        end_node='Node2',
        length=20,
        diameter=10,
        roughness=None,
    )

    system.add_pot(
        name='Pot1',
        coordinates=(10, 20),
        elevation=10,
        soil_volume=10,
        max_moisture=1,
        min_moisture=0,
        initial_moisture=0.54,
    )

    system.add_pipe(
        name='Pipe3',
        start_node='Node2',
        end_node='Pot1',
        length=20,
        diameter=10,
        roughness=None,
    )

    system.add_node(
        name='Node4',
        coordinates=(20, 20),
        elevation=10,
    )

    system.add_pipe(
        name='Pipe4',
        start_node='Node2',
        end_node='Node4',
        length=20,
        diameter=10,
        roughness=None,
    )

    system.add_pot(
        name='Pot2',
        coordinates=(30, 20),
        elevation=10,
        soil_volume=10,
        max_moisture=1,
        min_moisture=0,
        initial_moisture=0.74,
    )

    system.add_pipe(
        name='Pipe5',
        start_node='Node4',
        end_node='Pot2',
        length=20,
        diameter=10,
        roughness=None,
    )

    system.add_node(
        name='Node5',
        coordinates=(20, 10),
        elevation=10,
    )

    system.add_pipe(
        name='Pipe6',
        start_node='Node4',
        end_node='Node5',
        length=20,
        diameter=10,
        roughness=None,
    )

    system.add_pot(
        name='Pot3',
        coordinates=(30, 10),
        elevation=10,
        soil_volume=10,
        max_moisture=1,
        min_moisture=0,
        initial_moisture=0.38,
    )

    system.add_pipe(
        name='Pipe7',
        start_node='Node5',
        end_node='Pot3',
        length=20,
        diameter=10,
        roughness=None,
    )

    system.add_pot(
        name='Pot4',
        coordinates=(20, 5),
        elevation=10,
        soil_volume=10,
        max_moisture=1,
        min_moisture=0,
        initial_moisture=0.67,
    )

    system.add_pipe(
        name='Pipe8',
        start_node='Node5',
        end_node='Pot4',
        length=20,
        diameter=10,
        roughness=None,
    )

    fallback = WeatherFallback(
        INITIAL_LATITUDE,
        INITIAL_LONGITUDE,
    )

    pipeline = EnvironmentPipeline(
        BROKER,
        PORT,
        fallback,
        1,
        on_new_reading=on_new_reading,
        interval_seconds=1
    )

    simulator = Auto_Predict_Simulator(
        pipeline,
        fallback,
        system,
    )

    plt.style.use("cyberpunk")
    plt.ion()
    fig = plt.figure(figsize=(13, 6), constrained_layout=True)


    def gui_pause(seconds):
        fig.canvas.draw_idle()
        fig.canvas.start_event_loop(seconds)


    ax_moist = fig.add_subplot(2, 2, 3)
    ax_irradiation = fig.add_subplot(2, 2, 1)
    ax_dt = fig.add_subplot(1, 2, 2)
    ax_temperature = ax_irradiation.twinx()
    ax_tank = ax_moist.twinx()

    simulator.pause = True
    btn_ax_pause = fig.add_axes([0.80, 0.92, 0.09, 0.06])
    btn_ax_stop = fig.add_axes([0.90, 0.92, 0.09, 0.06])
    btn_pause = Button(btn_ax_pause, 'Play', color='#212946', hovercolor='#08F7FE')
    btn_stop = Button(btn_ax_stop, 'Stop', color='#212946', hovercolor='#FE53BB')
    for btn in (btn_pause, btn_stop):
        btn.label.set_color('white')
        btn.label.set_fontsize(11)
        for spine in btn.ax.spines.values():
            spine.set_color('#08F7FE')


    def toggle_pause(event):
        simulator.pause = not simulator.pause
        btn_pause.label.set_text('Play' if simulator.pause else 'Pause')


    def do_stop(event):
        simulator.stop_requested = True


    btn_pause.on_clicked(toggle_pause)
    btn_stop.on_clicked(do_stop)

    slider_ax = fig.add_axes([0.75, 0.135, 0.16, 0.035])

    calib_slider = Slider(slider_ax, 'Balcony Microclimate Coefficient', 0.1, 1.5,
                          valinit=simulator.balcony_mc_coefficient,
                          color='#08F7FE')
    calib_slider.label.set_color('white')
    calib_slider.valtext.set_color('white')

    def on_calibrate(value):
        simulator.balcony_mc_coefficient = value

    calib_slider.on_changed(on_calibrate)

    clock_base = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)

    # figure-level texts: survive ax.clear(), created once, updated per frame
    clock_text = fig.text(
        0.7, 0.95, 'Day 1  00:00',
        ha='center', va='center', fontsize=13, color='white',
        bbox=dict(boxstyle='round,pad=0.45', facecolor='#212946',
                  edgecolor='#08F7FE', alpha=0.7)
    )
    source_text = fig.text(
        0.02, 0.95, 'data source: waiting...',
        ha='left', va='center', fontsize=10, color='#F5D300',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='#212946',
                  edgecolor='gray', alpha=0.7)
    )



    t_start = time.time()

    state_q = queue.Queue()
    def run_sim():
        try:
            for s in simulator.auto_simulate(pump_percent=10, time_scale=900):
                state_q.put(s)
        finally:
            state_q.put(None)


    sim_thread = threading.Thread(target=run_sim, daemon=True)
    sim_thread.start()

    t = []

    tank_hist: dict[str, list] = {}
    moisture_hist: dict[str, list] = {}
    temp_hist, irr_hist = [], []

    try:

        while True:
            try:
                state = state_q.get(timeout=0.05)
            except queue.Empty:
                plt.pause(0.05)
                #gui_pause(0.05)
                continue
            if state is None:
                break
            t.append(state.get('Sim time', 0.0) / 3600)  # simulated hours

            sim_s = state.get('Sim time', 0.0)
            sim_dt = clock_base + datetime.timedelta(seconds=sim_s)
            clock_text.set_text(sim_dt.strftime('%Y-%m-%d  %H:%M'))

            src_status = pipeline.get_data('status')
            if src_status in (None, 'ok'):
                source_text.set_text('data source: sensors ok')
                source_text.set_color('#00FF9F')
            else:
                source_text.set_text(f'data source: fallback ({src_status})')
                source_text.set_color('#FE53BB')
            for name, level in state['Tank levels'].items():
                tank_hist.setdefault(name, []).append(level)
            for name, moisture in state['Soil moisture levels'].items():
                moisture_hist.setdefault(name, []).append(moisture)
            inputs = state.get('Inputs', {})
            temp_hist.append(inputs.get('temp_c'))
            irr_hist.append(inputs.get('irradiation'))

            ax_moist.clear()
            ax_tank.clear()
            for name, values in tank_hist.items():
                ax_tank.plot(t, values, label=f'Tank level {name}', c='#08F7FE')
            for name, values in moisture_hist.items():
                ax_moist.plot(t, values, label=f'Moisture level {name}', c='#00FF9F')
            ax_moist.set_title("Outputs")
            ax_moist.set_xlabel("simulated time [h]")
            ax_moist.set_ylabel("moisture [-]")
            ax_tank.set_ylabel("tank level [-]")
            h1, l1 = ax_moist.get_legend_handles_labels()
            h2, l2 = ax_tank.get_legend_handles_labels()
            ax_moist.legend(h1 + h2, l1 + l2, loc='upper right',
                            framealpha=0.3, facecolor='#212946',
                            frameon=True)
            ax_moist.grid(True)

            ax_temperature.clear()
            ax_irradiation.clear()
            ax_temperature.plot(t, temp_hist, label='Temperature', color='#FE53BB')
            ax_irradiation.plot(t, irr_hist, label='Irradiation', c='#F5D300')
            ax_irradiation.set_title("Inputs")
            ax_irradiation.set_xlabel("simulated time [h]")
            ax_irradiation.set_ylabel("Irradiation [W/m^2]")
            ax_temperature.set_ylabel('temperature [C]')
            h3, l3 = ax_temperature.get_legend_handles_labels()
            h4, l4 = ax_irradiation.get_legend_handles_labels()
            ax_irradiation.legend(h3 + h4, l3 + l4, loc='upper right',
                                  framealpha=0.3, facecolor='#212946',
                                  frameon=True)
            ax_temperature.yaxis.set_label_position("right")
            ax_tank.yaxis.set_label_position("right")
            ax_irradiation.grid(True)

            state['System'].visualize_standard(size=5,
                                               show_states=True,
                                               ax=ax_dt)


            #fig.canvas.draw_idle()
            plt.pause(0.01)
            #gui_pause(0.01)

    except KeyboardInterrupt:
        pass

    plt.ioff()
    plt.show()
    mplcyberpunk.make_lines_glow(ax_moist)





