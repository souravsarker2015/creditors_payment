# Form fields show dates as 2026-10-07 in every language: the date picker reads
# that form, and Django's Bangla default (07/10/2026) was read as a different
# date. People still see "7 Oct 2026" in the picker; dd/mm/yyyy typed by hand
# is still accepted.
DATE_INPUT_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y"]
DATETIME_INPUT_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]
