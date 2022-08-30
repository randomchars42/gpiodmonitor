# gpiodmonitor

Tiny wrapper around gpiod used to monitor and debounce button presses.

Callbacks are triggered on these events:

* on change to active signal (e.g., button pressed)
* on change to inactive signal (e.g., button released)
* after the active signal has been stable for a certain period of time (e.g., button held down)
* in regular interval while an "active" signal is recieved

## Installation

You can isntall the package from `pip`:

```bash
pip install gpiodmonitor
```

Needs libgpiod2 installed. Under Ubuntu / Debian you can install it using:

```bash
sudo apt install libgpiod2 python3-gpiod
```

## Usage:

```python3
from gpiodmonitor import gpiodmonitor

def dummy_active(pin: int):
    """Dummy function."""
    print(f'{pin} is active')

def dummy_inactive(pin: int):
    """Dummy function."""
    print(f'{pin} is inactive')

def dummy_long_active(pin: int):
    """Dummy function."""
    print(f'{pin} has been active for a long time')

monitor = gpiodmonitor.GPIODMonitor(chip=0)

for gpio_pin in [12,13]:
    # register some functions to be called on activity on pins 12 and 13
    monitor.register(int(gpio_pin),
                     on_active=dummy_active,
                     on_inactive=dummy_inactive)
    # register a function to be called when the button is pressed for 3 seconds
    # duration=3
    monitor.register_long_active(int(gpio_pin),
                                 callback=dummy_long_active,
                                 seconds=3)

with monitor.open_chip():
    try:
        while True:
            # check according to interval
            time.sleep(monitor.check_interval / 1000)
            monitor.tick()
    except KeyboardInterrupt:
        sys.exit(130)
    # or use (equivalent but you don't have controll over the loop):
    # chip.monitor()
```
