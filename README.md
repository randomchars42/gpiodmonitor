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

# set the chipnumber of your GPIO board (0 on the Raspberry Pi)
monitor = GPIODMonitor(0)

for pin in [17,23]:
    # register some lambda to be called on activity on pins 17 and 23
    monitor.register(pin,
            on_pressed=lambda used_pin, time: print("{}: pressed".format(
                used_pin)),
            on_released=lambda used_pin, time: print("{}: released".format(
                used_pin)))

    # register a lambda to be called when the button is pressed for 3 seconds
    duration=3
    monitor.register_long_press(pin,
            lambda used_pin, time: print("{}: pressed for {} secondes".format(
                used_pin,duration)),
            duration)

# will run infinitely
monitor.run()
```
