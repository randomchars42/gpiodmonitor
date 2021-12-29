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
    __slots__ =  ('id', 'state', 'countdown', 'on_pressed', 'on_released')

    def __init__(self, id):
        """Initialise the accessible variables.
        """
        self.id = id
        # key is initially assumed to be not pressed
        self.state = False
        # the countdown to accept a signal as "pressed"
        self.countdown = DEBOUNCE_PRESS_INTERVAL / DEBOUNCE_CHECK_INTERVAL
        self.on_pressed = []
        self.on_released = []


class GPIODMonitor:
    """Eventemitter using libgpiod and debouncing the raw signal.

    For the debouncing algorithm see:
    See: https://my.eng.utah.edu/~cs5780/debouncing.pdf
    """

    def __init__(self, chip_number=0):
        """Set default values.

        Positional arguments:
        chip_number -- the number of the gpio chip [int]; 0 if in doubt
        """
        logger.debug('creating monitor on chip {}'.format(chip_number))
        self.__chip_number = chip_number
        self.__gpio_pins = {}

    def register(self, gpio_pin, on_pressed=None, on_released=None):
        """Register a callback for an event on a gpio pin.

        If you want to have multiple callbacks for one event call this function
        as often as you like but don't hand it a list.

        Positional arguments:
        gpio_pin -- the BCM-number of the pin [int]
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

    def _debounce(self, gpio_pin, raw_state):
        """Debounce a press / release.

        This function is called every DEBOUNCE_CHECK_INTERVAL milliseconds.

        If a signal on a a `gpio_pin` differs from its known `gpio_pin.state`
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
        gpio_pin -- the pin to debounce [GPIOPin]
        raw_state -- the state as read from the pin ("line") [bool]

        Returns:
        (has the state changed, its new state) -- tuple([bool,bool])
        """
        key_changed = False

        if raw_state == gpio_pin.state:
            # state does not differ from the last accepted state
            # so reset the countdown
            if gpio_pin.state:
                gpio_pin.countdown = DEBOUNCE_RELEASE_INTERVAL / DEBOUNCE_CHECK_INTERVAL
            else:
                gpio_pin.countdown = DEBOUNCE_PRESS_INTERVAL / DEBOUNCE_CHECK_INTERVAL
        else:
            #logger.debug('detected change in state on pin {}'.format(
            #    str(gpio_pin.id)))
            # state is not the last accepted state
            # so decrease the count
            gpio_pin.countdown -= 1

            if gpio_pin.countdown == 0:
                # signal seems stable
                # accept the new state
                gpio_pin.state = raw_state
                key_changed = True
                # and prepare the countdown for the next change
                if gpio_pin.state:
                    gpio_pin.countdown = DEBOUNCE_RELEASE_INTERVAL / DEBOUNCE_CHECK_INTERVAL
                else:
                    gpio_pin.countdown = DEBOUNCE_PRESS_INTERVAL / DEBOUNCE_CHECK_INTERVAL
        return (key_changed, gpio_pin.state)

    def run(self):
        """Monitor all registered pins ("lines") for a change in state.
        """
        with gpiod.Chip('gpiochip{}'.format(str(self.__chip_number))) as chip:
            logger.debug('opened chip: {}'.format(chip))
            self.__chip = chip

            lines = chip.get_lines(self.__gpio_pins.keys())
            for i in self.__gpio_pins.keys():
                logger.debug('requesting line: {}'.format(self.__chip.get_line(i).offset()))
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
                        # let _debounce decide whether the pin / line has a
                        # new state
                        changed, state = self._debounce(self.__gpio_pins[pin],
                                self.__chip.get_line(i).get_value())
                        if changed:
                            logger.debug('pin: {}, state: {}'.format(
                                pin, state))
                            if state:
                                for callback in self.__gpio_pins[pin].on_pressed:
                                    callback(pin, time.time())
                            else:
                                for callback in self.__gpio_pins[pin].on_released:
                                    callback(pin, time.time())
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
                lambda used_pin: print("{}: 1".format(used_pin)),
                lambda used_pin: print("{}: 0".format(used_pin)))
    monitor.run()
