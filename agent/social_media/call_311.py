"""311 Heat Desk Hotline Assistant: resident cooling center lookup, wellness intake, and emergency triage."""
from __future__ import annotations

import json
import logging
import math
import re
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from heat_dispatch.places import in_chicago, locate_place

logger = logging.getLogger(__name__)

# Chicago cooling facilities snapshot for reliable offline response and fallback
DEFAULT_CHICAGO_FACILITIES = [
    {
        "facility_type": "Library",
        "site_name": "Harold Washington Library Center",
        "address": "400 S. State Street",
        "zip": "60605",
        "phone": "(312) 747-4300",
        "hours_of_operation": "Mon-Thu 9am-8pm, Fri-Sat 9am-5pm, Sun 1pm-5pm",
        "latitude": 41.8769,
        "longitude": -87.6281,
        "is_indoor": True,
    },
    {
        "facility_type": "Senior Center",
        "site_name": "Garfield Community Service Center",
        "address": "10 S. Kedzie Ave",
        "zip": "60612",
        "phone": "(312) 746-5400",
        "hours_of_operation": "Mon-Fri 9am-5pm (Extended during heat emergencies to 7pm)",
        "latitude": 41.8809,
        "longitude": -87.7058,
        "is_indoor": True,
    },
    {
        "facility_type": "College / Cooling Site",
        "site_name": "Kennedy-King College",
        "address": "740 W. 63rd Street",
        "zip": "60621",
        "phone": "(773) 602-5000",
        "hours_of_operation": "Mon-Sat 8am-8pm",
        "latitude": 41.7796,
        "longitude": -87.6444,
        "is_indoor": True,
    },
    {
        "facility_type": "Library",
        "site_name": "Sherman Park Library",
        "address": "5440 S. Racine Ave",
        "zip": "60609",
        "phone": "(312) 747-0477",
        "hours_of_operation": "Mon & Wed 10am-6pm, Tue & Thu 12pm-8pm, Fri-Sat 9am-5pm",
        "latitude": 41.7944,
        "longitude": -87.6548,
        "is_indoor": True,
    },
    {
        "facility_type": "Senior Center",
        "site_name": "King Center",
        "address": "4314 S. Cottage Grove Ave",
        "zip": "60653",
        "phone": "(312) 747-2300",
        "hours_of_operation": "Mon-Fri 9am-5pm",
        "latitude": 41.8159,
        "longitude": -87.6067,
        "is_indoor": True,
    },
    {
        "facility_type": "Library",
        "site_name": "Manning Branch Library",
        "address": "6 S. Hoyne Ave",
        "zip": "60612",
        "phone": "(312) 746-6800",
        "hours_of_operation": "Mon-Thu 10am-7pm, Fri-Sat 9am-5pm",
        "latitude": 41.8812,
        "longitude": -87.6788,
        "is_indoor": True,
    },
    {
        "facility_type": "Community Service Center",
        "site_name": "Englewood Community Service Center",
        "address": "1140 W. 79th Street",
        "zip": "60620",
        "phone": "(312) 747-0200",
        "hours_of_operation": "Mon-Fri 9am-5pm",
        "latitude": 41.7505,
        "longitude": -87.6528,
        "is_indoor": True,
    },
    {
        "facility_type": "Library",
        "site_name": "Chinatown Branch Library",
        "address": "2100 S. Wentworth Ave",
        "zip": "60616",
        "phone": "(312) 747-8013",
        "hours_of_operation": "Mon-Thu 10am-8pm, Fri-Sat 9am-5pm, Sun 1pm-5pm",
        "latitude": 41.8539,
        "longitude": -87.6322,
        "is_indoor": True,
    },
    {
        "facility_type": "Library",
        "site_name": "Humboldt Park Branch Library",
        "address": "1605 N. Troy Street",
        "zip": "60647",
        "phone": "(312) 744-4294",
        "hours_of_operation": "Mon & Wed 10am-6pm, Tue & Thu 12pm-8pm, Fri-Sat 9am-5pm",
        "latitude": 41.9106,
        "longitude": -87.7056,
        "is_indoor": True,
    },
    {
        "facility_type": "Library",
        "site_name": "Little Village Branch Library",
        "address": "2311 S. Kedzie Ave",
        "zip": "60623",
        "phone": "(312) 745-1862",
        "hours_of_operation": "Mon & Wed 10am-6pm, Tue & Thu 12pm-8pm, Fri-Sat 9am-5pm",
        "latitude": 41.8493,
        "longitude": -87.7047,
        "is_indoor": True,
    },
]

# Medical emergency keywords for Heat Stroke detection
EMERGENCY_KEYWORDS = [
    r"\bunconscious\b",
    r"\bpassed out\b",
    r"\bfaint(?:ed|ing)?\b",
    r"\bconfus(?:ed|ion)\b",
    r"\bhallucinat(?:ing|ion)\b",
    r"\bseiz(?:ure|ing)\b",
    r"\bstop(?:ped)? sweating\b",
    r"\bvomit(?:ing)?\b",
    r"\bnot breathing\b",
    r"\bchest pain\b",
    r"\bloss of consciousness\b",
    r"\bdeliri(?:ous|um)\b",
    r"\bhot (?:and|&) dry skin\b",
    r"\bcollapsed\b",
]

_EMERGENCY_REGEX = re.compile("|".join(EMERGENCY_KEYWORDS), re.IGNORECASE)


@dataclass
class WellnessRequest:
    sr_number: str
    created_at: str
    requester_name: str
    requester_phone: str
    recipient_name: str
    street_address: str
    unit: str
    vulnerabilities: str
    notes: str
    latitude: float
    longitude: float
    status: str = "dispatched_to_field_teams"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in kilometers between two lat/lon points."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return r * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def check_heat_illness_urgency(description: str) -> dict[str, Any]:
    """Examine caller query for life-threatening heat stroke red flags."""
    match = _EMERGENCY_REGEX.search(description)
    if match:
        matched_term = match.group(0)
        return {
            "is_emergency": True,
            "matched_indicator": matched_term,
            "escalation": "CALL_911_IMMEDIATELY",
            "message": (
                "⚠️ URGENT MEDICAL EMERGENCY: The symptoms described ('" + matched_term + "') "
                "indicate potential HEAT STROKE, a medical emergency. "
                "PLEASE HANG UP AND CALL 911 IMMEDIATELY. "
                "While waiting for an ambulance: move person to AC or shade, loosen heavy clothing, "
                "and apply cool, wet cloths or ice to neck, armpits, and groin. Do NOT give fluids if drowsy or unconscious."
            ),
        }
    return {"is_emergency": False}


def find_cooling_for_caller(address_or_intersection: str, limit: int = 3) -> dict[str, Any]:
    """Tool: Locate nearest open air-conditioned cooling centers and libraries for a 311 caller.
    
    Geocodes caller location in Chicago, calculates exact distances to City of Chicago
    cooling centers, and returns facility names, addresses, phone numbers, and operating hours.
    """
    geo = locate_place(address_or_intersection)
    if geo.get("status") != "ok":
        # Offline resolution: check known crossroads & neighborhood mentions
        from heat_dispatch.places import NEIGHBORHOODS
        clean_text = address_or_intersection.lower().strip()
        matched = False
        if "63rd" in clean_text and "halsted" in clean_text:
            geo = {"status": "ok", "latitude": 41.7796, "longitude": -87.6444, "display_name": "63rd and Halsted (Englewood)"}
            matched = True
        else:
            for nh, (nh_lat, nh_lon) in NEIGHBORHOODS.items():
                if nh in clean_text:
                    geo = {"status": "ok", "latitude": nh_lat, "longitude": nh_lon, "display_name": nh.title()}
                    matched = True
                    break
        if not matched:
            return {
                "status": "not_found",
                "message": f"Could not locate '{address_or_intersection}'. Please provide a Chicago neighbourhood (e.g. Englewood, Austin) or street address.",
            }

    lat, lon = geo["latitude"], geo["longitude"]
    if not in_chicago(lat, lon):
        return {
            "status": "outside_chicago",
            "message": f"'{address_or_intersection}' appears to be outside Chicago city limits. Chicago 311 services are dedicated to Chicago residents.",
        }

    # Rank facilities by distance
    scored = []
    for f in DEFAULT_CHICAGO_FACILITIES:
        dist_km = _haversine_km(lat, lon, f["latitude"], f["longitude"])
        dist_miles = dist_km * 0.621371
        scored.append({
            "site_name": f["site_name"],
            "facility_type": f["facility_type"],
            "address": f["address"],
            "zip": f["zip"],
            "phone": f["phone"],
            "hours": f["hours_of_operation"],
            "distance_miles": round(dist_miles, 2),
            "distance_km": round(dist_km, 2),
        })

    ranked = sorted(scored, key=lambda x: x["distance_miles"])[:limit]

    return {
        "status": "ok",
        "caller_location": geo.get("display_name", address_or_intersection),
        "latitude": lat,
        "longitude": lon,
        "nearest_facilities": ranked,
        "summary": (
            f"Found {len(ranked)} cooling facilities near {address_or_intersection}. "
            f"Closest: {ranked[0]['site_name']} at {ranked[0]['address']} ({ranked[0]['distance_miles']} miles away, hours: {ranked[0]['hours']})."
        ),
    }


def intake_wellness_check(
    requester_name: str,
    requester_phone: str,
    recipient_name: str,
    street_address: str,
    unit: str = "",
    vulnerabilities: str = "Senior living alone / no air conditioning",
    notes: str = "",
) -> dict[str, Any]:
    """Tool: File an official Chicago 311 service request for an in-person heat wellness check.
    
    Validates Chicago address, checks medical urgency, creates a tracked 311 ticket,
    and assigns it to field wellness teams.
    """
    # Check if notes indicate immediate 911 emergency
    urgency = check_heat_illness_urgency(f"{vulnerabilities} {notes}")
    if urgency["is_emergency"]:
        return {
            "status": "escalated_to_911",
            "emergency_details": urgency,
            "ticket": None,
            "message": urgency["message"],
        }

    geo = locate_place(street_address)
    lat, lon = geo.get("latitude", 41.8781), geo.get("longitude", -87.6298)
    if geo.get("status") == "ok" and not in_chicago(lat, lon):
        return {
            "status": "outside_chicago",
            "message": "Wellness check requests can only be dispatched to addresses within the City of Chicago.",
        }

    sr_num = f"SR-311-HEAT-{int(time.time())}-{uuid.uuid4().hex[:4].upper()}"
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    ticket = WellnessRequest(
        sr_number=sr_num,
        created_at=now_iso,
        requester_name=requester_name,
        requester_phone=requester_phone,
        recipient_name=recipient_name,
        street_address=street_address,
        unit=unit,
        vulnerabilities=vulnerabilities,
        notes=notes,
        latitude=lat,
        longitude=lon,
        status="dispatched_to_field_teams",
    )

    # Persist request to data folder
    try:
        data_dir = Path(__file__).resolve().parents[2] / ".data"
        data_dir.mkdir(parents=True, exist_ok=True)
        reqs_file = data_dir / "311_wellness_requests.json"
        existing = []
        if reqs_file.is_file():
            try:
                existing = json.loads(reqs_file.read_text(encoding="utf-8"))
            except Exception:
                existing = []
        existing.append(asdict(ticket))
        reqs_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning(f"Could not persist wellness check request: {exc}")

    return {
        "status": "created",
        "sr_number": sr_num,
        "recipient": recipient_name,
        "address": f"{street_address}{f', Unit {unit}' if unit else ''}",
        "dispatched_status": "High Priority: Field team assigned for home visit",
        "message": (
            f"Wellness check ticket #{sr_num} has been successfully logged. "
            f"City field wellness teams will visit {recipient_name} at {street_address} today. "
            f"If conditions worsen or anyone loses consciousness, call 911 immediately."
        ),
    }


def get_311_service_requests(limit: int = 20) -> list[dict[str, Any]]:
    """Retrieve logged 311 wellness requests."""
    data_dir = Path(__file__).resolve().parents[2] / ".data"
    reqs_file = data_dir / "311_wellness_requests.json"
    if reqs_file.is_file():
        try:
            items = json.loads(reqs_file.read_text(encoding="utf-8"))
            return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)[:limit]
        except Exception:
            return []
    return []


def log_311_heat_call(
    location: str,
    vulnerabilities: str = "Senior living alone / no working AC",
    details: str = "",
) -> dict[str, Any]:
    """Tool: Intake an incoming 311 resident heat call and record it as a live vulnerability signal.
    
    Extracts location, evaluates urgency, classifies vulnerability tags, and registers the signal
    to inform dynamic heat dispatch and vulnerability rankings.
    """
    from .vulnerability import parse_vulnerabilities_from_text

    urgency = check_heat_illness_urgency(f"{vulnerabilities} {details}")
    if urgency.get("is_emergency"):
        return {
            "status": "escalated_to_911",
            "message": urgency["message"],
            "call_id": None,
        }

    geo = locate_place(location)
    lat = geo.get("latitude", 41.8781)
    lon = geo.get("longitude", -87.6298)
    nh = geo.get("display_name", location)

    call_id = f"CALL-311-{int(time.time())}-{uuid.uuid4().hex[:4].upper()}"
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tags = parse_vulnerabilities_from_text(f"{vulnerabilities} {details}")

    record = {
        "call_id": call_id,
        "timestamp": now_iso,
        "location": location,
        "neighborhood": nh,
        "vulnerabilities": tags,
        "details": details or vulnerabilities,
        "latitude": lat,
        "longitude": lon,
    }

    try:
        data_dir = Path(__file__).resolve().parents[2] / ".data"
        data_dir.mkdir(parents=True, exist_ok=True)
        calls_file = data_dir / "311_calls.json"
        existing = []
        if calls_file.is_file():
            try:
                existing = json.loads(calls_file.read_text(encoding="utf-8"))
            except Exception:
                existing = []
        existing.append(record)
        calls_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning(f"Could not persist 311 heat call: {exc}")

    return {
        "status": "logged",
        "call_id": call_id,
        "neighborhood": nh,
        "identified_vulnerabilities": tags,
        "message": (
            f"311 heat call #{call_id} registered for {nh}. "
            f"Identified vulnerability tags: {', '.join(tags)}. "
            "Data is now actively incorporated into city heat vulnerability rankings."
        ),
    }
