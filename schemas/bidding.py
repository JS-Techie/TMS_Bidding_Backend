from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class FilterBidsRequest(BaseModel):
    shipper_id : UUID | None = None
    rc_id : UUID | None = None
    branch_id : UUID | None = None
    from_date : datetime | None = None
    to_date : datetime | None = None

class HistoricalRatesReq(BaseModel):
    transporter_id : UUID

class TransporterBidReq(BaseModel):
    transporter_id : UUID
    rate : float
    comment : str


class TransporterAssignReq(BaseModel):
    la_bidding_load_id : UUID
    la_transporter_id : UUID
    trans_pos_in_bid : str
    price : float
    price_difference_percent : float
    no_of_fleets_assigned : int
    