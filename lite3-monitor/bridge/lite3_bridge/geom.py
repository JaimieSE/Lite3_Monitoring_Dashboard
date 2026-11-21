"""Minimal rigid-transform maths (no numpy dependency)."""
from __future__ import annotations

import math
from typing import Tuple

Vec3 = Tuple[float, float, float]
Quat = Tuple[float, float, float, float]  # x, y, z, w


def quat_mul(a: Quat, b: Quat) -> Quat:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def quat_rotate(q: Quat, v: Vec3) -> Vec3:
    qx, qy, qz, qw = q
    vx, vy, vz = v
    # t = 2 * cross(q.xyz, v)
    tx = 2.0 * (qy * vz - qz * vy)
    ty = 2.0 * (qz * vx - qx * vz)
    tz = 2.0 * (qx * vy - qy * vx)
    return (
        vx + qw * tx + (qy * tz - qz * ty),
        vy + qw * ty + (qz * tx - qx * tz),
        vz + qw * tz + (qx * ty - qy * tx),
    )


def compose(t1: Vec3, q1: Quat, t2: Vec3, q2: Quat) -> Tuple[Vec3, Quat]:
    """Return T1 * T2."""
    r = quat_rotate(q1, t2)
    return (t1[0] + r[0], t1[1] + r[1], t1[2] + r[2]), quat_mul(q1, q2)


def yaw_from_quat(q: Quat) -> float:
    x, y, z, w = q
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def quat_from_yaw(yaw: float) -> Quat:
    return (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))


def wrap_angle(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi
