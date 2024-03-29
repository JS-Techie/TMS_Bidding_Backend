import os
import httpx
import json
import requests
import ast
import pytz
from datetime import datetime, timedelta
from sqlalchemy import text, and_, or_, func, select
from uuid import UUID
from typing import List

from config.db_config import Session
from utils.response import ServerError, SuccessResponse
from models.models import BidTransaction, TransporterModel, MapShipperTransporter, LoadAssigned, BiddingLoad, User, ShipperModel, MapLoadSrcDestPair, BlacklistTransporter, TrackingFleet, BidSettings
from utils.bids.bidding import Bid
from utils.utilities import log, structurize_transporter_bids
from utils.notification_service_manager import notification_service_manager, NotificationServiceManagerReq
from data.bidding import lost_participated_transporter_bids, live_bid_details, assignment_events


bid = Bid()


class Transporter:

    async def id(self, user_id: str) -> (str, str):

        session = Session()

        try:
            if not user_id:
                return (False, "The User ID provided is empty")

            transporter = (session
                           .query(User)
                           .filter(User.user_id == user_id, User.is_active == True)
                           .first()
                           )

            if not transporter:
                return ("", "Transporter ID could not be found")

            return (transporter.user_transporter_id, "")

        except Exception as e:
            session.rollback()
            return ("", str(e))
        finally:
            session.close()

    async def notify(self, bid_id: str, authtoken: any) -> (bool, str):

        session = Session()

        try:
            (bid_details, error) = await self.bid_details(bid_id=bid_id)
            if error:
                return ("", error)

            transporter_ids = []
            user_ids = []

            if bid_details.bid_mode == 'private_pool':
                transporters = session.query(MapShipperTransporter).filter(
                    MapShipperTransporter.mst_shipper_id == bid_details.bl_shipper_id, MapShipperTransporter.is_active == True).all()
                for transporter in transporters:
                    transporter_ids.append(transporter.mst_transporter_id)

            elif bid_details.bid_mode == 'open_market':
                transporters = session.query(TransporterModel).filter(
                    TransporterModel.is_active == True).all()
                for transporter in transporters:
                    transporter_ids.append(transporter.trnsp_id)

            user_details = session.query(User).filter(
                User.user_transporter_id.in_(transporter_ids), User.is_active == True).all()

            login_url = "http://13.235.56.142:8000/api/secure/notification/"
            headers = {
                'Authorization': authtoken
            }

            for user_detail in user_details:
                user_ids.append(str(user_detail.user_id))

            payload = {"nt_receiver_id": user_ids,
                       "nt_text": f"New Bid for a Load needing {bid_details.no_of_fleets} fleets is Available with Load id - {bid_details.bl_id}. The Bidding will start from {bid_details.bid_time}",
                       "nt_type": "PUBLISH NOTIFICATION",
                       "nt_deep_link": "transporter_dashboard_upcoming",
                       }

            log("PAYLOAD", payload)
            log("HEADER", headers)

            with httpx.Client() as client:
                response = client.post(
                    url=login_url, headers=headers, data=json.dumps(payload))

            log("NOTIFICATION CREATE Response", response.json())
            json_response = response.json()

            if json_response["success"] == False:
                return (False, json_response["dev_message"])
            return (True, "")

        except Exception as err:
            session.rollback()
            return ("", str(err))
        finally:
            session.close()

    async def historical_rates(self, transporter_id: str, bid_id: str) -> (any, str):

        session = Session()

        try:

            historical_rates = (session
                                .query(BidTransaction)
                                .filter(BidTransaction.transporter_id == transporter_id, BidTransaction.bid_id == bid_id, BidTransaction.rate > 0)
                                .order_by(BidTransaction.created_at.desc())
                                .all()
                                )

            price_match_rates = (session
                                 .query(LoadAssigned)
                                 .filter(LoadAssigned.la_transporter_id == transporter_id, LoadAssigned.la_bidding_load_id == bid_id)
                                 .first()
                                 )

            historical_rates = [{**historical_rate.__dict__, "event":"Live Bid Rates"} for historical_rate in historical_rates]
            for historical_rate in historical_rates:
                historical_rate["created_at"] = historical_rate["created_at"]+timedelta(hours=5.5)
            history = []

            if price_match_rates:
                if price_match_rates.history:
                    assignment_history = ast.literal_eval(price_match_rates.history)[::-1]

                    log("ASSIGNMENT HISTORY", assignment_history)
                    log("TYPE", type(assignment_history))

                    for (event, rate, created_at, reason) in assignment_history:
                        if event not in (assignment_events["unassign"] ,assignment_events["assign"]):
                            history.append({
                                "event": event,
                                "rate": rate,
                                "created_at":created_at,
                                "comment": reason
                            })
            
            if history:
                historical_rates = history + historical_rates

            pm_price = None
            pm_comment = None

            if price_match_rates:
                if price_match_rates.is_pmr_approved != False:
                    pm_price = price_match_rates.pmr_price
                    pm_comment = price_match_rates.pmr_comment
                    

            return ({
                "historical": historical_rates,
                "pmr_price": pm_price,
                "pmr_comment": pm_comment,
                "pmr_date": price_match_rates.updated_at if price_match_rates else None,
                "no_of_fleets_assigned": price_match_rates.no_of_fleets_assigned if price_match_rates else None,
            }, "")

        except Exception as err:
            session.rollback()
            return ([], str(err))

        finally:
            session.close()

    async def is_valid_bid_rate(self, bid_id: str, show_rate_to_transporter: bool, rate: float, transporter_id: str, decrement: float, is_decrement_in_percentage: bool, status: str) -> (any, str):

        session = Session()

        try:

            if show_rate_to_transporter and status == "live":
                return await bid.decrement_on_lowest_price(bid_id=bid_id, rate=rate, decrement=decrement, is_decrement_in_percentage=is_decrement_in_percentage)
            return await bid.decrement_on_transporter_lowest_price(bid_id=bid_id, transporter_id=transporter_id, rate=rate, decrement=decrement, is_decrement_in_percentage=is_decrement_in_percentage)

        except Exception as e:
            session.rollback()
            return ({}, str(e))
        finally:
            session.close()

    async def attempts(self, bid_id: str, transporter_id: str) -> (int, str):

        session = Session()

        try:
            no_of_tries = session.query(BidTransaction).filter(
                BidTransaction.transporter_id == transporter_id, BidTransaction.bid_id == bid_id, BidTransaction.rate > 0).count()

            log("NUMBER OF TRIES", no_of_tries)

            return (no_of_tries, "")

        except Exception as e:
            session.rollback()
            return (0, str(e))

        finally:
            session.close()

    async def lowest_price(self, bid_id: str, transporter_id: str) -> (float, str):

        session = Session()
        try:

            transporter_bid = (session
                               .query(BidTransaction)
                               .filter(BidTransaction.transporter_id == transporter_id, BidTransaction.bid_id == bid_id, BidTransaction.rate > 0)
                               .order_by(BidTransaction.rate)
                               .first()
                               )

            if not transporter_bid:
                return (0.0, "")

            return (transporter_bid.rate, "")

        except Exception as e:
            session.rollback()
            return (0.0, str(e))

        finally:
            session.close()

    async def name(self, transporter_id: str) -> (str, str):

        session = Session()

        try:
            transporter = session.query(TransporterModel).filter(
                TransporterModel.trnsp_id == transporter_id).first()

            if not transporter:
                return ("", "Requested transporter details was not found")

            return (transporter.name, "")

        except Exception as err:
            session.rollback()
            return ("", str(err))
        finally:
            session.close()

    async def allowed_to_bid(self, shipper_id: str, transporter_id: str) -> (bool, str):
        session = Session()

        try:
            log("INSIDE ALLOWED TO BID", "OK")
            transporter_details = session.query(MapShipperTransporter).filter(
                MapShipperTransporter.mst_shipper_id == shipper_id, MapShipperTransporter.mst_transporter_id == transporter_id, MapShipperTransporter.is_active == True).first()
            log("TRANSPORTER DETAILS", transporter_details)
            if not transporter_details:
                return (False, "transporter not tagged with the specific shipper")

            return (True, "")

        except Exception as e:
            session.rollback()
            return (False, str(e))
        finally:
            session.close()

    async def bid_match(self, bid_id: str, transporters: any, user_id: str, user_type: str) -> (any, str):
        session = Session()

        try:

            fetched_transporter_ids = []
            assigned_transporters = []
            price_match_window_start_time = None
            superuser = (user_type == "acu")
            ist_timezone = pytz.timezone("Asia/Kolkata")
            current_time = datetime.now(ist_timezone)
            current_time = current_time.replace(
                tzinfo=None, second=0, microsecond=0)

            transporter_ids = [getattr(transporter, "transporter_id") for transporter in transporters]

            transporter_details = session.query(LoadAssigned).filter(
                LoadAssigned.la_bidding_load_id == bid_id, LoadAssigned.la_transporter_id.in_(transporter_ids)).all()

            log("Fetched Transporter Detail ", transporter_details)

            bid_details = (session.query(BiddingLoad).filter(BiddingLoad.bl_id == bid_id).first())
            if not bid_details:
                return([],"Bid Details Not Found ")
            
            bid_settings = (session
                            .query(BidSettings)
                            .filter(BidSettings.bdsttng_shipper_id == bid_details.bl_shipper_id, BidSettings.is_active, or_(BidSettings.bdsttng_branch_id == bid_details.bl_branch_id, BidSettings.bdsttng_branch_id.is_(None)))
                            .order_by(BidSettings.bdsttng_branch_id).limit(1)
                            .first()
                            )
            
            all_transporter_details = (session.query(LoadAssigned).filter(LoadAssigned.la_bidding_load_id == bid_id, LoadAssigned.is_active == True).order_by(LoadAssigned.pm_req_timestamp).all())

            for transporter_detail in all_transporter_details:

                if not superuser:
                    if transporter_detail.is_negotiated_by_aculead == False and transporter_detail.pm_req_timestamp is not None:
                        if not price_match_window_start_time :
                            price_match_window_start_time = transporter_detail.pm_req_timestamp
                        else:
                            if price_match_window_start_time > transporter_detail.pm_req_timestamp:
                                price_match_window_start_time = transporter_detail.pm_req_timestamp

            for transporter_detail in transporter_details:

                if not superuser:
                    if transporter_detail.is_pmr_approved == True:
                        transporter_personals = (session.query(TransporterModel).filter(TransporterModel.trnsp_id == transporter_detail.la_transporter_id).first())
                        return (transporter_personals.name, "Price Match Already Accepted")

                fetched_transporter_ids.append(
                    transporter_detail.la_transporter_id)

            if not superuser and price_match_window_start_time is not None:
                if current_time > price_match_window_start_time + timedelta(minutes=bid_settings.price_match_duration):
                    return(price_match_window_start_time + timedelta(minutes=bid_settings.price_match_duration),"Price Match Locked")

            transporters_not_assigned = list(
                set(transporter_ids) - set(fetched_transporter_ids))
            log("Transporter IDs not assigned", transporters_not_assigned)
            transporters_to_be_updated = list(
                set(transporter_ids).intersection(set(fetched_transporter_ids)))
            log("Transporter to be Updated", transporters_to_be_updated)

            for transporter in transporters:
                if getattr(transporter, "transporter_id") in transporters_not_assigned:

                    assign_detail = LoadAssigned(
                        la_bidding_load_id=bid_id,
                        la_transporter_id=getattr(
                            transporter, "transporter_id"),
                        trans_pos_in_bid=getattr(
                            transporter, "trans_pos_in_bid"
                        ),
                        no_of_fleets_assigned=0,
                        pmr_price=getattr(
                            transporter, "rate"),
                        pmr_comment=getattr(
                            transporter, "comment"
                        ),
                        pm_req_timestamp=current_time if not superuser else None,
                        is_pmr_approved = True if superuser else False,
                        is_negotiated_by_aculead = True if superuser else False,
                        history = str([(assignment_events["superuser-negotiation"] if superuser else assignment_events["pm-request"] ,getattr(transporter, "rate"), str(current_time), getattr(transporter, "comment"))]),
                        is_active=True,
                        created_at="NOW()",
                        created_by=user_id
                    )
                    assigned_transporters.append(assign_detail)

            log("Assigned Transporters", assigned_transporters)

            for transporter_detail in transporter_details:
                if getattr(transporter_detail, "la_transporter_id") in transporters_to_be_updated:
                    for transporter in transporters:
                        if getattr(transporter_detail, "la_transporter_id") == getattr(transporter, "transporter_id"):
                            
                            task = (assignment_events["superuser-negotiation"] if superuser else assignment_events["pm-request"],getattr(transporter, "rate"), str(current_time), getattr(transporter, "comment"))
                            fetched_history = ast.literal_eval(getattr(transporter_detail, "history"))
                            fetched_history.append(task)

                            setattr(transporter_detail, "la_transporter_id",
                                    getattr(transporter, "transporter_id"))
                            setattr(transporter_detail, "pmr_price",
                                    getattr(transporter, "rate"))
                            setattr(transporter_detail, "trans_pos_in_bid",
                                    getattr(transporter, "trans_pos_in_bid"))
                            setattr(transporter_detail, "pmr_comment",
                                    getattr(transporter, "comment")),
                            setattr(transporter_detail, "pm_req_timestamp",current_time if not superuser else None)
                            setattr(transporter_detail, "is_pmr_approved", True if superuser else False)
                            setattr(transporter_detail, "is_negotiated_by_aculead", True if superuser else False)
                            setattr(transporter_detail, "history", str(fetched_history))
                            setattr(transporter_detail, "updated_at", "NOW()")
                            setattr(transporter_detail, "updated_by", user_id)

            log("Data changed for Update ")

            session.bulk_save_objects(assigned_transporters)
            session.commit()

            if not assigned_transporters:
                return ([], "")

            return (assigned_transporters, "")

        except Exception as e:
            session.rollback()
            return ([], str(e))
        finally:
            session.close()

    async def unassign(self, bid_id: str, transporter_request: any, authtoken: any) -> (any, str):

        session = Session()

        try:

            transporter_id = transporter_request.transporter_id
            unassignment_reason = transporter_request.unassignment_reason

            transporters = (session
                            .query(LoadAssigned)
                            .filter(LoadAssigned.la_bidding_load_id == bid_id,
                                    LoadAssigned.is_assigned == True,
                                    LoadAssigned.is_active == True)
                            .all()
                            )

            if not transporters:
                return ({}, "Transporter details could not be found")

            no_transporter_assigned = True

            ist_timezone = pytz.timezone("Asia/Kolkata")
            current_time = datetime.now(ist_timezone)
            current_time = current_time.replace(
                tzinfo=None, second=0, microsecond=0)

            for transporter in transporters:
                if transporter.la_transporter_id == UUID(transporter_id):
                    transporter.is_assigned = False
                    transporter.no_of_fleets_assigned = 0
                    transporter.unassignment_reason = unassignment_reason
                    if transporter.history:
                        task = (assignment_events["unassign"],0, str(current_time), unassignment_reason)
                        fetched_history = ast.literal_eval(transporter.history)
                        fetched_history.append(task)
                        transporter.history = str(fetched_history)
                    else:
                        transporter.history = str(
                            [(assignment_events["unassign"],0, str(current_time), unassignment_reason)])

                elif no_transporter_assigned and transporter.la_transporter_id != UUID(transporter_id):
                    no_transporter_assigned = False

            bid_details = (session
                   .query(BiddingLoad)
                   .filter(BiddingLoad.bl_id == bid_id)
                   .first()
                   )

            if not bid_details:
                return ({}, "Bid details could not be found")

            if no_transporter_assigned:
                bid_details.load_status = "pending"
                bid_details.updated_at = "NOW()"
            else:
                bid_details.load_status = "partially_confirmed"
                bid_details.updated_at = "NOW()"

            session.commit()

            (kam_ids, error) = await bid.transporter_kams(transporter_ids=[transporter_id])
            if error:
                return ([],error)
            
            (notification_response_success, notification_error) = await notification_service_manager(authtoken=authtoken, req=NotificationServiceManagerReq(**{
                                                                                                                                            "receiver_ids": kam_ids,
                                                                                                                                            "text":f"Bid L-{bid_id[-5:].upper()} has been Unassigned from you! NO WORRIES BUDDY ... HOPE FOR THE BEST, EXPECT THE WORST, LIFE IS A PLAY & WE ARE UNREHEARSED !!!",
                                                                                                                                            "type":"Bid Unassignment",
                                                                                                                                            "deep_link":"transporter_dashboard_pending"
                                                                                                                                        }
                                                                                                                                        )
                                                                                        )
            log("ASSIGNMENT CREATION NOTIFICATION SERVICE ", notification_response_success)
            if notification_error:
                log("::: NOTIFICATION ERROR DURING NEW BID ASSIGNMENT  ::: ",notification_error)
                

            return (transporter, "")

        except Exception as e:
            session.rollback()
            return ({}, str(e))
        finally:
            session.close()

    async def bids_by_status(self, transporter_id: str, user_id: str, status: str | None = None) -> (any, str):

        session = Session()

        try:
            shippers, error = await self.shippers(transporter_id=transporter_id)
            if error:
                return [], error

            log("FETCHED SHIPPERS ATTACHED TO TRANSPORTERS", shippers)

            public_bids, error = await bid.public(blocked_shippers=shippers["blocked_shipper_ids"], transporter_id=transporter_id, status=status)

            if error:
                return [], error

            log("FETCHED PUBLIC BIDS", public_bids)

            unsegmented_private_bids = []
            segmented_bids = []
            if shippers["shipper_ids"]:
                unsegmented_private_bids, error = await bid.private(shippers=shippers["shipper_ids"], transporter_id=transporter_id, user_id=user_id, status=status)
                if error:
                    return [], error
                log("FETCHED PRIVATE BIDS", unsegmented_private_bids)
                
                segmented_bids, error = await bid.segment(shippers=shippers["shipper_ids"], transporter_id=transporter_id, user_id=user_id, status=status)
                if error:
                    return [],error
                log("SEGMENTED PRIVATE BIDS", segmented_bids)
                
                
            return {
                "all": unsegmented_private_bids + public_bids + segmented_bids,
                "private": unsegmented_private_bids + segmented_bids,
                "public": public_bids
            }, ""

        except Exception as e:
            session.rollback()
            return [], str(e)
        finally:
            session.close()

    async def selected(self, transporter_id: str) -> (any, str):

        session = Session()

        try:
            bid_arr = (session
                       .query(LoadAssigned)
                       .filter(LoadAssigned.la_transporter_id == transporter_id, LoadAssigned.is_active == True, LoadAssigned.is_assigned == True)
                       .all()
                       )

            if not bid_arr:
                return ([], "")

            bid_ids = [bid.la_bidding_load_id for bid in bid_arr]

            log("BID IDS ", bid_ids)
            bids = (session
                    .query(BiddingLoad,
                           ShipperModel.shpr_id,
                           ShipperModel.name,
                           ShipperModel.contact_no,
                           func.array_agg(MapLoadSrcDestPair.src_city), func.array_agg(MapLoadSrcDestPair.src_street_address), func.array_agg(MapLoadSrcDestPair.src_state), func.array_agg(MapLoadSrcDestPair.dest_street_address), func.array_agg(MapLoadSrcDestPair.dest_state),
                           func.array_agg(MapLoadSrcDestPair.dest_city),
                           func.array_agg(select(func.count())
                                                            .where(
                                                                TrackingFleet.tf_transporter_id == transporter_id,
                                                                TrackingFleet.tf_bidding_load_id == BiddingLoad.bl_id,
                                                                TrackingFleet.is_active == True  
                                                            )
                                                            .correlate(BiddingLoad)
                                                            .subquery()
                                                        ).label('tf_vehicle_count')
                            )
                    .outerjoin(ShipperModel, ShipperModel.shpr_id == BiddingLoad.bl_shipper_id)
                    .outerjoin(MapLoadSrcDestPair, and_(MapLoadSrcDestPair.mlsdp_bidding_load_id == BiddingLoad.bl_id, MapLoadSrcDestPair.is_active == True))
                    .filter(BiddingLoad.is_active == True, BiddingLoad.bl_id.in_(bid_ids))
                    .group_by(BiddingLoad, *BiddingLoad.__table__.c, ShipperModel.name, ShipperModel.contact_no, ShipperModel.shpr_id )
                    .all()
                    )

            log("BIDS ", bids)
            if not bids:
                return ([], "")

            structured_bids = structurize_transporter_bids(bids=bids)

            load_assigned_dict = {
                load.la_bidding_load_id: load for load in bid_arr}

            for bid in structured_bids:
                if bid["bid_id"] in bid_ids:
                    load_assigned = load_assigned_dict.get(bid["bid_id"])
                    if load_assigned:
                        bid["no_of_fleets_assigned"] = load_assigned.no_of_fleets_assigned
                        bid["pending_vehicles"] = bid["no_of_fleets_assigned"] - bid["no_of_fleets_provided"]

            return (structured_bids, "")

        except Exception as e:
            session.rollback()
            return [], str(e)
        finally:
            session.close()

    async def completed(self, transporter_id: str) -> (any, str):

        session = Session()

        try:
            bid_arr = (session
                       .query(LoadAssigned)
                       .filter(LoadAssigned.la_transporter_id == transporter_id, LoadAssigned.is_active == True, LoadAssigned.is_assigned == True)
                       .all()
                       )

            if not bid_arr:
                return ([], "")

            bid_ids = [bid.la_bidding_load_id for bid in bid_arr]

            log("BID IDS ", bid_ids)
            bids = (session
                    .query(BiddingLoad,
                           ShipperModel.shpr_id,
                           ShipperModel.name,
                           ShipperModel.contact_no,
                           func.array_agg(MapLoadSrcDestPair.src_city), func.array_agg(MapLoadSrcDestPair.src_street_address), func.array_agg(MapLoadSrcDestPair.src_state), func.array_agg(MapLoadSrcDestPair.dest_street_address), func.array_agg(MapLoadSrcDestPair.dest_state),
                           func.array_agg(MapLoadSrcDestPair.dest_city),
                           func.array_agg(select(func.count())
                                                            .where(
                                                                TrackingFleet.tf_transporter_id == transporter_id,
                                                                TrackingFleet.tf_bidding_load_id == BiddingLoad.bl_id,
                                                                TrackingFleet.is_active == True  
                                                            )
                                                            .correlate(BiddingLoad)
                                                            .subquery()
                                                        ).label('tf_vehicle_count')
                            )
                    .outerjoin(ShipperModel, ShipperModel.shpr_id == BiddingLoad.bl_shipper_id)
                    .outerjoin(MapLoadSrcDestPair, and_(MapLoadSrcDestPair.mlsdp_bidding_load_id == BiddingLoad.bl_id, MapLoadSrcDestPair.is_active == True))
                    .filter(BiddingLoad.is_active == True, BiddingLoad.bl_id.in_(bid_ids), BiddingLoad.load_status == "completed")
                    .group_by(BiddingLoad, *BiddingLoad.__table__.c, ShipperModel.name, ShipperModel.contact_no, ShipperModel.shpr_id )
                    .all()
                    )

            log("BIDS ", bids)
            if not bids:
                return ([], "")

            structured_bids = structurize_transporter_bids(bids=bids)

            load_assigned_dict = {
                load.la_bidding_load_id: load for load in bid_arr}

            for bid in structured_bids:
                if bid["bid_id"] in bid_ids:
                    load_assigned = load_assigned_dict.get(bid["bid_id"])
                    if load_assigned:
                        bid["no_of_fleets_assigned"] = load_assigned.no_of_fleets_assigned
                        bid["pending_vehicles"] = bid["no_of_fleets_assigned"] - bid["no_of_fleets_provided"]

            return (structured_bids, "")

        except Exception as e:
            session.rollback()
            return [], str(e)
        finally:
            session.close()

    async def participated_bids(self, transporter_id: str) -> (any, str):

        session = Session()

        try:
            bid_arr = (session
                       .query(BidTransaction)
                       .distinct(BidTransaction.bid_id)
                       .filter(BidTransaction.transporter_id == transporter_id, BidTransaction.rate > 0)
                       .all()
                       )

            if not bid_arr:
                return ([], "")

            log("PARTICIPATED AND NOT LOST", bid_arr)

            bid_ids = [str(bid.bid_id) for bid in bid_arr]

            log("BID IDs OF NOT LOST AND PARTICPATED", bid_ids)

            bids = (session
                    .query(BiddingLoad,
                           ShipperModel.shpr_id,
                           ShipperModel.name,
                           ShipperModel.contact_no,
                           func.array_agg(MapLoadSrcDestPair.src_city), func.array_agg(MapLoadSrcDestPair.src_street_address), func.array_agg(MapLoadSrcDestPair.src_state), func.array_agg(MapLoadSrcDestPair.dest_street_address), func.array_agg(MapLoadSrcDestPair.dest_state),
                           func.array_agg(MapLoadSrcDestPair.dest_city),
                           func.array_agg(select(func.count())
                                                            .where(
                                                                TrackingFleet.tf_transporter_id == transporter_id,
                                                                TrackingFleet.tf_bidding_load_id == BiddingLoad.bl_id,
                                                                TrackingFleet.is_active == True  
                                                            )
                                                            .correlate(BiddingLoad)
                                                            .subquery()
                                                        ).label('tf_vehicle_count')
                           )
                    .outerjoin(ShipperModel, ShipperModel.shpr_id == BiddingLoad.bl_shipper_id)
                    .outerjoin(MapLoadSrcDestPair, and_(MapLoadSrcDestPair.mlsdp_bidding_load_id == BiddingLoad.bl_id, MapLoadSrcDestPair.is_active == True))
                    .filter(BiddingLoad.is_active == True, BiddingLoad.bl_id.in_(bid_ids))
                    .group_by(BiddingLoad, *BiddingLoad.__table__.c, ShipperModel.name, ShipperModel.contact_no, ShipperModel.shpr_id )
                    .all()
                    )

            if not bids:
                return ([], "")

            return (structurize_transporter_bids(bids=bids), "")

        except Exception as e:
            session.rollback()
            return [], str(e)
        finally:
            session.close()

    async def participated_and_lost_bids(self, transporter_id: str) -> (any, str):

        session = Session()

        try:
            bid_arr = session.execute(text(lost_participated_transporter_bids), params={
                "transporter_id": transporter_id
            })
            log("BID ARRAY ", bid_arr)
            bid_ids = [bid._mapping["bid_id"] for bid in bid_arr]
            log("BID IDS", bid_ids)
            if not bid_ids:
                return ([], "")

            load_status_for_lost_participated = ["completed", "confirmed"]

            bids = (session
                    .query(BiddingLoad,
                           ShipperModel.shpr_id,
                           ShipperModel.name,
                           ShipperModel.contact_no,
                           func.array_agg(MapLoadSrcDestPair.src_city), func.array_agg(MapLoadSrcDestPair.src_street_address), func.array_agg(MapLoadSrcDestPair.src_state), func.array_agg(MapLoadSrcDestPair.dest_street_address), func.array_agg(MapLoadSrcDestPair.dest_state),
                           func.array_agg(MapLoadSrcDestPair.dest_city),
                           func.array_agg(select(func.count())
                                                            .where(
                                                                TrackingFleet.tf_transporter_id == transporter_id,
                                                                TrackingFleet.tf_bidding_load_id == BiddingLoad.bl_id,
                                                                TrackingFleet.is_active == True  
                                                            )
                                                            .correlate(BiddingLoad)
                                                            .subquery()
                                                        ).label('tf_vehicle_count')
                           )
                    .outerjoin(ShipperModel, ShipperModel.shpr_id == BiddingLoad.bl_shipper_id)
                    .outerjoin(MapLoadSrcDestPair, and_(MapLoadSrcDestPair.mlsdp_bidding_load_id == BiddingLoad.bl_id, MapLoadSrcDestPair.is_active == True))
                    .filter(BiddingLoad.is_active == True, BiddingLoad.bl_id.in_(bid_ids), BiddingLoad.load_status.in_(load_status_for_lost_participated))
                    .group_by(BiddingLoad, *BiddingLoad.__table__.c, ShipperModel.name, ShipperModel.contact_no, ShipperModel.shpr_id )
                    .all()
                    )

            if not bids:
                return ([], "")

            log("PARTICPATED BIDS", bids)

            return (structurize_transporter_bids(bids=bids), "")

        except Exception as e:
            session.rollback()
            return [], str(e)
        finally:
            session.close()

    async def not_participated_and_lost_bids(self, transporter_id: str, user_id: str) -> (any, str):

        session = Session()

        try:
            all_bids, error = await self.bids_by_status(transporter_id=transporter_id, user_id= user_id)

            if error:
                return ([], error)

            _all = all_bids["all"]

            (participated_bids, error) = await self.participated_bids(transporter_id=transporter_id)

            if error:
                return ([], "Participated bids for transporter could not be fetched")

            log("PARTICIPATED")

            not_participated_bids = [
                bid for bid in _all if bid not in participated_bids]

            # and bid.load_status in particpated_and_lost_status

            if not not_participated_bids:
                return ([], "")

            return not_participated_bids, ""

        except Exception as e:
            session.rollback()
            return [], str(e)
        finally:
            session.close()

    async def shippers(self, transporter_id: str) -> (any, str):

        session = Session()
        shipper_ids = []

        try:
            shipper_and_blacklist_details = (
                session.query(MapShipperTransporter,
                              TransporterModel,
                              BlacklistTransporter
                              )
                .join(TransporterModel, and_(MapShipperTransporter.mst_transporter_id == TransporterModel.trnsp_id, TransporterModel.is_active == True))
                .outerjoin(BlacklistTransporter, and_(BlacklistTransporter.bt_shipper_id == MapShipperTransporter.mst_shipper_id, BlacklistTransporter.bt_transporter_id == transporter_id, BlacklistTransporter.is_active == True))
                .filter(MapShipperTransporter.mst_transporter_id == transporter_id, MapShipperTransporter.is_active == True)
                .all()
            )
            
            transporter_status = ''
            if not shipper_and_blacklist_details:
                aculead_transporter_detail = (
                                            session.query(TransporterModel)
                                            .filter(TransporterModel.trnsp_id == transporter_id, TransporterModel.is_active == True)
                                            .first()
                                            )
                
                if aculead_transporter_detail:
                    transporter_status = aculead_transporter_detail.status

            shipper_ids = []
            mapped_blocked_shipper_ids = []
            unmapped_blocked_shipper_ids = []

            
            for shipper_and_blacklist_detail in shipper_and_blacklist_details:
                (shipper, transporter_details,
                 blacklist_details) = shipper_and_blacklist_detail

                if transporter_details.status == 'partially_blocked':
                    transporter_status = 'partially_blocked'
                    if not blacklist_details:
                        shipper_ids.append(shipper.mst_shipper_id)
                    else:
                        mapped_blocked_shipper_ids.append(shipper.mst_shipper_id)
                        
                else:
                    shipper_ids.append(shipper.mst_shipper_id)
                log("SHIPPER :", shipper)
                log("TRANSPORTER DETAILS :", transporter_details.trnsp_id)
                log("BLACKLIST :", blacklist_details)

            log("SHIPPER IDs", shipper_ids)
            log("BLOCKED SHIPPER IDS", mapped_blocked_shipper_ids)

            if transporter_status == 'partially_blocked':
                unmapped_blocked_shippers = (
                                            session.query(BlacklistTransporter)
                                            .filter(BlacklistTransporter.is_active == True, ~BlacklistTransporter.bt_shipper_id.in_(mapped_blocked_shipper_ids), BlacklistTransporter.bt_transporter_id == transporter_id)
                                            .all()
                                        )
                log("UNMAPPED BLOCKED SHIPPERS ", unmapped_blocked_shippers)
                for unmapped_blocked_shipper in unmapped_blocked_shippers:
                    unmapped_blocked_shipper_ids.append(unmapped_blocked_shipper.bt_shipper_id)
                log("UNMAPPED BLOCKED SHIPPER IDS ", unmapped_blocked_shipper_ids)

            
            all_shipper_ids = {
                "shipper_ids": shipper_ids,
                "blocked_shipper_ids": mapped_blocked_shipper_ids + unmapped_blocked_shipper_ids
            }
            log("ALL SHIPPER IDS ", all_shipper_ids)

            return (all_shipper_ids, "")

        except Exception as e:
            session.rollback()
            return ({}, str(e))
        finally:
            session.close()

    async def participated_bids_shipper(self, transporter_id: str) -> (any, str):

        session = Session()
        
        try:
            
            bids_participated = (session
                                .query(BidTransaction, BiddingLoad.bl_shipper_id)
                                .filter(BidTransaction.transporter_id == transporter_id,
                                        BidTransaction.is_tc_accepted == True,
                                        BidTransaction.is_active == True,
                                        BidTransaction.rate < 0,
                                        BidTransaction.bid_id == BiddingLoad.bl_id,
                                        BiddingLoad.is_active == True)
                                .all()
                                )
            
            shippers_participated_in = []
            
            if bids_participated:
                shippers_participated_in = [shipper_id for _, shipper_id in bids_participated]
                
            return (list(set(shippers_participated_in)), "")
            
            
        except Exception as e:
            session.rollback()
            return ({}, str(e))
        finally:
            session.close()

    async def bid_details(self, bid_id: str, transporter_id: str | None = None) -> (any, str):

        session = Session()

        log("FINDING BID DETAILS FOR A TRANSPORTER")

        try:

            bid_details = (
                session
                .query(BiddingLoad)
                .filter(BiddingLoad.bl_id == bid_id)
                .first()
            )

            log("BID DETAILS AFTER QUERY", bid_details)

            if not bid_details:
                return ([], "")

            return (bid_details, "")

        except Exception as e:
            session.rollback()
            return ({}, str(e))
        finally:
            session.close()

    async def assigned_bids(self, transporter_id: str, user_id: str) -> (any, str):

        session = Session()

        try:

            _all, error = await self.bids_by_status(transporter_id=transporter_id, user_id= user_id)

            if error:
                return ([], error)

            all_bids = _all["all"]

            if not all_bids:
                return ([], "")

            log("ALL BIDS FOR A TRANSPORTER", all_bids)

            # Filtering all bids which are confirmed or partially confirmed
            filtered_bid_ids = [str(bid["bid_id"]) for bid in all_bids if bid["load_status"]
                                == "confirmed" or bid["load_status"] == "partially_confirmed"]

            log("BIDS WHICH ARE CONFIRMED OR PARTIALLY CONFIRMED ", filtered_bid_ids)

            bids_which_transporter_has_been_assigned_to = (
                session
                .query(LoadAssigned)
                .filter(LoadAssigned.la_bidding_load_id.in_(filtered_bid_ids), LoadAssigned.la_transporter_id == transporter_id, LoadAssigned.is_active == True, LoadAssigned.is_assigned == True)
                .all()
            )

            if not bids_which_transporter_has_been_assigned_to:
                return ([], "")

            log("BIDS WHICH TRANSPORTER IS ASSIGNED TO ",
                bids_which_transporter_has_been_assigned_to)

            bid_ids = [str(bid.la_bidding_load_id)
                       for bid in bids_which_transporter_has_been_assigned_to]

            bids = (session
                    .query(BiddingLoad,
                           ShipperModel.shpr_id,
                           ShipperModel.name,
                           ShipperModel.contact_no,
                           func.array_agg(MapLoadSrcDestPair.src_city), func.array_agg(MapLoadSrcDestPair.src_street_address), func.array_agg(MapLoadSrcDestPair.src_state), func.array_agg(MapLoadSrcDestPair.dest_street_address), func.array_agg(MapLoadSrcDestPair.dest_state),
                           func.array_agg(MapLoadSrcDestPair.dest_city),
                           func.array_agg(select(func.count())
                                                            .where(
                                                                TrackingFleet.tf_transporter_id == transporter_id,
                                                                TrackingFleet.tf_bidding_load_id == BiddingLoad.bl_id,
                                                                TrackingFleet.is_active == True  
                                                            )
                                                            .correlate(BiddingLoad)
                                                            .subquery()
                                                        ).label('tf_vehicle_count')
                           )
                    .outerjoin(ShipperModel, ShipperModel.shpr_id == BiddingLoad.bl_shipper_id)
                    .outerjoin(MapLoadSrcDestPair, and_(MapLoadSrcDestPair.mlsdp_bidding_load_id == BiddingLoad.bl_id, MapLoadSrcDestPair.is_active == True))
                    .filter(BiddingLoad.is_active == True, BiddingLoad.bl_id.in_(bid_ids))
                    .group_by(BiddingLoad, *BiddingLoad.__table__.c, ShipperModel.name, ShipperModel.contact_no, ShipperModel.shpr_id )
                    .all()
                    )

            if not bids:
                return ([], "")

            log("ALL BIDS WHICH TRANSPORTER IS ASSIGNED TO ", bids)

            return (structurize_transporter_bids(bids=bids), "")

        except Exception as e:
            session.rollback()
            return ([], str(e))
        finally:
            session.close()

    async def position(self, transporter_id: str, bid_id: str) -> (any, str):
        try:
            session = Session()

            bid_details = session.execute(text(live_bid_details), params={
                "bid_id": bid_id})

            bid_summary = []
            for row in bid_details:
                bid_summary.append(row._mapping)

            if not bid_summary:
                return (None, "")

            log("BID SUMMARY", bid_summary)
            # sorted_bid_summary = sorted(bid_summary, key=lambda x: x['rate'])

            transporter_lowest_rate_bid_dict = {}
            for bid in bid_summary:

                id = bid.transporter_id
                if id in transporter_lowest_rate_bid_dict.keys():
                    if transporter_lowest_rate_bid_dict[id].rate > bid.rate:
                        transporter_lowest_rate_bid_dict[id] = bid

                if id not in transporter_lowest_rate_bid_dict.keys():
                    transporter_lowest_rate_bid_dict[id] = bid

            lowest_rate_bid_summary = [
                lowest_rate_bid_details for lowest_rate_bid_details in transporter_lowest_rate_bid_dict.values()]

            sorted_bid_summary = sorted(lowest_rate_bid_summary, key=lambda x: (
                x['rate'], x['created_at'].timestamp()))

            log("SORTED BID SUMMARY ", sorted_bid_summary)

            _position = 0

            for index, bid_detail in enumerate(sorted_bid_summary):
                if str(bid_detail.transporter_id) == str(transporter_id):
                    return (index, "")
            return (None, "")

        except Exception as e:
            session.rollback()
            return ({}, str(e))

        finally:
            session.close()

    async def assignment_history(self, transporter_id: str, bid_id: str) -> (any, str):

        session = Session()

        try:

            transporter_detail = (session.query(LoadAssigned).filter(LoadAssigned.la_bidding_load_id == bid_id,
                                  LoadAssigned.la_transporter_id == transporter_id, LoadAssigned.is_active == True).first())

            log("TRANSPORTER DETAILS", transporter_detail)
            if not transporter_detail:
                return ([], "")
            if not transporter_detail.history:
                return ([], "")

            log("ASSIGNMENT HISTORY", transporter_detail.history)
            log("TYPE", type(transporter_detail.history))

            assignment_history = ast.literal_eval(transporter_detail.history)[::-1]

            log("ASSIGNMENT HISTORY", assignment_history)
            log("TYPE", type(assignment_history))

            history = []

            for (event, resources, created_at, reason) in assignment_history:

                if event in (assignment_events["unassign"] ,assignment_events["assign"]):
                    history.append({
                        "event": event,
                        "resources": str(resources)+" vehicle(s)",
                        "created_at": created_at,
                        "reason": reason
                    })

            return (history, "")

        except Exception as err:
            session.rollback()
            return ([], str(err))

        finally:
            session.close()

    async def bid_match_approval(self, transporter_id: str, bid_id: str, req: any, user_id: str, authtoken: any) -> (any, str):

        session = Session()

        try:
            event = []
            approval_status = ""
            price_match_window_start_time=None

            ist_timezone = pytz.timezone("Asia/Kolkata")
            current_time = datetime.now(ist_timezone)
            current_time = current_time.replace(
                tzinfo=None, second=0, microsecond=0)

            transporter_detail = (session.query(LoadAssigned).filter(LoadAssigned.la_bidding_load_id == bid_id,
                                LoadAssigned.la_transporter_id == transporter_id, LoadAssigned.is_active == True).first())

            if not transporter_detail:
                return ([], "Transporter's Assigned Load Detail not Found")
            
            bid_details = (session.query(BiddingLoad).filter(BiddingLoad.bl_id == bid_id).first())
            if not bid_details:
                return([],"Bid Details Not Found ")
            
            bid_settings = (session
                            .query(BidSettings)
                            .filter(BidSettings.bdsttng_shipper_id == bid_details.bl_shipper_id, BidSettings.is_active, or_(BidSettings.bdsttng_branch_id == bid_details.bl_branch_id, BidSettings.bdsttng_branch_id.is_(None)))
                            .order_by(BidSettings.bdsttng_branch_id).limit(1)
                            .first()
                            )
            
            all_transporter_details = (session.query(LoadAssigned).filter(LoadAssigned.la_bidding_load_id == bid_id, LoadAssigned.is_active == True).all())
            
            for each_transporter_detail in all_transporter_details:

                if each_transporter_detail.is_negotiated_by_aculead == False and each_transporter_detail.pm_req_timestamp is not None:
                    if not price_match_window_start_time :
                        price_match_window_start_time = each_transporter_detail.pm_req_timestamp
                    else:
                        if price_match_window_start_time > each_transporter_detail.pm_req_timestamp:
                            price_match_window_start_time = each_transporter_detail.pm_req_timestamp
            
            
            if (current_time - price_match_window_start_time).total_seconds()/60 > bid_settings.price_match_duration :
                return(price_match_window_start_time + timedelta(minutes=bid_settings.price_match_duration), "Bid Match Approval Period is Over")

            if req.approval :
                event.append(assignment_events["pm-approved"])
                event.append(req.rate)
                event.append(str(current_time))
                event.append("Price Match Approved by Transporter")

                transporter_detail.is_negotiated_by_aculead = False
                transporter_detail.is_pmr_approved = True
                approval_status = "approved"

            else:
                event_detail = ''
                if transporter_detail.history:
                    event_details = ast.literal_eval(transporter_detail.history)[::-1]
                    event_detail = next ((event_detail for event_detail in event_details if event_detail[0] == assignment_events["pm-negotiated"]), None)

                if req.rate:
                    
                    lowest_rate_provided_by_transporter=-1
                    if event_detail:
                        lowest_rate_provided_by_transporter = event_detail[1]
                    else:
                        detail_of_lowest_bid_provided_by_transporter = (session
                                                                        .query(BidTransaction)
                                                                        .filter(BidTransaction.bid_id == bid_id, BidTransaction.transporter_id == transporter_id, BidTransaction.is_active == True, BidTransaction.rate > 0)
                                                                        .order_by(BidTransaction.rate.asc())
                                                                        .first()
                                                                        )
                        
                        if detail_of_lowest_bid_provided_by_transporter:
                            lowest_rate_provided_by_transporter = detail_of_lowest_bid_provided_by_transporter.rate
                    
                    if req.rate > lowest_rate_provided_by_transporter:
                        return(lowest_rate_provided_by_transporter,"rate greater than lowest rate negotiated")
                    
                    event.append(assignment_events["pm-negotiated"])
                    transporter_detail.pmr_price = req.rate
                    approval_status = "negotiated"
                else:
                    event.append(assignment_events["pm-rejected"])
                    approval_status = "rejected"
                    transporter_detail.pmr_price = event_detail[1] if event_detail else None

                event.append(req.rate)
                event.append(str(current_time))
                event.append(req.comment)

                transporter_detail.is_negotiated_by_aculead = False
                transporter_detail.is_pmr_approved = None
                transporter_detail.pmr_comment = req.comment
                transporter_detail.updated_at = current_time
                transporter_detail.updated_by = user_id

            if transporter_detail.history:
                fetched_history = ast.literal_eval(transporter_detail.history)
                fetched_history.append(tuple(event))
                transporter_detail.history = str(fetched_history)
                
            else:
                transporter_detail.history = str([(tuple(event))])

            session.commit()
                        
            (shipper_user_ids,error)  = await bid.shipper_users(bid_ids=[bid_id])
            if error:
                return ([], error)

            log("::: SHIPPER RELATED USERS ::: ", shipper_user_ids)
            
            (notification_response_success, error) = await notification_service_manager(authtoken=authtoken, req=NotificationServiceManagerReq(**{
                                                                                                                                                "receiver_ids": shipper_user_ids,
                                                                                                                                                "text":f"Transporter has responded to the PRICE MATCH REQUEST for L-{bid_id[-5:].upper()} ! GO AND CHECK IF ITS NEGOTIATED !!!",
                                                                                                                                                "type":"Transporter Bid Match Response",
                                                                                                                                                "deep_link":"manage_trip_partially_confirmed"
                                                                                                                                            }
                                                                                                                                            )
                                                                                    )
            
            print("::::: NOTIFICATION RESPONSE ::::",notification_response_success)
            if error:
                log("::: NOTIFICATION ERROR DURING BID PUBLISH ::: ",error)
                
            return (approval_status,"")

        except Exception as err:
            session.rollback()
            return ([], str(err))

        finally:
            session.close()

    async def tc_approval(self, transporter_id: str, bid_id: str, user_id: str) -> (any, str):
        session = Session()

        try:

            approval_data = BidTransaction(
                                        bid_id= bid_id,
                                        transporter_id= transporter_id,
                                        rate= -1,
                                        attempt_number= 0,
                                        is_tc_accepted= True,
                                        created_by= user_id
                                        )
            
            session.add(approval_data)
            session.commit()
            return (True,"")

        except Exception as err:
            session.rollback()
            return (False, str(err))

        finally:
            session.close()
