"""
Portions of this module are adapted from qreki-dart by Akito Nishiyama
(https://github.com/Anishishi/qreki-dart), distributed under the MIT License.

MIT License

Copyright (c) 2024 Akito Nishiyama

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

JST_OFFSET_DAYS = 9.0 / 24.0
DEG_TO_RAD = math.pi / 180.0
ROKUYO_LABELS = ("大安", "赤口", "先勝", "友引", "先負", "仏滅")
ROKUYO_SHORT_LABELS = {
    "大安": "安",
    "赤口": "赤",
    "先勝": "勝",
    "友引": "友",
    "先負": "負",
    "仏滅": "仏",
}


@dataclass(frozen=True, slots=True)
class KyurekiDate:
    year: int
    month: int
    leap_month: bool
    day: int


@dataclass(frozen=True, slots=True)
class RokuyoDay:
    kyureki: KyurekiDate
    label: str
    short_label: str


def gregorian_to_kyureki(value: date) -> KyurekiDate:
    tm0 = value.toordinal() + 1721424
    tm = float(tm0)

    chu = [_before_nibun_from_jd(tm, JST_OFFSET_DAYS)]
    for _ in range(1, 4):
        chu.append(_chuki_from_jd(chu[-1][0] + 32.0, JST_OFFSET_DAYS))

    saku = [_saku_from_jd(chu[0][0], JST_OFFSET_DAYS)]
    for _ in range(1, 5):
        next_saku = _saku_from_jd(saku[-1] + 30.0, JST_OFFSET_DAYS)
        if abs(int(saku[-1]) - int(next_saku)) <= 26:
            next_saku = _saku_from_jd(saku[-1] + 35.0, JST_OFFSET_DAYS)
        saku.append(next_saku)

    if int(saku[1]) <= int(chu[0][0]):
        saku = saku[1:] + [_saku_from_jd(saku[3] + 35.0, JST_OFFSET_DAYS)]
    elif int(saku[0]) > int(chu[0][0]):
        saku = [_saku_from_jd(saku[0] - 27.0, JST_OFFSET_DAYS)] + saku[:4]

    has_leap_month = int(saku[4]) <= int(chu[3][0])
    lunar_months = [[0, 0, 0] for _ in range(5)]
    lunar_months[0][0] = int(chu[0][1] / 30.0) + 2
    lunar_months[0][2] = int(saku[0])

    for index in range(1, 5):
        if has_leap_month and index != 1:
            if int(chu[index - 1][0]) <= int(saku[index - 1]) or int(chu[index - 1][0]) >= int(
                saku[index]
            ):
                lunar_months[index - 1][0] = lunar_months[index - 2][0]
                lunar_months[index - 1][1] = 1
                lunar_months[index - 1][2] = int(saku[index - 1])
                has_leap_month = False
        lunar_months[index][0] = lunar_months[index - 1][0] + 1
        if lunar_months[index][0] > 12:
            lunar_months[index][0] -= 12
        lunar_months[index][2] = int(saku[index])

    match_index = 0
    state = 0
    for index, (_, _, month_start) in enumerate(lunar_months):
        if tm0 < month_start:
            state = 1
            match_index = index
            break
        if tm0 == month_start:
            state = 2
            match_index = index
            break
    else:
        match_index = len(lunar_months) - 1

    if state in {0, 1}:
        match_index -= 1

    kyureki_year = value.year
    kyureki_month = lunar_months[match_index][0]
    kyureki_leap_month = bool(lunar_months[match_index][1])
    kyureki_day = tm0 - lunar_months[match_index][2] + 1

    if kyureki_month > 9 and kyureki_month > value.month:
        kyureki_year -= 1

    return KyurekiDate(
        year=kyureki_year,
        month=kyureki_month,
        leap_month=kyureki_leap_month,
        day=kyureki_day,
    )


def rokuyo_from_kyureki(value: KyurekiDate) -> RokuyoDay:
    label = ROKUYO_LABELS[(value.month + value.day) % 6]
    return RokuyoDay(
        kyureki=value,
        label=label,
        short_label=ROKUYO_SHORT_LABELS[label],
    )


def rokuyo_for_date(value: date) -> RokuyoDay:
    return rokuyo_from_kyureki(gregorian_to_kyureki(value))


def _longitude_of_sun(t: float) -> float:
    longitude = 0.0
    for frequency, phase, coefficient in (
        (31557.0, 161.0, 0.0004),
        (29930.0, 48.0, 0.0004),
        (2281.0, 221.0, 0.0005),
        (155.0, 118.0, 0.0005),
        (33718.0, 316.0, 0.0006),
        (9038.0, 64.0, 0.0007),
        (3035.0, 110.0, 0.0007),
        (65929.0, 45.0, 0.0007),
        (22519.0, 352.0, 0.0013),
        (45038.0, 254.0, 0.0015),
        (445267.0, 208.0, 0.0018),
        (19.0, 159.0, 0.0018),
        (32964.0, 158.0, 0.0020),
        (71998.1, 265.1, 0.0200),
    ):
        angle = (frequency * t + phase) % 360.0
        longitude += coefficient * math.cos(DEG_TO_RAD * angle)

    angle = (35999.05 * t + 267.52) % 360.0
    longitude -= 0.0048 * t * math.cos(DEG_TO_RAD * angle)
    longitude += 1.9147 * math.cos(DEG_TO_RAD * angle)
    angle = (36000.7695 * t) % 360.0
    angle = (angle + 280.4659) % 360.0
    return (longitude + angle) % 360.0


def _longitude_of_moon(t: float) -> float:
    longitude = 0.0
    for frequency, phase, coefficient in (
        (2322131.0, 191.0, 0.0003),
        (4067.0, 70.0, 0.0003),
        (549197.0, 220.0, 0.0003),
        (1808933.0, 58.0, 0.0003),
        (349472.0, 337.0, 0.0003),
        (381404.0, 354.0, 0.0003),
        (958465.0, 340.0, 0.0003),
        (12006.0, 187.0, 0.0004),
        (39871.0, 223.0, 0.0004),
        (509131.0, 242.0, 0.0005),
        (1745069.0, 24.0, 0.0005),
        (1908795.0, 90.0, 0.0005),
        (2258267.0, 156.0, 0.0006),
        (111869.0, 38.0, 0.0006),
        (27864.0, 127.0, 0.0007),
        (485333.0, 186.0, 0.0007),
        (405201.0, 50.0, 0.0007),
        (790672.0, 114.0, 0.0007),
        (1403732.0, 98.0, 0.0008),
        (858602.0, 129.0, 0.0009),
        (1920802.0, 186.0, 0.0011),
        (1267871.0, 249.0, 0.0012),
        (1856938.0, 152.0, 0.0016),
        (401329.0, 274.0, 0.0018),
        (341337.0, 16.0, 0.0021),
        (71998.0, 85.0, 0.0021),
        (990397.0, 357.0, 0.0021),
        (818536.0, 151.0, 0.0022),
        (922466.0, 163.0, 0.0023),
        (99863.0, 122.0, 0.0024),
        (1379739.0, 17.0, 0.0026),
        (918399.0, 182.0, 0.0027),
        (1934.0, 145.0, 0.0028),
        (541062.0, 259.0, 0.0037),
        (1781068.0, 21.0, 0.0038),
        (133.0, 29.0, 0.0040),
        (1844932.0, 56.0, 0.0040),
        (1331734.0, 283.0, 0.0040),
        (481266.0, 205.0, 0.0050),
        (31932.0, 107.0, 0.0052),
        (926533.0, 323.0, 0.0068),
        (449334.0, 188.0, 0.0079),
        (826671.0, 111.0, 0.0085),
        (1431597.0, 315.0, 0.0100),
        (1303870.0, 246.0, 0.0107),
        (489205.0, 142.0, 0.0110),
        (1443603.0, 52.0, 0.0125),
        (75870.0, 41.0, 0.0154),
        (513197.9, 222.5, 0.0304),
        (445267.1, 27.9, 0.0347),
        (441199.8, 47.4, 0.0409),
        (854535.2, 148.2, 0.0458),
        (1367733.1, 280.7, 0.0533),
        (377336.3, 13.2, 0.0571),
        (63863.5, 124.2, 0.0588),
        (966404.0, 276.5, 0.1144),
        (35999.05, 87.53, 0.1851),
        (954397.74, 179.93, 0.2136),
        (890534.22, 145.7, 0.6583),
        (413335.35, 10.74, 1.2740),
        (477198.868, 44.963, 6.2888),
    ):
        angle = (frequency * t + phase) % 360.0
        longitude += coefficient * math.cos(DEG_TO_RAD * angle)

    angle = (481267.8809 * t) % 360.0
    angle = (angle + 218.3162) % 360.0
    return (longitude + angle) % 360.0


def _before_nibun_from_jd(tm: float, time_zone: float) -> tuple[float, float]:
    tm2 = tm - math.floor(tm)
    tm1 = math.floor(tm)
    tm2 -= time_zone

    t = (tm2 + 0.5) / 36525.0 + (tm1 - 2451545.0) / 36525.0
    solar_longitude = _longitude_of_sun(t)
    target_longitude = solar_longitude - solar_longitude % 90.0

    delta_t1 = 0.0
    delta_t2 = 1.0
    while abs(delta_t1 + delta_t2) > 1.0 / 86400.0:
        t = (tm2 + 0.5) / 36525.0 + (tm1 - 2451545.0) / 36525.0
        solar_longitude = _longitude_of_sun(t)
        delta_longitude = solar_longitude - target_longitude
        if delta_longitude > 180.0:
            delta_longitude -= 360.0
        elif delta_longitude < -180.0:
            delta_longitude += 360.0

        correction = delta_longitude * 365.2 / 360.0
        delta_t2 = math.floor(correction)
        delta_t1 = correction - delta_t2

        tm1 -= delta_t1
        tm2 -= delta_t2
        if tm2 < 0.0:
            tm2 += 1.0
            tm1 -= 1.0

    return tm1 + tm2 + time_zone, target_longitude


def _chuki_from_jd(tm: float, time_zone: float) -> tuple[float, float]:
    tm2 = tm - math.floor(tm)
    tm1 = math.floor(tm)
    tm2 -= time_zone

    t = (tm2 + 0.5) / 36525.0 + (tm1 - 2451545.0) / 36525.0
    solar_longitude = _longitude_of_sun(t)
    target_longitude = solar_longitude - solar_longitude % 30.0

    delta_t1 = 0.0
    delta_t2 = 1.0
    while abs(delta_t1 + delta_t2) > 1.0 / 86400.0:
        t = (tm2 + 0.5) / 36525.0 + (tm1 - 2451545.0) / 36525.0
        solar_longitude = _longitude_of_sun(t)
        delta_longitude = solar_longitude - target_longitude
        if delta_longitude > 180.0:
            delta_longitude -= 360.0
        elif delta_longitude < -180.0:
            delta_longitude += 360.0

        correction = delta_longitude * 365.2 / 360.0
        delta_t2 = math.floor(correction)
        delta_t1 = correction - delta_t2

        tm1 -= delta_t1
        tm2 -= delta_t2
        if tm2 < 0.0:
            tm2 += 1.0
            tm1 -= 1.0

    return tm1 + tm2 + time_zone, target_longitude


def _saku_from_jd(tm: float, time_zone: float) -> float:
    tm2 = tm - math.floor(tm)
    tm1 = math.floor(tm)
    tm2 -= time_zone

    delta_t1 = 0.0
    delta_t2 = 1.0
    for loop_count in range(1, 30):
        t = (tm2 + 0.5) / 36525.0 + (tm1 - 2451545.0) / 36525.0
        solar_longitude = _longitude_of_sun(t)
        lunar_longitude = _longitude_of_moon(t)
        delta_longitude = lunar_longitude - solar_longitude

        if loop_count == 1 and delta_longitude < 0.0:
            delta_longitude %= 360.0
        elif 0.0 <= solar_longitude <= 20.0 and lunar_longitude >= 300.0:
            delta_longitude %= 360.0
            delta_longitude = 360.0 - delta_longitude
        elif abs(delta_longitude) > 40.0:
            delta_longitude %= 360.0

        correction = delta_longitude * 29.530589 / 360.0
        delta_t2 = math.floor(correction)
        delta_t1 = correction - delta_t2

        tm1 -= delta_t1
        tm2 -= delta_t2
        if tm2 < 0.0:
            tm2 += 1.0
            tm1 -= 1.0

        if abs(delta_t1 + delta_t2) <= 1.0 / 86400.0:
            break
        if loop_count == 15:
            tm1 = tm - 26.0
            tm2 = 0.0

    return tm1 + tm2 + time_zone
