from __future__ import print_function
import sys


__version__ = '0.2'


def _import_json():
    """Import json module on demand."""
    global json
    if json is None:
        import json
    return json
json = None


# Clocks
try:
    # Python 3.3+ (PEP 418)
    from time import monotonic as monotonic_clock, perf_counter
except ImportError:
    import time

    monotonic_clock = time.time
    if sys.platform == "win32":
        perf_counter = time.clock
    else:
        perf_counter = time.time


# Statistics
try:
    from statistics import mean, stdev as _stdev   # Python 3.4+

    def stdev(data):
        # Wrapper to hide the xbar parameter, to be portable with Python 2
        return _stdev(data)
except ImportError:
    import math

    def mean(data):
        if not data:
            raise ValueError("data must be non-empty")
        return float(sum(data)) / len(data)

    def stdev(data):
        data = [float(value) for value in data]
        n = len(data)
        if n < 2:
            raise ValueError('stdev requires at least two data points')

        c = mean(data)

        total = sum((x - c) ** 2 for x in data)
        total2 = sum((x - c) for x in data)
        ss = total - total2**2 / n
        variance = ss / (n - 1)

        return math.sqrt(variance)


_TIMEDELTA_UNITS = ('sec', 'ms', 'us', 'ns')


def _format_timedeltas(values):
    if any(dt < 0 for dt in values):
        raise ValueError("numbers must be positive")

    ref_value = values[0]
    for i in range(2, -9, -1):
        if ref_value >= 10.0 ** i:
            break
    else:
        i = -9

    precision = 2 - i % 3
    k = -(i // 3) if i < 0 else 0
    factor = 10 ** (k * 3)
    unit = _TIMEDELTA_UNITS[k]
    fmt = "%%.%sf %s" % (precision, unit)

    return tuple(fmt % (value * factor,) for value in values)


def _format_timedelta(value):
    return _format_timedeltas((value,))[0]


def _format_run_result(values, verbose=0):
    numbers = [mean(values)]
    with_stdev = (len(values) >= 2)
    if with_stdev:
        numbers.append(stdev(values))
    if verbose:
        numbers.append(min(values))
        numbers.append(max(values))

    numbers = _format_timedeltas(numbers)
    if verbose:
        if with_stdev:
            text = '%s +- %s (min: %s, max: %s)' % numbers
        else:
            text = '%s (min: %s, max: %s)' % numbers
    else:
        if with_stdev:
            text = '%s +- %s' % numbers
        else:
            text = numbers[0]
    return text


def _format_number(number, unit, units=None):
    plural = (abs(number) > 1)
    if number >= 10000:
        pow10 = 0
        x = number
        while x >= 10:
            x, digit = divmod(x, 10)
            if digit != 0:
                break
            pow10 += 1
        if x == 1 and digit == 0:
            number = '10^%s' % pow10

    if plural:
        if not units:
            units = unit + 's'
        return '%s %s' % (number, units)
    else:
        return '%s %s' % (number, unit)


class Results:
    def __init__(self, runs=None, name=None, metadata=None, formatter=None):
        if runs is not None:
            self.runs = runs
        else:
            self.runs = []
        self.name = name
        # Raw metadata dictionary, key=>value, keys and values are non-empty
        # strings
        if metadata is not None:
            self.metadata = metadata
        else:
            self.metadata = {}
        if formatter is not None:
            self._formatter = formatter
        else:
            self._formatter = _format_run_result

    def format(self, verbose=False):
        if self.runs:
            samples = []
            first_run = self.runs[0]
            warmup = len(first_run.warmups)
            nsample = len(first_run.samples)
            loops = first_run.loops
            for run in self.runs:
                # FIXME: handle the case where samples is empty
                samples.extend(run.samples)
                if loops is not None and run.loops != loops:
                    loops = None
                run_nsample = len(run.samples)
                if nsample is not None and nsample != run_nsample:
                    nsample = None
                run_warmup = len(run.warmups)
                if warmup is not None and warmup != run_warmup:
                    warmup = None

            iterations = []
            nrun = len(self.runs)
            if nrun > 1:
                iterations.append(_format_number(nrun, 'run'))
            if nsample:
                text = _format_number(nsample, 'sample')
                iterations.append(text)
            if loops:
                iterations.append(_format_number(loops, 'loop'))
            iterations = ' x '.join(iterations)
            if verbose and warmup:
                iterations += '; %s' % _format_number(warmup, 'warmup')

            text = self._formatter(samples, verbose)
            if iterations:
                text = '%s (%s)' % (text, iterations)
        else:
            text = '<no run>'
        if self.name:
            text = '%s: %s' % (self.name, text)
        return text

    def __str__(self):
        return self.format()

    @classmethod
    def _from_json(cls, data):
        version = data.get('version')
        if version != 1:
            raise ValueError("version %r not supported" % version)

        runs = [RunResult._from_json(run) for run in data['runs']]
        metadata = data['metadata']
        name = data.get('name')
        return cls(runs=runs, name=name, metadata=metadata)

    @classmethod
    def from_json(cls, text):
        json = _import_json()
        data = json.loads(text)

        if 'results' not in data:
            raise ValueError("JSON doesn't contain results")
        data = data['results']

        return cls._from_json(data)

    def json(self):
        json = _import_json()
        runs = [run._json() for run in self.runs]
        data = {'version': 1,
                'runs': runs,
                'metadata': self.metadata}
        if self.name:
            data['name'] = self.name
        # FIXME: export formatter
        return json.dumps({'results': data})


class RunResult:
    def __init__(self, samples=None, warmups=None, loops=None, formatter=None):
        if not(loops is None or (isinstance(loops, int) and loops >= 0)):
            raise TypeError("loops must be an int >= 0 or None")
        if (samples is not None
        and any(not(isinstance(value, float) and value >= 0)
                for value in samples)):
            raise TypeError("samples must be a list of float >= 0")
        if (warmups is not None
        and any(not(isinstance(value, float) and value >= 0)
                for value in warmups)):
            raise TypeError("warmups must be a list of float >= 0")

        self.samples = []
        if samples is not None:
            self.samples.extend(samples)
        self.loops = loops
        self.warmups = []
        if warmups is not None:
            self.warmups.extend(warmups)
        if formatter is not None:
            self._formatter = formatter
        else:
            self._formatter = _format_run_result

    def _format_sample(self, sample, verbose=False):
        return self._formatter([sample], verbose)

    def format(self, verbose=False):
        return self._formatter(self.samples, verbose)

    def __str__(self):
        return self.format()

    @classmethod
    def _from_json(cls, data):
        version = data.get('version')
        if version != 1:
            raise ValueError("version %r not supported" % version)

        samples = data['samples']
        warmups = data['warmups']
        loops = data.get('loops')
        return cls(loops=loops, samples=samples, warmups=warmups)

    @classmethod
    def from_json(cls, text):
        json = _import_json()
        data = json.loads(text)

        if 'run_result' not in data:
            raise ValueError("JSON doesn't contain run_result")
        data = data['run_result']

        return cls._from_json(data)

    def _json(self):
        data = {'version': 1,
                'samples': self.samples,
                'warmups': self.warmups}
        if self.loops is not None:
            data['loops'] = self.loops
        # FIXME: export formatter
        return data

    def json(self):
        json = _import_json()
        return json.dumps({'run_result': self._json()})


class TextRunner:
    def __init__(self, runs, warmups=1):
        self.result = RunResult()
        self.warmups = warmups
        self.runs = runs
        self.json = False
        self.timer = perf_counter

    def _stream(self):
        return sys.stderr if self.json else None

    def range(self):
        # FIXME: use six.range
        for warmup in range(self.warmups):
            yield (True, warmup)
        for run in range(self.runs):
            yield (False, run)

    def add(self, is_warmup, run, sample):
        if is_warmup:
            self.result.warmups.append(sample)
        else:
            self.result.samples.append(sample)

        text = self.result._format_sample(sample)
        if is_warmup:
            text = "Warmup %s: %s" % (1 + run, text)
        else:
            text = "Run %s: %s" % (1 + run, text)
        print(text, file=self._stream())

    def bench_func(self, func, *args):
        # FIXME: use functools.partial() to not use the slow "func(*args)"
        # unpacking at each iteration?
        if self.result.loops is not None:
            print(_format_number(self.result.loops, 'loop'),
                  file=self._stream())
        for is_warmup, run in self.range():
            t1 = self.timer()
            func(*args)
            t2 = self.timer()
            self.add(is_warmup, run, t2 - t1)

    def done(self):
        sys.stderr.flush()
        if self.json:
            print(self.result.json())
