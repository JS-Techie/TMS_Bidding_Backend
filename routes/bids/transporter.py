import json
import os
import pytz
from datetime import datetime
from fastapi import APIRouter, Request

from config.socket import manager
from data.bidding import valid_bid_status, valid_transporter_status
from schemas.bidding import TransporterBidReq, TransporterLostBidsReq, TransporterBidMatchApproval
from utils.bids.bidding import Bid
from utils.bids.shipper import Shipper
from utils.bids.transporters import Transporter
from utils.redis import Redis
from utils.response import ErrorResponse, ServerError, SuccessResponse
from utils.utilities import log

transporter_bidding_router: APIRouter = APIRouter(
    prefix="/transporter/bid", tags=["Transporter routes for bidding"])

transporter = Transporter()
bid = Bid()
shipper = Shipper()
redis = Redis()

shp, trns, acu = os.getenv("SHIPPER"), os.getenv(
    "TRANSPORTER"), os.getenv("ACULEAD")


@transporter_bidding_router.get("/status/{status}")
async def fetch_bids_for_transporter_by_status(request: Request, participated: bool | None=True, status: str | None = None):

    bid = Bid()
    transporter_id = request.state.current_user["transporter_id"]
    user_id = request.state.current_user["id"]
    (bids, error) = ([], "")

    try:

        if status not in valid_transporter_status:
            return ErrorResponse(data=[], dev_msg="Invalid status", client_msg=os.getenv("GENERIC_ERROR"))

        if not transporter_id:
            return ErrorResponse(data=[], dev_msg=os.getenv("TRANSPORTER_ID_NOT_FOUND_ERROR"), client_msg=os.getenv("GENERIC_ERROR"))

        if status == "assigned":
            (bids, error) = await transporter.assigned_bids(transporter_id=transporter_id, user_id= user_id)
        else:
            if status == "active":
                (bids, error) = await transporter.bids_by_status(transporter_id=transporter_id, user_id= user_id, status="not_started")
            else:
                (bids, error) = await transporter.bids_by_status(transporter_id=transporter_id, user_id= user_id, status=status)

        if error:
            return ErrorResponse(data=[], dev_msg=error, client_msg=os.getenv("GENERIC_ERROR"))

        updated_bids = None
        log("STATUS ", status)
        if status != "assigned":
            updated_private_bids = []
            updated_public_bids = []

            if status == "not_started":
                (bids_participated, error) = await transporter.participated_bids(transporter_id=transporter_id)

                filtered_private_bids = [
                    private_record for private_record in bids["private"]
                    if not any(participated_bid["bid_id"] == private_record["bid_id"] and participated_bid["load_status"] == "not_started" for participated_bid in bids_participated)
                ]

                filtered_public_bids = [
                    public_record for public_record in bids["public"]
                    if not any(participated_bid["bid_id"] == public_record["bid_id"] and participated_bid["load_status"] == "not_started" for participated_bid in bids_participated)
                ]

                bids["private"] = filtered_private_bids
                bids["public"] = filtered_public_bids

                
                (participated_shipper_of_bids, error) = await transporter.participated_bids_shipper(transporter_id= transporter_id)
                if error :
                    return ErrorResponse(data=[], dev_msg=error)

                private_bids_with_participated_shipper = [{**private_bid, "participated_for_shipper": 1} if private_bid["shipper_id"] in participated_shipper_of_bids 
                                                            else {**private_bid, "participated_for_shipper": 0} for private_bid in bids["private"]]

                public_bids_with_participated_shipper = [{**public_bid, "participated_for_shipper": 1} if public_bid["shipper_id"] in participated_shipper_of_bids 
                                                            else {**public_bid, "participated_for_shipper": 0} for public_bid in bids["public"]]

                bids["private"] = private_bids_with_participated_shipper
                bids["public"] = public_bids_with_participated_shipper


            elif status == "active":
                (bids_participated, error) = await transporter.participated_bids(transporter_id=transporter_id)

                filtered_private_bids = [
                    private_record for private_record in bids["private"]
                    if any(participated_bid["bid_id"] == private_record["bid_id"] and participated_bid["load_status"] == "not_started" for participated_bid in bids_participated)
                ]

                filtered_public_bids = [
                    public_record for public_record in bids["public"]
                    if any(participated_bid["bid_id"] == public_record["bid_id"] and participated_bid["load_status"] == "not_started" for participated_bid in bids_participated)
                ]

                bids["private"] = filtered_private_bids
                bids["public"] = filtered_public_bids
                log("BIDS PUBLIC :", bids["public"])
                
                # (participated_shipper_of_bids, error) = await transporter.participated_bids_shipper(transporter_id= transporter_id)
                # if error :
                #     return ErrorResponse(data=[], dev_msg=error)

                # private_bids_with_participated_shipper = [{**private_bid, "participated_for_shipper": 1} if private_bid["shipper_id"] in participated_shipper_of_bids 
                #                                             else {**private_bid, "participated_for_shipper": 0} for private_bid in bids["private"]]

                # public_bids_with_participated_shipper = [{**public_bid, "participated_for_shipper": 1} if public_bid["shipper_id"] in participated_shipper_of_bids 
                #                                             else {**public_bid, "participated_for_shipper": 0} for public_bid in bids["public"]]

                # bids["private"] = private_bids_with_participated_shipper
                # bids["public"] = public_bids_with_participated_shipper


            elif status == "live":
                (bids_participated, error) = await transporter.participated_bids(transporter_id=transporter_id)

                if participated:

                    filtered_private_bids = [
                        private_record for private_record in bids["private"]
                        if any(participated_bid["bid_id"] == private_record["bid_id"] and participated_bid["load_status"] == "live" for participated_bid in bids_participated)
                    ]

                    filtered_public_bids = [
                        public_record for public_record in bids["public"]
                        if any(participated_bid["bid_id"] == public_record["bid_id"] and participated_bid["load_status"] == "live" for participated_bid in bids_participated)
                    ]

                    bids["private"] = filtered_private_bids
                    bids["public"] = filtered_public_bids

                else:

                    filtered_private_bids = [
                        private_record for private_record in bids["private"]
                        if not any(participated_bid["bid_id"] == private_record["bid_id"] and participated_bid["load_status"] == "live" for participated_bid in bids_participated)
                    ]

                    filtered_public_bids = [
                        public_record for public_record in bids["public"]
                        if not any(participated_bid["bid_id"] == public_record["bid_id"] and participated_bid["load_status"] == "live" for participated_bid in bids_participated)
                    ]

                    bids["private"] = filtered_private_bids
                    bids["public"] = filtered_public_bids
                    
                    (participated_shipper_of_private_bids, error) = await transporter.participated_bids_shipper(transporter_id= transporter_id)
                    if error :
                        return ErrorResponse(data=[], dev_msg=error)
                    
                    (participated_shipper_of_public_bids, error) = await transporter.participated_bids_shipper(transporter_id= transporter_id)
                    if error :
                        return ErrorResponse(data=[], dev_msg=error)

                    private_bids_with_participated_shipper = [{**private_bid, "participated_for_shipper": 1} if private_bid["shipper_id"] in participated_shipper_of_private_bids 
                                                                else {**private_bid, "participated_for_shipper": 0} for private_bid in bids["private"]]

                    public_bids_with_participated_shipper = [{**public_bid, "participated_for_shipper": 1} if public_bid["shipper_id"] in participated_shipper_of_public_bids 
                                                                else {**public_bid, "participated_for_shipper": 0} for public_bid in bids["public"]]

                    bids["private"] = private_bids_with_participated_shipper
                    bids["public"] = public_bids_with_participated_shipper
                    
                    log("BIDS PUBLIC :", bids["public"])


            elif status == "pending":
                (bids_participated, error) = await transporter.participated_bids(transporter_id=transporter_id)

                filtered_private_bids = [
                    private_record for private_record in bids["private"]
                    if any(participated_bid["bid_id"] == private_record["bid_id"] and participated_bid["load_status"] in ["pending", "partially_confirmed"] for participated_bid in bids_participated)
                ]

                filtered_public_bids = [
                    public_record for public_record in bids["public"]
                    if any(participated_bid["bid_id"] == public_record["bid_id"] and participated_bid["load_status"] in ["pending", "partially_confirmed"] for participated_bid in bids_participated)
                ]

                bids["private"] = filtered_private_bids
                bids["public"] = filtered_public_bids


            for private_bid in bids["private"]:

                lowest_price_response = await lowest_price_of_bid_and_transporter(request=request, bid_id=private_bid["bid_id"])
                if lowest_price_response["data"] == []:
                    return lowest_price_response

                lowest_price_data = lowest_price_response["data"]
                updated_private_bids.append(
                    {**private_bid, **lowest_price_data})
                

            for public_bid in bids["public"]:

                lowest_price_response = await lowest_price_of_bid_and_transporter(request=request, bid_id=public_bid["bid_id"])
                if lowest_price_response["data"] == []:
                    return lowest_price_response

                lowest_price_data = lowest_price_response["data"]
                updated_public_bids.append({**public_bid, **lowest_price_data})

            private_bids_with_assigned_load_details = []
            public_bids_with_assigned_load_details = []

            (assigned_private_load_details, error) = await bid.assigned_load_details(bid_ids= [private_bid["bid_id"] for private_bid in updated_private_bids], transporter_id= transporter_id)
            if error:
                return ErrorResponse(data=[], client_msg="Something Went Wrong, Please Try Again Later", dev_msg=error)
            
            (assigned_public_load_details, error) = await bid.assigned_load_details(bid_ids= [public_bid["bid_id"] for public_bid in updated_public_bids], transporter_id= transporter_id)
            if error:
                return ErrorResponse(data=[], client_msg="Something Went Wrong, Please Try Again Later", dev_msg=error)

            for assigned_private_load_detail, updated_private_bid in zip(assigned_private_load_details, updated_private_bids):
                private_bids_with_assigned_load_details.append({**assigned_private_load_detail, ** updated_private_bid})

            for assigned_public_load_detail, updated_public_bid in zip(assigned_public_load_details, updated_public_bids):
                public_bids_with_assigned_load_details.append({**assigned_public_load_detail, ** updated_public_bid})

            updated_bids = {
                "all": private_bids_with_assigned_load_details+public_bids_with_assigned_load_details,
                "private": private_bids_with_assigned_load_details,
                "public": public_bids_with_assigned_load_details
            }
            sorted_bids = {
                "all":sorted(updated_bids["all"], key=lambda x: x['bid_time'], reverse=True),
                "private":sorted(updated_bids["private"], key=lambda x: x['bid_time'], reverse=True),
                "public":sorted(updated_bids["public"], key=lambda x: x['bid_time'], reverse=True)
            }


        else:

            updated_bids_with_lowest_price = []
            for each_bid in bids:

                lowest_price_response = await lowest_price_of_bid_and_transporter(request=request, bid_id=each_bid["bid_id"])
                if lowest_price_response["data"] == []:
                    return lowest_price_response

                lowest_price_data = lowest_price_response["data"]
                updated_bids_with_lowest_price.append({**each_bid, **lowest_price_data})

            updated_bids = []

            (assigned_load_details, error) = await bid.assigned_load_details(bid_ids= [bid["bid_id"] for bid in updated_bids_with_lowest_price], transporter_id= transporter_id)
            if error:
                return ErrorResponse(data=[], client_msg="Something Went Wrong, Please Try Again Later", dev_msg=error)
            
            for assigned_load_detail, updated_bid in zip(assigned_load_details, updated_bids_with_lowest_price):
                updated_bids.append({**assigned_load_detail, ** updated_bid})

            sorted_bids = sorted(updated_bids, key=lambda x: x['bid_time'], reverse=True)

        return SuccessResponse(data=sorted_bids, dev_msg="Fetched bids successfully", client_msg=f"Fetched all {status} bids successfully!")

    except Exception as err:
        return ServerError(err=err, errMsg=str(err))


@transporter_bidding_router.get("/selected")
async def fetch_selected_bids(request: Request):

    transporter_id = request.state.current_user["transporter_id"]

    try:

        if not transporter_id:
            return ErrorResponse(data=[], dev_msg=os.getenv("TRANSPORTER_ID_NOT_FOUND_ERROR"), client_msg=os.getenv("GENERIC_ERROR"))

        (bids, error) = await transporter.selected(transporter_id=transporter_id)

        if error:
            return ErrorResponse(data=[], dev_msg=error, client_msg=os.getenv("GENERIC_ERROR"))

        if not bids:
            return SuccessResponse(data=[], client_msg="You have not been selected in any bids yet", dev_msg="Not selected in any bids")

        updated_bids_with_lowest_price = []
        for each_bid in bids:

            lowest_price_response = await lowest_price_of_bid_and_transporter(request=request, bid_id=each_bid["bid_id"])
            if lowest_price_response["data"] == []:
                return lowest_price_response

            lowest_price_data = lowest_price_response["data"]
            updated_bids_with_lowest_price.append({**each_bid, **lowest_price_data})

        
        updated_bids = []

        (assigned_load_details, error) = await bid.assigned_load_details(bid_ids= [bid["bid_id"] for bid in updated_bids_with_lowest_price], transporter_id= transporter_id)
        if error:
            return ErrorResponse(data=[], client_msg="Something Went Wrong, Please Try Again Later", dev_msg=error)
        
        for assigned_load_detail, updated_bid in zip(assigned_load_details, updated_bids_with_lowest_price):
            updated_bids.append({**assigned_load_detail, ** updated_bid})

        sorted_bids = sorted(updated_bids, key=lambda x: x['bid_time'], reverse=True)

        return SuccessResponse(data=sorted_bids, dev_msg="Fetched bids successfully", client_msg="Fetched all selected bids successfully!")

    except Exception as err:
        return ServerError(err=err, errMsg=str(err))


@transporter_bidding_router.get("/completed")
async def fetch_completed_bids(request: Request):

    transporter_id = request.state.current_user["transporter_id"]
    bid=Bid()

    try:

        if not transporter_id:
            return ErrorResponse(data=[], dev_msg=os.getenv("TRANSPORTER_ID_NOT_FOUND_ERROR"), client_msg=os.getenv("GENERIC_ERROR"))

        (bids, error) = await transporter.completed(transporter_id=transporter_id)

        if error:
            return ErrorResponse(data=[], dev_msg=error, client_msg=os.getenv("GENERIC_ERROR"))

        if not bids:
            return SuccessResponse(data=[], client_msg="You dont have any completed bids yet", dev_msg="Not completed any bids")

        private_bids = []
        public_bids = []
        for each_bid in bids:

            lowest_price_response = await lowest_price_of_bid_and_transporter(request=request, bid_id=each_bid["bid_id"])
            if lowest_price_response["data"] == []:
                return lowest_price_response

            lowest_price_data = lowest_price_response["data"]
            
            if each_bid["bid_mode"] == "private_pool":
                private_bids.append({**each_bid, **lowest_price_data})
            else:
                public_bids.append({**each_bid, **lowest_price_data})

        
        private_bids_with_assigned_load_details = []
        public_bids_with_assigned_load_details = []

        (assigned_private_load_details, error) = await bid.assigned_load_details(bid_ids= [private_bid["bid_id"] for private_bid in private_bids], transporter_id= transporter_id)
        if error:
            return ErrorResponse(data=[], client_msg="Something Went Wrong, Please Try Again Later", dev_msg=error)
        
        (assigned_public_load_details, error) = await bid.assigned_load_details(bid_ids= [public_bid["bid_id"] for public_bid in public_bids], transporter_id= transporter_id)
        if error:
            return ErrorResponse(data=[], client_msg="Something Went Wrong, Please Try Again Later", dev_msg=error)

        for assigned_private_load_detail, private_bid in zip(assigned_private_load_details, private_bids):
            private_bids_with_assigned_load_details.append({**assigned_private_load_detail, ** private_bid})

        for assigned_public_load_detail, public_bid in zip(assigned_public_load_details, public_bids):
            public_bids_with_assigned_load_details.append({**assigned_public_load_detail, ** public_bid})

        updated_bids = {
            "all": private_bids_with_assigned_load_details+public_bids_with_assigned_load_details,
            "private": private_bids_with_assigned_load_details,
            "public": public_bids_with_assigned_load_details
        }

        sorted_bids = {
                "all":sorted(updated_bids["all"], key=lambda x: x['bid_time'], reverse=True),
                "private":sorted(updated_bids["private"], key=lambda x: x['bid_time'], reverse=True),
                "public":sorted(updated_bids["public"], key=lambda x: x['bid_time'], reverse=True)
            }

        return SuccessResponse(data=sorted_bids, dev_msg="Fetched bids successfully", client_msg="Fetched all completed bids successfully!")

    except Exception as err:
        return ServerError(err=err, errMsg=str(err))


@transporter_bidding_router.post("/rate/{bid_id}", response_model=None)
async def provide_new_rate_for_bid(request: Request, bid_id: str, bid_req: TransporterBidReq):

    transporter_id, user_id = request.state.current_user[
        "transporter_id"], request.state.current_user["id"]

    # user_id = os.getenv("USERID")

    try:

        if not transporter_id:
            return ErrorResponse(data=[], dev_msg=os.getenv("TRANSPORTER_ID_NOT_FOUND_ERROR"), client_msg=os.getenv("GENERIC_ERROR"))

        if bid_req.rate <= 0:
            return ErrorResponse(data=bid_req.rate, client_msg="Invalid Rate Entered, Rate Entered Must be Greater Than Zero", dev_msg="Rate must be greater than zero")

        log("BID REQUEST DETAILS", bid_req)

        (valid_bid_id, error) = await bid.is_valid(bid_id)

        log("BID IS VALID", bid_id)

        if not valid_bid_id:
            return ErrorResponse(data=bid_id, client_msg=os.getenv("NOT_FOUND_ERROR"), dev_msg=error)

        (error, bid_details) = await bid.details(bid_id)

        if not bid_details:
            return ErrorResponse(data=[], client_msg=os.getenv("BID_RATE_ERROR"), dev_msg=error)
        log("BID DETAILS LOAD STATUS", bid_details.load_status)

        ist_timezone = pytz.timezone("Asia/Kolkata")
        current_time = datetime.now(ist_timezone)
        current_time = current_time.replace(
            tzinfo=None, second=0, microsecond=0)

        log("THE CURRENT TIME DURING RATE :::: ", current_time)
        if bid_details.load_status not in valid_bid_status:
            if current_time < bid_details.bid_time and current_time < bid_details.bid_end_time:
                return ErrorResponse(data=[], client_msg=f"This Load is not Accepting Bids yet, the start time is {bid_details.bid_time}", dev_msg="Tried bidding, but bid is not live yet")

            elif current_time > bid_details.bid_time and current_time >= bid_details.bid_end_time:
                return ErrorResponse(data=[], client_msg=f"This Load is not Accepting Bids anymore, the end time was {bid_details.bid_end_time}", dev_msg="Tried bidding, but bid is not live anymore")
            
        if bid_details.load_status in valid_bid_status:
            if current_time >= bid_details.bid_end_time:
                return ErrorResponse(data=[], client_msg=f"This Load is not Accepting Bids anymore, the end time was {bid_details.bid_end_time}", dev_msg="Tried bidding, but bid is not live anymore")

        log("BID DETAILS FOUND", bid_id)

        if bid_details.bid_mode == "private_pool":
            log("REQUEST TRANSPORTER ID:", transporter_id)
            log("BID SHIPPER ID", bid_details.bl_shipper_id)
            (allowed_transporter_to_bid, error) = await transporter.allowed_to_bid(shipper_id=bid_details.bl_shipper_id, transporter_id=transporter_id)

            if not allowed_transporter_to_bid:
                return ErrorResponse(data=[], client_msg="Transporter Not Allowed to participate in the private Bid", dev_msg="bid is private, transporter not allowed")

        log("TRANSPORTER ALLOWED TO BID", bid_id)

        (transporter_attempts, error) = await transporter.attempts(
            bid_id=bid_id, transporter_id=transporter_id)

        if error:
            return ErrorResponse(data=[], client_msg=os.getenv("BID_RATE_ERROR"), dev_msg=error)

        if transporter_attempts >= bid_details.no_of_tries:
            return ErrorResponse(data=[], client_msg="You have exceeded the number of tries for this bid!", dev_msg=f"Number of tries for Bid  L-{bid_id[-5:].upper()} exceeded!")

        log("BID TRIES OK", bid_id)

        (rate, error) = await transporter.is_valid_bid_rate(bid_id=bid_id, show_rate_to_transporter=bid_details.show_current_lowest_rate_transporter,
                                                            rate=bid_req.rate, transporter_id=transporter_id, decrement=bid_details.bid_price_decrement,
                                                            is_decrement_in_percentage=bid_details.is_decrement_in_percentage , status=bid_details.load_status)

        log("RATE OBJECT", rate)

        if error:
            return ErrorResponse(data={}, dev_msg=error, client_msg=error)

        if not rate["valid"]:
            return ErrorResponse(data=[], client_msg=f"You entered an incorrect bid rate! Decrement is {bid_details.bid_price_decrement}", dev_msg="Incorrect bid price entered")

        log("VALID RATE", bid_id)

        (new_bid_transaction, error) = await bid.new(
            bid_id, transporter_id, bid_req.rate, bid_req.comment, bid_req.is_tc_accepted, user_id=user_id)

        log("NEW BID INSERTED", new_bid_transaction)

        if error:
            return ErrorResponse(data=[], dev_msg=error, client_msg=os.getenv("BID_RATE_ERROR"))

        (transporter_name, error) = await transporter.name(
            transporter_id=transporter_id)

        log("TRANSPORTER NAME", transporter_name)

        if error:
            return ErrorResponse(data=[], client_msg=os.getenv("BID_RATE_ERROR"), dev_msg=error)

        (sorted_bid_details, error) = await redis.update(sorted_set=bid_id,
                                                         transporter_id=transporter_id, comment=new_bid_transaction.comment, transporter_name=transporter_name, rate=bid_req.rate, attempts=transporter_attempts + 1)

        log("BID DETAILS", sorted_bid_details)

        await manager.broadcast(bid_id=bid_id, message=json.dumps(sorted_bid_details))

        log("SOCKET EVENT SENT", sorted_bid_details)

        return SuccessResponse(data=sorted_bid_details, dev_msg="Bid submitted successfully", client_msg=f"Bid for Bid  L-{bid_id[-5:].upper()} submitted!")

    except Exception as err:
        return ServerError(err=err, errMsg=str(err))

@transporter_bidding_router.post("/match/{bid_id}")
async def bid_match_for_transporter(request: Request, bid_id: str, req: TransporterBidMatchApproval):
    transporter_id = request.state.current_user["transporter_id"]
    user_id = request.state.current_user["id"]
    authtoken = request.headers.get("authorization", "")

    try:
        if not transporter_id:
            return ErrorResponse(data=[], dev_msg=os.getenv("TRANSPORTER_ID_NOT_FOUND_ERROR"), client_msg=os.getenv("GENERIC_ERROR"))

        (bid_match_result, error) = await transporter.bid_match_approval(transporter_id= transporter_id, bid_id= bid_id, req=req, user_id = user_id, authtoken = authtoken)

        if error :
            if error == "Bid Match Approval Period is Over":
                return ErrorResponse(data=[], client_msg=f"Bid Match Approval EXPIRED on {bid_match_result.strftime('%Y-%m-%d %I:%M:%S %p')}", dev_msg=error) 
            if error == "rate greater than lowest rate negotiated":
                return ErrorResponse(data=[], client_msg=f"Negotiating Rate Must Be Lesser than the Current Lowest Rate of {bid_match_result}", dev_msg=error)
            return ErrorResponse(data=[], client_msg="Something Went Wrong. Pls Try Again after Sometime", dev_msg=error)
        
        client_msg = ""
        if bid_match_result == "approved":
            client_msg = "Price Approved Successfully"
        elif bid_match_result == "negotiated":
            client_msg = "Price Match Rejected and Updated with a new rate Successfully"
        else:
            client_msg = "Price Match Rejection Successful"

        return SuccessResponse(data= [], client_msg=client_msg, dev_msg="price match approval updated")

    except Exception as err:
        return ServerError(err=err, errMsg=str(err))


@transporter_bidding_router.post("/lost")
async def fetch_lost_bids_for_transporter_based_on_participation(request: Request, t: TransporterLostBidsReq):

    transporter_id = request.state.current_user["transporter_id"]
    user_id = request.state.current_user["id"]

    try:
        if not transporter_id:
            return ErrorResponse(data=[], dev_msg=os.getenv("TRANSPORTER_ID_NOT_FOUND_ERROR"), client_msg=os.getenv("GENERIC_ERROR"))

        (bids, error) = ([], "")

        if t.particpated:
            (bids, error) = await transporter.participated_and_lost_bids(
                transporter_id=transporter_id)
        else:
            (bids, error) = await transporter.not_participated_and_lost_bids(
                transporter_id=transporter_id, user_id= user_id)

        if error:
            return ErrorResponse(data=[], dev_msg=error, client_msg="Something went wrong file fetching bids, please try again in some time")

        if not bids:
            return SuccessResponse(data=[], dev_msg="Not lost any bid", client_msg="No lost bids to show right now!")

        ist_timezone = pytz.timezone("Asia/Kolkata")
        current_time = datetime.now(ist_timezone)
        current_time = current_time.replace(tzinfo=None, second=0, microsecond=0)

        updated_bids = []
        for bid in bids:

            lowest_price_response = await lowest_price_of_bid_and_transporter(request=request, bid_id=bid["bid_id"], show_bid_lowest_price=True)
            if lowest_price_response["data"] == []:
                return lowest_price_response

            lowest_price_data = lowest_price_response["data"]
            bid_data_with_lowest_price = {**bid, **lowest_price_data}

            if current_time.day - bid_data_with_lowest_price["bid_end_time"].day < 7:
                bid_data_with_lowest_price["bid_lowest_price"] = None
            updated_bids.append(bid_data_with_lowest_price)
            

        sorted_bids = sorted(updated_bids, key=lambda x: x['bid_time'], reverse=True)

        return SuccessResponse(data=sorted_bids, dev_msg="Fetched lost bids successfully", client_msg="Fetched all lost bids successfully!")

    except Exception as err:
        return ServerError(err=err, errMsg=str(err))


@transporter_bidding_router.get("/lowest/{bid_id}")
async def lowest_price_of_bid_and_transporter(request: Request, bid_id: str, show_bid_lowest_price: bool | None = False):

    transporter_id = str(request.state.current_user["transporter_id"])
    log("TRANSPORTER DATA TYPE :", type(transporter_id))

    try:
        if not transporter_id:
            return ErrorResponse(data=[], dev_msg=os.getenv("TRANSPORTER_ID_NOT_FOUND_ERROR"), client_msg=os.getenv("GENERIC_ERROR"))

        (transporter_lowest_price, error) = await transporter.lowest_price(
            bid_id=bid_id, transporter_id=transporter_id)

        if error:
            return ErrorResponse(data=[], dev_msg=error, client_msg="Something went wrong file fetching lowest price of transporter, please try again in sometime!")

        log("FOUND TRANSPORTER LOWEST PRICE", transporter_lowest_price)

        (success, bid_details) = await bid.details(bid_id=bid_id)
        if not success:
            return ErrorResponse(data=[], dev_msg=error, client_msg="Something went wrong while fetching bid details for transporter, please try again in sometime!")

        (bid_lowest_price, error) = (None, None)

        if not show_bid_lowest_price:
            if bid_details.show_current_lowest_rate_transporter:
                (bid_lowest_price, error) = await bid.lowest_price(bid_id=bid_id)
        else:
            (bid_lowest_price, error) = await bid.lowest_price(bid_id=bid_id)

        if error:
            return ErrorResponse(data=[], dev_msg=error, client_msg="Something went wrong while fetching bid details for transporter, please try again in sometime!")

        log("FOUND BID LOWEST PRICE", bid_lowest_price)

        # transporter_position, error = redis.position(
        #     sorted_set=bid_id, key=transporter_id)

        # if error:
        #     return ErrorResponse(data=[], dev_msg=error, client_msg="Something went wrong file fetching bid details for transporter, please try again in sometime!")

        # if not transporter_position:
        (transporter_position, error) = await transporter.position(transporter_id=transporter_id, bid_id=bid_id)

        if error:
            return ErrorResponse(data=[], dev_msg=error, client_msg="Something went wrong file fetching bid details for transporter, please try again in sometime!")
        log("TRANSPORTER POSITION ", transporter_position)

        return SuccessResponse(data={
            "bid_lowest_price": bid_lowest_price if bid_lowest_price != float("inf") else None,
            "transporter_lowest_price": transporter_lowest_price if transporter_lowest_price != 0.0 else None,
            "position": transporter_position+1 if transporter_position != None else None,
            "no_of_tries": bid_details.no_of_tries
            # "transporter_rates": transporter_historical_rates
        }, dev_msg="Found all rates successfully", client_msg="Fetched lowest price of bid and transporter successfully")

    except Exception as err:
        return ServerError(err=err, errMsg=str(err))


@transporter_bidding_router.get("/details/{bid_id}")
async def fetch_details_needed_for_providing_rates(request: Request, bid_id: str):

    transporter_id = str(request.state.current_user["transporter_id"])

    try:

        lowest_price_response = await lowest_price_of_bid_and_transporter(request=request, bid_id=bid_id)
        if lowest_price_response["data"] == []:
            return lowest_price_response

        lowest_price_data = lowest_price_response["data"]

        (bid_details_found, details_for_assignment) = await bid.details_for_assignment(bid_id=bid_id, transporter_id=transporter_id)

        if not bid_details_found:
            return ErrorResponse(data=[], client_msg="Bid details were not found", dev_msg="Bid details for assignment could not be found")

        specific_details ={}
        if len(details_for_assignment) == 0:
            specific_details = {**lowest_price_data, "last_comment": None, "pending_tries": None}
        else:
            specific_details = {**lowest_price_data, **details_for_assignment[0], "pending_tries":lowest_price_data["no_of_tries"] - details_for_assignment[0]["total_number_attempts"]}

        return SuccessResponse(data=specific_details, client_msg='Necessary Details For Providing Rates are Fetched', dev_msg='Details Fetched')

        
    except Exception as err:
        return ServerError(err=err, errMsg=str(err))

@transporter_bidding_router.get("/approval/tc/{bid_id}")
async def terms_and_conditions_approval_before_bidding(request: Request, bid_id: str):

    transporter_id = str(request.state.current_user["transporter_id"])
    user_id = str(request.state.current_user["id"])

    try:

        (tc_approval_success, error) = await transporter.tc_approval(bid_id= bid_id, transporter_id= transporter_id, user_id= user_id)
        
        if not tc_approval_success:
            return ErrorResponse(data=[], dev_msg=error)
        
        return SuccessResponse(data=[], client_msg='Terms & Conditions Acceptance Successful', dev_msg='T&C accepted')

        
    except Exception as err:
        return ServerError(err=err, errMsg=str(err))
