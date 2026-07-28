"""Match-format helpers shared by services and presentation code."""

from __future__ import annotations


LIMIT_UNITS = ("balls", "overs")


def legal_balls_for_limit(
    innings_limit: int,
    *,
    limit_unit: str,
    balls_per_over: int | None,
) -> int:
    """Convert a format allocation into canonical legal balls.

    :param innings_limit: Positive allocation expressed in the format's unit.
    :param limit_unit: Format unit, either ``balls`` or ``overs``.
    :param balls_per_over: Deliveries in an over for an over-based format.
    :return: The allocation as a canonical legal-ball count.
    :raises ValueError: If the allocation or format configuration is invalid.
    """
    # Booleans are excluded because an allocation is a genuine whole number.
    if isinstance(innings_limit, bool) or not isinstance(innings_limit, int):
        raise ValueError("Innings limit must be a whole number.")
    if innings_limit <= 0:
        raise ValueError("Innings limit must be greater than zero.")
    if limit_unit not in LIMIT_UNITS:
        raise ValueError("Limit unit must be balls or overs.")
    if limit_unit == "balls":
        # A ball-based allocation is already stored in the canonical unit.
        return innings_limit
    if (
        isinstance(balls_per_over, bool)
        or not isinstance(balls_per_over, int)
        or balls_per_over <= 0
    ):
        raise ValueError("Balls per over must be a positive whole number.")

    # Over allocations contain only complete overs at match level.
    return innings_limit * balls_per_over


def format_delivery_count(
    legal_balls: int,
    *,
    limit_unit: str,
    balls_per_over: int | None,
) -> str:
    """Format a canonical legal-ball count for its match format.

    :param legal_balls: Number of legal deliveries completed.
    :param limit_unit: Format unit, either ``balls`` or ``overs``.
    :param balls_per_over: Deliveries in an over for an over-based format.
    :return: A delivery count in balls or cricket over notation.
    :raises ValueError: If the count or format configuration is invalid.
    """
    # Reject booleans explicitly because they otherwise behave like integers.
    if isinstance(legal_balls, bool) or not isinstance(legal_balls, int):
        raise ValueError("Legal balls must be a whole number.")
    if legal_balls < 0:
        raise ValueError("Legal balls cannot be negative.")
    if limit_unit not in LIMIT_UNITS:
        raise ValueError("Limit unit must be balls or overs.")
    if limit_unit == "balls":
        # Hundred progress remains expressed using the existing canonical unit.
        return f"{legal_balls} balls"
    if (
        isinstance(balls_per_over, bool)
        or not isinstance(balls_per_over, int)
        or balls_per_over <= 0
    ):
        raise ValueError("Balls per over must be a positive whole number.")

    # The dot separates complete overs from balls; it is not a decimal fraction.
    complete_overs, balls_in_over = divmod(legal_balls, balls_per_over)
    return f"{complete_overs}.{balls_in_over} overs"
