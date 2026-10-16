# UrbanNav: recorded IMU and real GNSS outages

The first dataset here with a real GNSS receiver and a real GNSS outage. The reader is `navkit.urbannav_data`, the
measurements below come from `navkit urbannav check`, and the decision behind the dataset is
[ADR-0026](adr/0026-urbannav-as-a-real-gnss-dataset.md). The filter has not been run on it yet. This page says what
the files contain and what that means for a run.

## Read this before quoting anything

- **This page is about the data, not about the filter.** No NEES, coverage or error of the filter appears here.
- **The data is not in the repository (S2).** It is fetched with `navkit urbannav fetch`. The table below comes from a
  committed CSV of aggregate quantities, so CI can check the page and cannot reread the data. The data is MIT licensed
  by its authors, who ask for a citation of Hsu et al. (2023), NAVIGATION.
- **The receiver is the u-blox F9P**, through its own NMEA position fixes. The NovAtel and F9P RINEX files hold raw
  observations only, and positions from them would need navigation files that the download does not contain.
- **The outage rule reads the receiver's fix flag and nothing else.** An epoch is denied when the fix quality is 0 or
  it has no position, and time with no epoch is denied. It was written before any filter ran on this data, and it
  does not look at the reference, the satellite count or how wrong a fix turns out to be.
- **A fix marked valid can be badly wrong.** In the seconds before the receiver gives up, and in the first seconds
  after it recovers, the fixes carry a valid flag and differ from the reference by tens of metres (rows below).
  The rule does not cover them. The filter's gate has to catch them, and how well it does is a result.
- **The reference is an estimate.** It is a post-processed NovAtel SPAN-CPT solution at 1 Hz. Through the tunnel it is
  carried by that unit's inertial sensors alone, and its error there is unknown. Scores against it inside the outage
  are scores against an estimate. Its quality column has six codes, and what each means has not been confirmed.
- **The fixes are not the simulated ones.** They differ from the reference by metres, with a long tail, where the
  simulated GNSS of the other pages differs by a fraction of a metre. The vertical difference is a bias that changes
  between the two sides of the outage, so the height is not usable as given.
- **Not related here:** the antenna positions and the rotation between the NovAtel and Xsens units. The reference
  attitude belongs to the NovAtel unit, so no initial attitude can be taken from it without that rotation.

## What the files contain

<!-- urbannav-data:start -->

| Sequence | Quantity | Value | Unit |
|---|---|---:|---|
| tunnel1 | IMU samples | 159459 | count |
| tunnel1 | IMU time span | 398.6 | s |
| tunnel1 | IMU rate, median | 400.6 | Hz |
| tunnel1 | IMU longest gap | 9.227 | ms |
| tunnel1 | Reference epochs | 401 | count |
| tunnel1 | Reference spacing, median | 1 | s |
| tunnel1 | Distinct reference quality codes | 6 | count |
| tunnel1 | Reference-to-IMU clock offset | 0 | s |
| tunnel1 | Offset search step | 0.01 | s |
| tunnel1 | F9P fixes (GGA sentences) | 401 | count |
| tunnel1 | Epochs with no fix | 151 | count |
| tunnel1 | Outages by the rule | 1 | count |
| tunnel1 | First outage, start (IMU clock) | 137.5 | s |
| tunnel1 | First outage, end (IMU clock) | 288.5 | s |
| tunnel1 | First outage, length | 151 | s |
| tunnel1 | Fix horizontal difference from the reference, median | 1.999 | m |
| tunnel1 | Fix horizontal difference, 95th percentile | 11.33 | m |
| tunnel1 | Fix horizontal difference, largest | 83.25 | m |
| tunnel1 | Last valid fix before the outage, difference | 83.25 | m |
| tunnel1 | Largest difference in the last valid fixes before the outage | 83.25 | m |
| tunnel1 | First valid fix after the outage, difference | 52.76 | m |
| tunnel1 | Largest difference in the first valid fixes after the outage | 52.76 | m |
| tunnel1 | Mean fix height minus reference height, before the outage | -7.63 | m |
| tunnel1 | Mean fix height minus reference height, after the outage | 1.164 | m |

<!-- urbannav-data:end -->

## What it shows

1. **One real outage.** The F9P reports no fix for one continuous stretch, and the rule finds a single outage there.
2. **The two clocks agree.** The offset between the reference and the IMU is within one search step of zero. The
   method was checked by shifting a synthetic reference by known amounts, and it recovered each. The 1 Hz reference
   limits how sharply it can say so, and the estimate uses only the yaw axis.
3. **The edges of the outage are the hard part.** The fixes just before the receiver gives up are the worst of the
   valid ones, and the first fixes after it recovers are wrong too.

## What follows

A run needs four things that this page does not settle: the rotation between the NovAtel and Xsens units for the start
attitude, a way to give the filter real fixes in place of simulated ones, a noise setting for fixes that are metres
off, and a decision on the vertical axis. See [ADR-0026](adr/0026-urbannav-as-a-real-gnss-dataset.md).
