# Bonsai Sketch Mode - direct-modelling interaction for Bonsai
# Copyright (C) 2026 Innovations & Integrations
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Placing drawings in one building, on evidence rather than by accident.

Two plans of the same building rarely share coordinates: each sheet has
its own origin, sometimes its own rotation. Aligning them by bounding
boxes would work until the day it silently didn't, so alignment here is
a first-class compiler pass with the same discipline as everything else:
a :class:`~.ir.TransformCandidate` per drawing, earned from evidence,
carrying the correspondences that earned it, the residual left over, and
a status that says what kind of claim it is.

The evidence this pass reads today is the strongest a drawing itself
offers: **named grid intersections**. Grid A meets grid 1 at one point
on every sheet that draws them, so shared names give point
correspondences, and a rigid fit (rotation and translation; scale fixed
at one, because unit normalisation already happened and a scale that is
not one is a wrong drawing, not a parameter) drops out of Kabsch over
those points. The residual is reported, and it gates the status:
ACCEPTED within tolerance, NEEDS_REVIEW when the fit is loose,
UNRESOLVED when fewer than two shared crossings exist -- at which point
a person states the correspondence, and the transform says a person did.

What this never does: a fit computed from geometry matching never
masquerades as surveyed truth. The evidence lines name grid bubbles,
not survey marks, and consumers can tell the difference.
"""

from __future__ import annotations

import math
from typing import Optional

from . import drawings, ir

#: Residual at or under this is drafting precision: ACCEPTED.
ACCEPT_RESIDUAL = 0.005

#: Residual under this still fits, but loosely enough that a person
#: should look: NEEDS_REVIEW. Above it the correspondence is wrong.
REVIEW_RESIDUAL = 0.050


def rigid_fit(pairs) -> Optional[tuple]:
    """(rotation degrees, translation, residual) mapping local -> reference.

    Kabsch in two dimensions over exact correspondences: centre both
    point sets, take the cross-covariance angle, then the translation
    that superposes the centroids. Needs two pairs; one point fixes
    nothing but a translation somebody must still confirm.
    """
    if len(pairs) < 2:
        return None
    n = float(len(pairs))
    lcx = sum(p[0][0] for p in pairs) / n
    lcy = sum(p[0][1] for p in pairs) / n
    rcx = sum(p[1][0] for p in pairs) / n
    rcy = sum(p[1][1] for p in pairs) / n
    sxx = sxy = syx = syy = 0.0
    for (lx, ly), (rx, ry) in pairs:
        dlx, dly = lx - lcx, ly - lcy
        drx, dry = rx - rcx, ry - rcy
        sxx += dlx * drx
        sxy += dlx * dry
        syx += dly * drx
        syy += dly * dry
    angle = math.atan2(sxy - syx, sxx + syy)
    c, s = math.cos(angle), math.sin(angle)
    tx = rcx - (lcx * c - lcy * s)
    ty = rcy - (lcx * s + lcy * c)
    residual = 0.0
    for (lx, ly), (rx, ry) in pairs:
        mx, my = lx * c - ly * s + tx, lx * s + ly * c + ty
        residual = max(residual, math.hypot(mx - rx, my - ry))
    return math.degrees(angle), (tx, ty), residual


def to_reference(candidate, reference, transform_id: str) -> ir.TransformCandidate:
    """One drawing's transform into the reference drawing's coordinates.

    The reference drawing itself gets the identity, ACCEPTED on its own
    testimony: something has to hold the datum, and saying which sheet
    does is part of the record.
    """
    transform = ir.TransformCandidate(transform_id, candidate.id)
    if candidate.id == reference.id:
        transform.status = "ACCEPTED"
        transform.residual = 0.0
        transform.evidence.append("the reference sheet: identity holds the datum")
        candidate.transform = transform.id
        return transform

    ours = drawings.intersections(candidate)
    theirs = drawings.intersections(reference)
    shared = sorted(set(ours) & set(theirs))
    if len(shared) < 2:
        transform.evidence.append(
            f"{len(shared)} shared named grid crossing(s) with {reference.id}; two are needed")
        transform.status = "UNRESOLVED"
        candidate.diagnostics.append(
            f"no alignment earned against {reference.id} -- state the correspondence by hand")
        return transform

    fit = rigid_fit([(ours[key], theirs[key]) for key in shared])
    rotation, translation, residual = fit
    transform.rotation_degrees = rotation
    transform.translation = translation
    transform.residual = residual
    for key in shared:
        transform.evidence.append(
            f"grid {key[0]}/{key[1]} here matches grid {key[0]}/{key[1]} on {reference.id}")
    transform.evidence.append(
        "earned from grid bubbles, not survey marks -- geometry-matched, not surveyed")
    if residual <= ACCEPT_RESIDUAL:
        transform.status = "ACCEPTED"
    elif residual <= REVIEW_RESIDUAL:
        transform.status = "NEEDS_REVIEW"
        candidate.diagnostics.append(
            f"alignment residual {residual * 1000:.1f} mm is loose -- review {transform.id}")
    else:
        transform.status = "UNRESOLVED"
        candidate.diagnostics.append(
            f"grids match by name but not by geometry (residual {residual * 1000:.0f} mm)"
            " -- the correspondence is wrong somewhere")
    candidate.transform = transform.id if transform.status != "UNRESOLVED" else None
    return transform
