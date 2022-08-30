#!/usr/bin/env python3
"""
Monitor GPIO pins ("lines") using the "new" way (libgpiod).

Thus it depends on python3-gpiod being installed:
https://git.kernel.org/pub/scm/libs/libgpiod/libgpiod.git
"""

import contextlib
import logging
import sys
import time

from typing import Dict, List, Callable, Tuple, Optional, Iterator

# pylint: disable=import-error
import gpiod  # type: ignore

logger: logging.Logger = logging.getLogger(__name__)

# configure time [ms] over which a new signal has to be stable before
# a change in state is assumed

# after which time to check the state [ms]
DEBOUNCE_CHECK_INTERVAL: int = 5
# how long has a change to "active" to be stable [ms]
DEBOUNCE_ACTIVE_INTERVAL: int = 10
# how long has a change to "inactive" to be stable [ms]
DEBOUNCE_INACTIVE_INTERVAL: int = 100
# while recieving a stable "active" signal send `on_active` in regular intervals
ACTIVE_PULSES = False
# interval for pulses [ms]
ACTIVE_PULSE_INTERVAL: int = 500


class GPIOPin:
    # pylint: disable=too-many-instance-attributes
    """Class to hold data associated with each registered pin.

    Holds:
    * the current state (this will only change after debouncing the
      signal)
    * the state of the countdown
    * a list of callback functions to be called on a change to active /
      inactive

    Attributes:
        _num: The number of the pin.
        _active: Is the pin in active state?
        _countdown: This is activated on raw pin state change and
            decreases with every tick. If it reaches zero the state is
            asssumed to be stable.
        _countup: This counts up as soon as an active signal is stable.
            This is used to trigger callbacks in `on_long_active`.
        on_active: Functions to call on state change to active.
        on_inactive: Functions to call on state change to inactive.
        _on_long_active: Functions to call if the state has been
            active for X ms.
        _stack: A working copy of `on_long_active` where all called
            callbacks are popped off.
    """
    # save some space by using slots
    __slots__ = ('_num', '_active', '_countdown', '_countup', 'on_active',
                 'on_inactive', 'on_long_active', '_stack')

    active_interval: int = DEBOUNCE_ACTIVE_INTERVAL
    inactive_interval: int = DEBOUNCE_INACTIVE_INTERVAL
    check_interval: int = DEBOUNCE_CHECK_INTERVAL
    active_pulses: bool = ACTIVE_PULSES
    active_pulse_interval: int = ACTIVE_PULSE_INTERVAL

    def __init__(self, num: int) -> None:
        """Initialise the accessible variables.

        Arguments:
            num: The number of the pin.
        """

        self._num: int = num
        # key is initially assumed to be not pressed
        self._active: bool = False
        # the countdown to accept a signal as "pressed"
        self._countdown: int = GPIOPin.active_interval
        # the countup to accept a signal  as "long_pressed"
        self._countup: int = 0
        self.on_active: List[Callable[[int], None]] = []
        self.on_inactive: List[Callable[[int], None]] = []
        # list of tuples: (milliseconds, callback)
        self.on_long_active: List[Tuple[int, Callable[[int], None]]] = []
        # working copy of on_long_active
        self._stack: List[Tuple[int, Callable[[int], None]]] = []

    def set_state(self, active: bool) -> None:
        """This function is called once the signal has stably changed.

        Attributes:
            active: Is the state "active"?
        """

        logger.debug('pin: %s, state: %s', self._num, active)
        self._active = active
        if active:
            for callback in self.on_active:
                callback(self._num)
        else:
            for callback in self.on_inactive:
                callback(self._num)

    def is_active(self) -> bool:
        """Is the pin active?

        Returns:
            Is the stable state of the pin "active"?
        """
        return self._active

    def reset_countdown(self) -> None:
        """Reset the countdown for a signal to be stable.

        The length of the interval before a signal is considered stable
        depends on the state. React faster for changes to "active", the
        user might not be patient.
        """

        if self._active:
            self._countdown = GPIOPin.inactive_interval
        else:
            self._countdown = GPIOPin.active_interval

    def tick(self, raw_active: bool) -> None:
        """Debounce a change to active / inactive.

        This function is called every DEBOUNCE_CHECK_INTERVAL
        milliseconds.

        If the raw state of a pin differs from its known state this
        function tries to determine if it's a real change or just
        noise:
        A countdown is started and with every check that holds the new
        state the count is decreased.
        If the count reaches 0 the new state is accepted. If a the old
        state is detected inbetween the countdown is reset and starts
        again if a new state is detected.

        Example for DEBOUNCE_CHECK_INTERVAL = 5 ms and
        DEBOUNCE_ACTIVE_INTERVAL = 15 ms

        Time [ms]:  0  5 10 15 20 25 30 35
        Check:      1  2  3  4  5  6  7  8
        Signal:     0  1  1  0  1  1  1  1
                       ^  ^  ^  ^  ^  ^  ^
                       |  |  |  |  |  |  |
                       |  |  |  |  |  |  no change -> do nothing
                       |  |  |  |  |  signal stable -> count reaches 0
                       |  |  |  |  |                -> emit event
                       |  |  |  |  signal stable -> count decreases
                       |  |  |  countdown starts
                       |  |  signal does not seem stable -> reset
                       |  signal stable -> count decreased
                       countdown starts

        Adaption of: https://my.eng.utah.edu/~cs5780/debouncing.pdf

        Arguments:
            raw_state: The state as read from the pin ("line").
        """

        if raw_active == self._active:
            # state does not differ from the last accepted state
            # so reset the countdown
            self.reset_countdown()
            # if the state is active
            if self._active:
                # count up
                self._countup += GPIOPin.check_interval

                to_pop: List = []
                for i, (fire_after, callback) in enumerate(self._stack):
                    if self._countup >= fire_after:
                        # fire callback
                        callback(self._num)
                        # remove it from the list of available callbacks
                        to_pop.append(i)
                    else:
                        # break loop
                        # the list is sorted by the length
                        # all following items will need an even larger value of
                        # countup
                        break

                # remove fired callbacks
                for i in to_pop:
                    self._stack.pop(i)

                # if we are on multiples of `active_pulse_interval`
                if (self.active_pulses
                        and self._countup % self.active_pulse_interval == 0):
                    # send a pulse
                    for callback in self.on_active:
                        callback(self._num)

        else:
            # state is not the last accepted state
            # so decrease the count by DEBOUNCE_CHECK_INTERVAL
            self._countdown -= GPIOPin.check_interval

            if self._countdown == 0:
                # signal seems stable
                # accept the new state
                self.set_state(raw_active)
                # and prepare the countdown for the next change
                self.reset_countdown()
                # if the new state is active
                if self._active:
                    # create a working copy
                    self._stack = self.on_long_active.copy()
                    # and reset countup
                    self._countup = 0


class GPIODMonitor:
    """Eventemitter using libgpiod and debouncing the raw signal.

    For the debouncing algorithm see:
    See: https://my.eng.utah.edu/~cs5780/debouncing.pdf

    Attributes:
        _chip_number: The number of the chip with the pins.
        _chip: The gpiod.Chip.
        _pins: The pins by their number.
        check_interval: The interval with which to check the pins'
            state in milliseconds.
    """

    def __init__(self,
                 chip_number: int = 0,
                 check_interval: int = DEBOUNCE_CHECK_INTERVAL,
                 active_interval: int = DEBOUNCE_ACTIVE_INTERVAL,
                 inactive_interval: int = DEBOUNCE_INACTIVE_INTERVAL,
                 active_pulses: bool = ACTIVE_PULSES,
                 active_pulse_interval: int = ACTIVE_PULSE_INTERVAL):
        # pylint: disable=too-many-arguments
        """Set default values.

        Arguments:
            chip_number: The number of the gpio chip; 0 if in doubt.
            check_interval: The interval with which to check the pins'
                state in milliseconds.
            active_interval: The interval it takes for a stable active
                signal to trigger a change in state in milliseconds.
            inactive_interval: The interval it takes for a stable
                inactive signal to trigger a change in state in
                milliseconds.
            active_pulses: While recieving a stable "active" signal
                send `on_active` in regular intervals.
            active_pulse_interval: Interval for pulses in milliseconds.
        """
        logger.debug('creating monitor on chip %s', chip_number)
        self._chip_number = chip_number
        self._chip: Optional[gpiod.Chip] = None
        self._pins: Dict[int, GPIOPin] = {}
        self.check_interval: int = check_interval
        GPIOPin.check_interval = check_interval
        GPIOPin.active_interval = active_interval
        GPIOPin.inactive_interval = inactive_interval
        GPIOPin.active_pulses = active_pulses
        GPIOPin.active_pulse_interval = active_pulse_interval

    def get_pins(self) -> Dict[int, GPIOPin]:
        """Return the pins.

        Returns:
            The pins mapped to their number.
        """
        return self._pins

    def is_raw_pin_active(self, pin: int) -> bool:
        """Is the raw state of the pin "active".

        Arguments:
            pin: Number of the pin.

        Returns:
            Is the pin ("line") active?
        """
        if not self._chip:
            raise IOError('Chip not opened.')
        return bool(self._chip.get_line(pin).get_value())

    def register(self,
                 pin,
                 on_active: Optional[Callable[[int], None]] = None,
                 on_inactive: Optional[Callable[[int], None]] = None) -> None:
        """Register a callback for a stable signal change on a pin.

        If you want to have multiple callbacks for one event call this
        function often as you like but don't hand it a list.

        Arguments:
            pin: The BCM-number of the pin.
            on_active: Function to call if the state changes to active.
            on_inactive: Function to call if the state changes to
                inctive.
        """

        if not pin in self._pins:
            logger.debug('registering new pin %s', pin)
            self._pins[pin] = GPIOPin(pin)
        if on_active:
            self._pins[pin].on_active.append(on_active)
        if on_inactive:
            self._pins[pin].on_inactive.append(on_inactive)

    def register_long_active(self, pin: int, callback: Callable[[int], None],
                             seconds: int) -> None:
        """Register a callback for a long change to active.

        Arguments:
            pin: The BCM-number of the pin.
            callback: Function to call if the state changes to active.
            seconds: The time button needs to be pressed before
                callback is fired.
        """
        if not pin in self._pins:
            logger.debug('registering new pin %s', pin)
            self._pins[pin] = GPIOPin(pin)
        self._pins[pin].on_long_active.append((seconds * 1000, callback))
        # sort callbacks by the time the button needs to be pressed
        self._pins[pin].on_long_active.sort(key=lambda x: x[0])

    @contextlib.contextmanager
    def open_chip(self) -> Iterator[gpiod.Chip]:
        """Opens the chip and requests the registered lines.

        Yields:
            The handle of the chip.
        """
        self._chip = gpiod.Chip(f'gpiochip{self._chip_number}')

        logger.debug('opened chip: %s', self._chip)

        # pylint: disable=consider-iterating-dictionary
        for i in self._pins.keys():
            logger.debug('requesting line: %s',
                         self._chip.get_line(i).offset())
            self._chip.get_line(i).request(
                consumer="GPIODMonitor",
                type=gpiod.LINE_REQ_DIR_IN,
                flags=gpiod.LINE_REQ_FLAG_BIAS_PULL_UP
                | gpiod.LINE_REQ_FLAG_ACTIVE_LOW)
        yield self._chip
        self._chip.close()
        self._chip = None

    def tick(self) -> None:
        """Check the state of all registered pins."""
        if self._chip is None:
            raise IOError('Chip not opened.')

        for number, pin in self.get_pins().items():
            pin.tick(self.is_raw_pin_active(number))

    def monitor(self):
        """Monitor all registered pins ("lines") for a change in state."""
        if not self._chip is None:
            logger.error(
                'chip has already been opend using the context manager')
            return

        with self.open_chip() as chip:
            self._chip = chip
            try:
                logger.debug('starting the loop')
                while True:
                    # check according to interval
                    time.sleep(self.check_interval / 1000)
                    self.tick()
            except KeyboardInterrupt:
                sys.exit(130)
        self._chip = None


if __name__ == '__main__':
    import argparse

    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    parser.add_argument("chip", help="the number of the chip", type=int)
    parser.add_argument("pins",
                        help="the numbers of the pins to monitor",
                        type=int,
                        nargs='+')
    parser.add_argument('-v',
                        '--verbosity',
                        help='increase verbosity',
                        action='count',
                        default=0)
    args: argparse.Namespace = parser.parse_args()

    verbosity = ['ERROR', 'WARNING', 'INFO', 'DEBUG']
    root_logger: logging.Logger = logging.getLogger()
    root_logger.setLevel(verbosity[args.verbosity])

    def dummy_active(pin: int):
        """Dummy function."""
        print(f'{pin} is active')

    def dummy_inactive(pin: int):
        """Dummy function."""
        print(f'{pin} is inactive')

    def dummy_long_active(pin: int):
        """Dummy function."""
        print(f'{pin} has been active for a long time')

    monitor = GPIODMonitor(args.chip)

    for gpio_pin in args.pins:
        monitor.register(int(gpio_pin),
                         on_active=dummy_active,
                         on_inactive=dummy_inactive)
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
