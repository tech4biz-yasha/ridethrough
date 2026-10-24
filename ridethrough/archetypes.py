"""Facility archetypes.

These are configurations, not measurements. Each default below is either
taken from a public source, named here, or is a round engineering figure
chosen so the archetypes differ in the way real facilities differ. None of
them describes a specific site.

Where the numbers come from:

- Server PSU hold-up of 10 ms at full load. Dell, US patent 9,213,385,
  "Supplemental power system for power excursions", states that PSU power
  density tripled over three server generations and that the result has been
  a hold-up time reduction to approximately 10 ms at full load, which it
  calls the minimum that lets a PDU switch between rails.

- Undervoltage protection pickup near 0.85 pu. Reported as Dominion's
  approach in "Best Practices for Large Load Interconnections: A North
  American Perspective on Data Centers", arXiv 2601.12686, which describes
  requiring ride-through of several reclosing shots with undervoltage pickup
  near 85%.

- 400 V nominal DC bus with a 320 V cut-off is a round figure for a
  wide-input server PSU and is not from a cited source.

- UPS DC bus hold-up and battery energy are round figures.
"""

from __future__ import annotations

from .facility import Battery, Facility, Protection, Stage

SERVER_PSU = Stage(
    name="server PSU",
    hold_up_seconds=0.010,
    nominal_dc_volts=400.0,
    cutoff_dc_volts=320.0,
    current_limit_pu=1.5,
    restart_seconds=120.0,
)

UPS_DC_BUS = Stage(
    name="UPS DC bus",
    hold_up_seconds=0.050,
    nominal_dc_volts=800.0,
    cutoff_dc_volts=640.0,
    current_limit_pu=1.2,
)

FIVE_MINUTE_BATTERY = Battery(energy_seconds=300.0, transfer_seconds=0.002)

NO_PROTECTION = Protection()
UNDERVOLTAGE_RELAY = Protection(pickup_pu=0.85, delay_seconds=0.1)


def no_ups(rated_power_w: float = 50e6) -> Facility:
    """Servers fed straight from the utility. No stored energy beyond the PSUs."""
    return Facility(
        name="no UPS",
        rated_power_w=rated_power_w,
        psu=SERVER_PSU,
        ups=None,
        battery=None,
        protection=NO_PROTECTION,
        notes="Servers hold power for the PSU hold-up time and no longer.",
    )


def no_ups_with_relay(rated_power_w: float = 50e6) -> Facility:
    """The same, with an undervoltage relay that disconnects the site."""
    return Facility(
        name="no UPS, undervoltage relay at 0.85 pu",
        rated_power_w=rated_power_w,
        psu=SERVER_PSU,
        ups=None,
        battery=None,
        protection=UNDERVOLTAGE_RELAY,
        notes="Protection decides the outcome before the PSUs ever get a say.",
    )


def double_conversion_ups(rated_power_w: float = 50e6) -> Facility:
    """Double conversion UPS, DC bus only, no battery support."""
    return Facility(
        name="double conversion UPS, no battery",
        rated_power_w=rated_power_w,
        psu=SERVER_PSU,
        ups=UPS_DC_BUS,
        battery=None,
        protection=NO_PROTECTION,
        notes="The UPS DC bus is the only reservoir between grid and servers.",
    )


def ups_with_battery(rated_power_w: float = 50e6) -> Facility:
    """Double conversion UPS with five minutes of battery on the DC bus."""
    return Facility(
        name="double conversion UPS with battery",
        rated_power_w=rated_power_w,
        psu=SERVER_PSU,
        ups=UPS_DC_BUS,
        battery=FIVE_MINUTE_BATTERY,
        protection=NO_PROTECTION,
        notes="Battery decouples the servers from the grid for the whole event.",
    )


def ups_with_load_reduction(rated_power_w: float = 50e6) -> Facility:
    """UPS with battery, and an IT load that reduces in proportion to the sag.

    This is the behaviour ERCOT Section 2.15(3)(c) contemplates: the facility
    may reduce consumption during the sag provided it comes back in time.
    """
    return Facility(
        name="UPS with battery and proportional load reduction",
        rated_power_w=rated_power_w,
        psu=SERVER_PSU,
        ups=UPS_DC_BUS,
        battery=FIVE_MINUTE_BATTERY,
        protection=NO_PROTECTION,
        reduces_load_with_voltage=True,
        notes="Reduces IT power with voltage, which keeps current off the ceiling.",
    )


ARCHETYPES = {
    "no-ups": no_ups,
    "no-ups-relay": no_ups_with_relay,
    "ups": double_conversion_ups,
    "ups-battery": ups_with_battery,
    "ups-battery-reduction": ups_with_load_reduction,
}


def ups_with_sag_counter(rated_power_w: float = 50e6) -> Facility:
    """UPS with battery, and a control scheme that transfers after four sags
    inside a minute.

    This is the northern Virginia failure mode. The site survives any single
    sag and then gives up on a train of them. ERCOT Section 2.15(7) now
    forbids exactly this where the facility is required to ride each one
    through. The count of four is chosen to show the behaviour and is not
    taken from any vendor's settings.
    """
    return Facility(
        name="UPS with battery and a four-sag transfer scheme",
        rated_power_w=rated_power_w,
        psu=SERVER_PSU,
        ups=UPS_DC_BUS,
        battery=FIVE_MINUTE_BATTERY,
        protection=NO_PROTECTION,
        sag_count_trip=4,
        sag_count_window_s=60.0,
        notes="Passes every single-sag test and fails a reclosing train.",
    )


ARCHETYPES["ups-sag-counter"] = ups_with_sag_counter
