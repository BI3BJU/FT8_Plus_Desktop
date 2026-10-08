# time_utils.py
import time

class Time_utils:
    def __init__(self):
        self.cycle_seconds = 15
        self.time_offset = 0.0          # Added: NTP correction offset

    def set_cycle_length(self, dur):
        self.cycle_seconds = dur

    def corrected_time(self):
        """Return the corrected UTC timestamp (float)."""
        return time.time() + self.time_offset

    def cycle_time(self):
        """Return progress within the current cycle (corrected time)."""
        return self.corrected_time() % self.cycle_seconds

    def curr_cycle_from_time(self):
        t = self.corrected_time()
        return int((t % (2 * self.cycle_seconds)) / self.cycle_seconds)

    def cyclestart(self, t=None):
        """Return the start of the cycle containing the given time (corrected time).
        Defaults to the current corrected time.
        """
        if t is None:
            t = self.corrected_time()
        cst = self.cycle_seconds * int(t / self.cycle_seconds)
        css = time.strftime("%y%m%d_%H%M%S", time.gmtime(cst))
        return {'time': cst, 'string': css}

    def tlog(self, txt, verbose=False):
        if verbose:
            print(f"{self.cyclestart()['string']} {self.cycle_time():5.2f} {txt}")

    def format_duration(self, seconds):
        intervals = (('yr', 314496000), ('wk', 604800), ('day', 86400),
                     ('hr', 3600), ('min', 60), ('sec', 1))
        for name, count in intervals:
            value = int(seconds / count)
            if value:
                return f"{value:d} {name}{'s' if value > 1 else ''}"

global_time_utils = Time_utils()

class Ticker:
    def __init__(self, trigger_time, cycle_length=None, timing_function=None):
        self.previous_ticker_time = 0
        self.timing_function = timing_function if timing_function is not None else global_time_utils.cycle_time
        self.trigger_time = trigger_time
        self.cycle_length = cycle_length if cycle_length is not None else global_time_utils.cycle_seconds

    def ticked(self):
        ticker_time = (self.timing_function() - self.trigger_time) % self.cycle_length
        ticked = ticker_time < self.previous_ticker_time
        self.previous_ticker_time = ticker_time
        return ticked