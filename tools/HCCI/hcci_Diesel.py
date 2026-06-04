import cantera as ct
import numpy as np
import matplotlib.pyplot as plt

# ============================================================
# Parameter
# ============================================================

rpm = 2000.0
compression_ratio = 16.0

bore = 0.086
stroke = 0.086
conrod = 0.143

T0 = 450.0          # K
p0 = 2.0e5          # Pa

phi = 0.4           # equivalence ratio

# ============================================================
# Geometrie
# ============================================================

Vd = np.pi / 4 * bore**2 * stroke
Vc = Vd / (compression_ratio - 1.0)

def volume(theta_deg):

    theta = np.radians(theta_deg)

    r = stroke / 2.0
    l = conrod

    x = r * (1 - np.cos(theta)) + \
        (l - np.sqrt(l**2 - (r*np.sin(theta))**2))

    V = Vc + np.pi/4 * bore**2 * x

    return V

# ============================================================
# Cantera Gas
# ============================================================

gas = ct.Solution("nDodecane_Reitz.yaml")

gas.set_equivalence_ratio(
    phi,
    fuel="c12h26",
    oxidizer={"o2":1.0, "n2":3.76}
)

gas.TP = T0, p0

# ============================================================
# Reaktor
# ============================================================

reactor = ct.IdealGasReactor(gas)

sim = ct.ReactorNet([reactor])

# ============================================================
# Kurbelwinkel-Simulation
# ============================================================

theta_array = np.linspace(-180, 180, 2000)

pressure = []
temperature = []
hrr = []

time = 0.0

for i in range(len(theta_array)-1):

    theta = theta_array[i]
    theta_next = theta_array[i+1]

    dtheta = theta_next - theta

    # Zeit aus Drehzahl
    dt = dtheta / 360.0 * 60.0 / rpm

    # Volumen setzen
    V = volume(theta)

    reactor.volume = V

    # Integration
    time += dt
    sim.advance(time)

    pressure.append(reactor.thermo.P / 1e5)
    temperature.append(reactor.T)

    # Wärmefreisetzung
    hrr.append(
        -np.dot(
            reactor.thermo.partial_molar_enthalpies,
            reactor.thermo.net_production_rates
        )
    )

# ============================================================
# Plot
# ============================================================

fig, ax1 = plt.subplots()

ax1.plot(theta_array[:-1], pressure)
ax1.set_xlabel("Crank angle [deg]")
ax1.set_ylabel("Pressure [bar]")

ax2 = ax1.twinx()
ax2.plot(theta_array[:-1], temperature)
ax2.set_ylabel("Temperature [K]")

plt.show()
