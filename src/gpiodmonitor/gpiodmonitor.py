#!/usr/bin/env python3

# depends on python3-gpiod
# use the "new" way to interact with GPIO
# https://git.kernel.org/pub/scm/libs/libgpiod/libgpiod.git
import gpiod
import sys
import time
import logging

logger = logging.getLogger(__name__)

# configure time [ms] over which a new signal has to be stable before a change
# in state is assumed

# after which time to check the state [ms]
DEBOUNCE_CHECK_INTERVAL = 5
# how long has a change to "press" signal to be stable [ms]
DEBOUNCE_PRESS_INTERVAL = 10
# how long has a change to "release" signal to be stable [ms]
DEBOUNCE_RELEASE_INTERVAL = 100

class GPIOPin:
    """Class ("struct") to hold data associated with each registered pin.

    Holds:
     - the current state (this will only change after debouncing the signal)
     - the state of the countdown
     - a list of callback functions to be called on a change to pressed /
       released
    """
    # save some space by using slots
    __slots__ =  ('id', 'state', 'countdown', 'on_pressed', 'on_released',
            'on_long_pressed', 'countup', 'stack')

    def __init__(self, id, ):
        """Initialise the accessible variables.
        """
        self.id = id
        # key is initially assumed to be not pressed
        self.state = False
        # the countdown to accept a signal as "pressed"
        self.countdown = GPIOPin.press_interval
        # the countup to accept a signal  as "long_pressed"
        self.countup = 0
        self.on_pressed = []
        self.on_released = []
        # list of tuples: (milliseconds, callback)
        self.on_long_pressed = []
        # working copy of on_long_pressed
        self.stack = []

    def set_state(self, state):
        logger.debug('pin: {}, state: {}'.format(self.id, state))
        self.state = state
        if state:
            # pressed
            for callback in self.on_pressed:
                callback(self.id, time.time())
        else:
            # released
            for callback in self.on_released:
                callback(self.id, time.time())

    def get_state(self):
        return self.state

    def reset_countdown(self):
        if self.state:
            self.countdown = GPIOPin.release_interval
        else:
            self.countdown = GPIOPin.press_interval

    def tick(self, raw_state):
        """Debounce a press / release.

        This function is called every DEBOUNCE_CHECK_INTERVAL milliseconds.

        If a signal on a `gpio_pin` differs from its known `gpio_pin.state`
        this function tries to determine if it's a real event or just noise:
        A countdown is started and with every check that holds the new state
        the count is decreased.
        If the count reaches 0 the new state is accepted. If a the old state
        is detected inbetween the countdown is reset and starts again if a
        new state is detected.

        Example for DEBOUNCE_CHECK_INTERVAL = 5 ms and
        DEBOUNCE_PRESS_INTERVAL = 15 ms

        Time [ms]:  0  5 10 15 20 25 30 35
        Check:      1  2  3  4  5  6  7  8
        Signal:     0  1  1  0  1  1  1  1
                       ^  ^  ^  ^  ^  ^  ^
                       |  |  |  |  |  |  |
                       |  |  |  |  |  |  no change -> do nothing
                       |  |  |  |  |  signal stable -> count reaches zero
                       |  |  |  |  |                -> emit event
                       |  |  |  |  signal stable -> count decreases
                       |  |  |  countdown starts
                       |  |  signal does not seem stable -> reset countdown
                       |  signal stable -> count decreased
                       countdown starts

        Adaption of: https://my.eng.utah.edu/~cs5780/debouncing.pdf

        Positional arguments:
        raw_state -- the state as read from the pin ("line") [bool]
        """
        if raw_state == self.state:
            # state does not differ from the last accepted state
            # so reset the countdown
            self.reset_countdown()
            # if the button is pressed
            if self.state:
                # count up
                self.countup += GPIOPin.check_interval

                to_pop = []
                for i in range(len(self.stack)):
                    if self.countup >= self.stack[i][0]:
                        # fire callback
                        self.stack[i][1](self.id, time.time())
                        # mark callback as used
                        to_pop.append(i)
                    else:
                        # break loop
                        # the list is sorted by the length
                        # all following items will need an even larger countup
                        break

                # remove fired callbacks
                for n in to_pop:
                    self.stack.pop(n)

        else:
            # state is not the last accepted state
            # so decrease the count by DEBOUNCE_CHECK_INTERVAL
            self.countdown -= GPIOPin.check_interval

            if self.countdown == 0:
                # signal seems stable
                # accept the new state
                self.set_state(raw_state)
                # and prepare the countdown for the next change
                self.reset_countdown()
                # if the button has been pressed
                if self.state:
                    # create a working copy
                    self.stack = self.on_long_pressed.copy()
                    # and reset countup
                    self.countup = 0

class GPIODMonitor:
    """Eventemitter using libgpiod and debouncing the raw signal.

    For the debouncing algorithm see:
    See: https://my.eng.utah.edu/~cs5780/debouncing.pdf
    """

    def __init__(self, chip_number=0,
            check_interval=DEBOUNCE_CHECK_INTERVAL,
            press_interval=DEBOUNCE_RELEASE_INTERVAL,
            release_interval=DEBOUNCE_RELEASE_INTERVAL):
        """Set default values.

        Positional arguments:
        chip_number -- the number of the gpio chip [int]; 0 if in doubt
        """
        logger.debug('creating monitor on chip {}'.format(chip_number))
        self.__chip_number = chip_number
        self.__gpio_pins = {}
        self.check_interval = check_interval
        GPIOPin.check_interval = check_interval
        GPIOPin.press_interval = press_interval
        GPIOPin.release_interval = release_interval

    def register(self, gpio_pin, on_pressed=None, on_released=None):
        """Register a callback for an event on a gpio pin.

        If you want to have multiple callbacks for one event call this function
        as often as you like but don't hand it a list.

        Positional arguments:
        gpio_pin -- the BCM-number of the pin [int]

        Keyword arguments:
        on_pressed -- callback function to call if the button was pressed
        on_released -- callback function to call if the button was pressed
        """
        if not gpio_pin in self.__gpio_pins:
            logger.debug('registering new pin {}'.format(gpio_pin))
            self.__gpio_pins[gpio_pin] = GPIOPin(gpio_pin)
        if on_pressed:
            self.__gpio_pins[gpio_pin].on_pressed.append(on_pressed)
        if on_released:
            self.__gpio_pins[gpio_pin].on_released.append(on_released)

    def register_long_press(self, gpio_pin, callback, seconds):
        """Register a callback for an event on a gpio pin.

        If you want to have multiple callbacks for one event call this function
        as often as you like but don't hand it a list.

        Positional arguments:
        gpio_pin -- the BCM-number of the pin [int]
        callback -- the function to call on long press [function]
        seconds -- time the button needs to be pressed before callback is called
        """
        if not gpio_pin in self.__gpio_pins:
            logger.debug('registering new pin {}'.format(gpio_pin))
            self.__gpio_pins[gpio_pin] = GPIOPin(gpio_pin)
        self.__gpio_pins[gpio_pin].on_long_pressed.append((seconds * 1000,
                callback))
        # sort callbacks by the time the button needs to be pressed
        self.__gpio_pins[gpio_pin].on_long_pressed.sort(key=lambda x: x[0])

    def run(self):
        """Monitor all registered pins ("lines") for a change in state.
        """
        with gpiod.Chip('gpiochip{}'.format(str(self.__chip_number))) as chip:
            logger.debug('opened chip: {}'.format(chip))
            self.__chip = chip

            lines = chip.get_lines(self.__gpio_pins.keys())
            for i in self.__gpio_pins.keys():
                logger.debug('requesting line: {}'.format(
                    self.__chip.get_line(i).offset()))
                self.__chip.get_line(i).release()
                self.__chip.get_line(i).request(consumer="GPIODMonitor.py",
                    type=gpiod.LINE_REQ_DIR_IN,
                    flags=gpiod.LINE_REQ_FLAG_BIAS_PULL_UP|gpiod.LINE_REQ_FLAG_ACTIVE_LOW)

            vals = lines.get_values()

            try:
                logger.debug('starting the loop')
                while True:
                    # check according to interval
                    time.sleep(DEBOUNCE_CHECK_INTERVAL / 1000)

                    for i in self.__gpio_pins.keys():
                        pin = self.__chip.get_line(i).offset()

                        self.__gpio_pins[pin].tick(
                                self.__chip.get_line(i).get_value())
            except KeyboardInterrupt:
                sys.exit(130)

if __name__ == '__main__':
    """Run the application.

    Configure logging and read parameters.
    """
    import argparse
    import logging.config
    from .log import log

    parser = argparse.ArgumentParser()
    parser.add_argument("chip", help="the number of the chip",
            type=int)
    parser.add_argument("pins", help="the numbers of the pins to monitor",
            type=int, nargs='+')
    parser.add_argument(
            '-v', '--verbosity',
            help='increase verbosity',
            action='count',
            default=0)
    args = parser.parse_args()

    verbosity = ['ERROR', 'WARNING', 'INFO', 'DEBUG']
    log.config['handlers']['console']['level'] = verbosity[args.verbosity]
    log.config['loggers']['__main__']['level'] = verbosity[args.verbosity]
    log.config['loggers']['gpiodmonitor']['level'] = verbosity[args.verbosity]
    logger.info('log level: {}'.format(verbosity[args.verbosity]))
    logging.config.dictConfig(log.config)

    monitor = GPIODMonitor(args.chip)
    for pin in args.pins:
        monitor.register(int(pin),
                lambda used_pin, time: print("{}: 1".format(used_pin)),
                lambda used_pin, time: print("{}: 0".format(used_pin)))
        monitor.register_long_press(int(pin),
                lambda used_pin, time: print("{}: 1 long".format(used_pin)),
                3)
    monitor.run()
