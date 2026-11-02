"""CSV that's safe to open in Excel. A cell starting with = + - @ runs as a formula there, so a name someone typed
(a buyer called =HYPERLINK(…)) could fetch or leak data on the computer of whoever opens the download.
Such text gets a leading ' which keeps it plain text. Plain numbers and phone numbers stay as they are."""
import csv
import re

RISKY = ("=", "+", "-", "@", "\t", "\r")
PLAIN_NUMBER = re.compile(r"[+-]?[\d\s().,-]+\Z")


def safe_cell(value):
    if isinstance(value, str) and value.startswith(RISKY) and not PLAIN_NUMBER.match(value):
        return "'" + value
    return value


class _Writer:
    def __init__(self, target):
        self._writer = csv.writer(target)

    def writerow(self, row):
        return self._writer.writerow([safe_cell(v) for v in row])

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)


def safe_writer(target):
    """Use in place of csv.writer for anything a person may download."""
    return _Writer(target)
