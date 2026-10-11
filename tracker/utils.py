"""Small pure helpers: day numbering and number formatting."""
from datetime import timedelta
from decimal import Decimal

WEEK_LENGTH = 7


def day_number(start_date, on_date):
    """Day 1 is the start date. Calculated from the date difference only."""
    return (on_date - start_date).days + 1


def day_label(number):
    """Human label for a day number. Dates before the start date have no day."""
    return f"Day {number}" if number >= 1 else "Before Day 1"


def week_window(today):
    """The current seven calendar days: today and the six days before it."""
    return today - timedelta(days=WEEK_LENGTH - 1), today


def format_decimal(value):
    """Decimal('7.500') -> '7.5', Decimal('10.000') -> '10'."""
    if value is None:
        return ""
    return format(Decimal(value).normalize(), "f")
