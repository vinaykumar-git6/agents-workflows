"""Normalized Air Waybill schema (structured output the agent must produce)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Party(BaseModel):
    name: Optional[str] = Field(None, description="Normalized full name, title case.")
    account_number: Optional[str] = None
    address: Optional[str] = Field(None, description="Single-line normalized address.")
    city: Optional[str] = None
    country: Optional[str] = Field(None, description="ISO country name, normalized.")


class RoutingLeg(BaseModel):
    to: Optional[str] = Field(None, description="Destination airport IATA code.")
    by_carrier: Optional[str] = Field(None, description="Carrier code.")


class AwbDocument(BaseModel):
    """Normalized Air Waybill. All values cleaned, de-duplicated, trimmed."""

    awb_number: Optional[str] = Field(
        None, description="Full AWB as PREFIX-SERIAL, e.g. 176-12345678."
    )
    awb_prefix: Optional[str] = Field(None, description="3-digit airline prefix.")
    awb_serial: Optional[str] = Field(None, description="8-digit serial number.")
    shipper: Party = Field(default_factory=Party)
    consignee: Party = Field(default_factory=Party)
    issuing_carrier_agent: Party = Field(default_factory=Party)
    airport_of_departure: Optional[str] = None
    airport_of_destination: Optional[str] = None
    routing: list[RoutingLeg] = Field(default_factory=list)
    flight_number: Optional[str] = None
    flight_date: Optional[str] = Field(None, description="ISO 8601 date, YYYY-MM-DD.")
    number_of_pieces: Optional[int] = None
    gross_weight: Optional[float] = None
    weight_unit: Optional[str] = Field(None, description="KG or LB, normalized.")
    chargeable_weight: Optional[float] = None
    rate_class: Optional[str] = None
    rate_charge: Optional[float] = None
    total_charge: Optional[float] = None
    currency: Optional[str] = Field(None, description="ISO 4217 code, e.g. USD.")
    nature_and_quantity_of_goods: Optional[str] = None
    declared_value_for_carriage: Optional[str] = None
    declared_value_for_customs: Optional[str] = None
    handling_information: Optional[str] = None
