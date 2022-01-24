# gpiodmonitor

Tiny wrapper around gpiod used to monitor and debounce button presses.

## Installation

You can isntall the package from `pip`:

```bash
pip install gpiodmonitor
```

Needs libgpiod2 installed. Under Ubuntu / Debian you can it install using:

```bash
sudo apt install libgpiod2 python3-gpiod
```

## Usage:

```python3
import gpiodmonitor

def dummy_active(pin: int):
    """Dummy function."""
    print(f'{pin} is active')

def dummy_inactive(pin: int):
    """Dummy function."""
    print(f'{pin} is inactive')

def dummy_long_active(pin: int):
    """Dummy function."""
    print(f'{pin} has been active for a long time')

monitor = GPIODMonitor(0)

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

with monitor.open_chip() as gpio_chip:
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
