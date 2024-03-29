import os, math, copy
import datetime
from collections import Counter
from schemas.bidding import FilterBidsRequest, FilterBidsRequest
from models.models import BiddingLoad


def log(key: str, value: str | None = None):
    if os.getenv("print") == "true":
        print("-------------------------------------------------------------------------")
        print(key, " : ", value)
        print("=========================================================================")


def convert_date_to_string(date: datetime):

    return (str(date.year)+"-"+str(date.month)+"-"+str(date.day)+" "+str(date.hour)+":"+str(date.minute))


def structurize(input_array):
    result_dict = {}

    load_type_dict = {
        "private_pool": "Private Pool",
        "open_market": "Open Market",
        "indent": "Indent"
    }
    
    for item in input_array:
        bl_id = item["bl_id"]
        if bl_id not in result_dict:
            result_dict[bl_id] = {
                "bl_id": bl_id,
                "bid_time": item["bid_time"],
                "bid_end_time": item["bid_end_time"],
                "bid_extended_time": item["bid_extended_time"],
                "bid_mode": item["bid_mode"],
                "rate_quote_type": item["rate_quote_type"],
                "price_match_duration": item["price_match_duration"],
                "enable_price_match": item["enable_price_match"],
                "reporting_from_time": item["reporting_from_time"],
                "reporting_to_time": item["reporting_to_time"],
                "bl_cancellation_reason": item["bl_cancellation_reason"],
                "enable_tracking": item["enable_tracking"],
                "total_no_of_fleets": item["no_of_fleets"],
                "total_no_of_fleets_assigned":0,
                "pending_vehicle_count":item["no_of_fleets"],
                "fleet_type": item["fleet_type"],
                "fleet_name": item["fleet_name"],
                "shipper_id": item["bl_shipper_id"],
                "branch_id": item["bl_branch_id"],
                "shipper_name": item["shipper_name"],
                "branch_name": item["branch_name"],
                "bid_show": item["show_current_lowest_rate_transporter"],
                "load_type": load_type_dict[item["bid_mode"]],
                "prime_src_city": item["src_city"],
                "prime_dest_city": item["dest_city"],
                "src_cities": item["src_city"],
                "dest_cities": item["dest_city"],
                "no_of_bids_placed":item["total_no_of_bids"],
                "transporters_participated": item["participants"],
                "completion_reason":item["completion_reason"],
                "transporters": []  # Rename bid_items to transporters
            }
            if item["src_cities"]:
                
                address_data_arr = []
                for add, city, state in zip(item["src_street_addresses"], item["src_cities"], item["src_states"]):
                    address_data_arr.append(add+", "+city+", "+state)
                    
                result_dict[bl_id]["src_cities"] = ' | '.join(list(set(address_data_arr)))
                # log("SRC CITIES", item["src_cities"])
                # # result_dict[bl_id]["src_cities"]= ','.join(set(city for city in item["src_cities"] if city is not None))
                # result_dict[bl_id]["src_cities"]= [city for city in item["src_cities"] if city is not None]
                # src_city_list=copy.deepcopy(result_dict[bl_id]["src_cities"])
                # counter = Counter(src_city_list)
                # result_dict[bl_id]["src_cities"]= ', '.join(f"{key}({count})" if count > 1 else key for key, count in counter.items())
            if item["dest_cities"]:
                
                address_data_arr = []
                for add, city, state in zip(item["dest_street_addresses"], item["dest_cities"], item["dest_states"]):
                    address_data_arr.append(add+", "+city+", "+state)
                    
                result_dict[bl_id]["dest_cities"] = ' | '.join(list(set(address_data_arr)))
                
                # # result_dict[bl_id]["dest_cities"]= ','.join(set(city for city in item["dest_cities"] if city is not None))
                # result_dict[bl_id]["dest_cities"]= [city for city in item["dest_cities"] if city is not None]
                # dest_city_list=copy.deepcopy(result_dict[bl_id]["dest_cities"])
                # counter = Counter(dest_city_list)
                # result_dict[bl_id]["dest_cities"]= ', '.join(f"{key}({count})" if count > 1 else key for key, count in counter.items())
            

        bid_item = {
            "la_transporter_id": item["la_transporter_id"],
            "trans_pos_in_bid": item["trans_pos_in_bid"],
            "price": item["price"],
            "price_difference_percent": item["price_difference_percent"],
            "no_of_fleets_assigned": item["no_of_fleets_assigned"],
            "assignment_status": item["is_assigned"],
            "contact_name": item["name"],
            # "contact_name": item["contact_name"],
            "contact_no": item["contact_no"],
            "fleets": []  # Initialize an empty list for fleets
        }

        fleet_item = {
            "tf_id": item["tf_id"],
            "fleet_no": item["fleet_no"],
            "src_addrs": item["src_addrs"],
            "dest_addrs": item["dest_addrs"]
        }

        # Check if a transporter with the same la_transporter_id already exists
        existing_transporters = [
            transporter for transporter in result_dict[bl_id]["transporters"]
            if transporter["la_transporter_id"] == bid_item["la_transporter_id"]
        ]

        if existing_transporters:
            # If transporter exists, append the fleet to its fleets list
            existing_transporter = existing_transporters[0]
            if fleet_item not in existing_transporter["fleets"] and item["trf_active"]:
                existing_transporter["fleets"].append(fleet_item)
        else:
            # If transporter doesn't exist, add it along with the fleet
            if item["trf_active"]:
                bid_item["fleets"].append(fleet_item)
            if item["tr_active"] and item["la_active"]:
                result_dict[bl_id]["transporters"].append(bid_item)
                result_dict[bl_id]["total_no_of_fleets_assigned"]=result_dict[bl_id]["total_no_of_fleets_assigned"] + bid_item["no_of_fleets_assigned"]
                result_dict[bl_id]["pending_vehicle_count"]=result_dict[bl_id]["total_no_of_fleets"] - result_dict[bl_id]["total_no_of_fleets_assigned"]
    return list(result_dict.values())


def structurize_assignment_data(data):
    # Initialize a dictionary to organize data by transporter_id
    transporter_data = {}
    for entry in data:
        bid_details = entry["bid_details"]
        transporter_id = bid_details.transporter_id
        rate = bid_details.rate
        comment = bid_details.comment

        # Create or update the transporter entry
        if transporter_id not in transporter_data:
            transporter_data[transporter_id] = {
                "name": entry["transporter_name"],
                "id": transporter_id,
                "total_number_attempts": 0,
                "pmr_price": None,
                "assigned": None,
                "lowest_price": float('inf'),
                "last_comment": None,
                "rates": [],
                "fleet_assigned": None,
                "is_pmr_approved": None,
                "is_negotiated_by_aculead": None
            }

        transporter_entry = transporter_data[transporter_id]

        # Update total_number_attempts
        # transporter_entry["total_number_attempts"] += 1

        if rate < transporter_entry["lowest_price"]:
            transporter_entry["lowest_price"] = rate

        existing_entry = next(
            (item for item in transporter_entry["rates"] if item["rate"] == rate and item["comment"] == comment), None)
        # Add rate and comment to the rates array
        if not existing_entry:
            transporter_entry["rates"].append(
                {"rate": rate, "comment": comment})

        if not entry["load_assigned"]:
            transporter_entry["pmr_price"] = None
            transporter_entry["fleet_assigned"] = None
            transporter_entry["is_pmr_approved"] = None
            transporter_entry["is_negotiated_by_aculead"] = None

        elif transporter_id == entry["load_assigned"].la_transporter_id:
            transporter_entry["fleet_assigned"] = entry["load_assigned"].no_of_fleets_assigned
            transporter_entry["pmr_price"] = entry["load_assigned"].pmr_price
            transporter_entry["assigned"] = entry["load_assigned"].is_assigned
            transporter_entry["is_pmr_approved"] = entry["load_assigned"].is_pmr_approved
            transporter_entry["is_negotiated_by_aculead"] = entry["load_assigned"].is_negotiated_by_aculead

    # Sort the rates array for each transporter by rate
    for transporter_entry in transporter_data.values():
        transporter_entry["rates"].sort(key=lambda x: x["rate"])
        transporter_entry["last_comment"] = next((rate_comment["comment"] for rate_comment in transporter_entry["rates"] if rate_comment["comment"]), None)
        transporter_entry["total_number_attempts"] = len(
            transporter_entry["rates"])

    # Sort the final array by lowest_price
    sorted_transporter_data = []
    for transporter_entry in transporter_data.values():
        sorted_data_for_transporter = sorted(
            transporter_data.values(), key=lambda x: x["lowest_price"])
        if (sorted_data_for_transporter not in sorted_transporter_data):
            sorted_transporter_data.append(sorted_data_for_transporter)

    return sorted_transporter_data


def structurize_transporter_bids(bids):

    bid_details = []

    for bid_load, shipper_id, shipper_name, shipper_contact_no, src_city, src_street_address, src_state, dest_street_address, dest_state, dest_city, fleets_provided  in bids:
        log("BID_LOAD ", bid_load)
        log("SHIPPER ", shipper_name)
        log("SRC ", src_city)
        log("DEST ", dest_city)
        log("NO OF FLEETS PROVIDED ", fleets_provided)
        
        src_addresses = []
        dest_addresses = []
        for city, street, state in zip(src_city, src_street_address, src_state):
            src_addresses.append(street + " ," + city + " ," + state)
        
        for city, street, state in zip(dest_city, dest_street_address, dest_state):
            dest_addresses.append(street + " ," + city + " ," + state)
        
        bid_detail = {
            "bid_id": bid_load.bl_id,
            "branch_id": bid_load.bl_branch_id,
            "region_cluster_id":bid_load.bl_region_cluster_id,
            "shipper_name": shipper_name,
            "shipper_id": shipper_id,
            "contact_number": shipper_contact_no,
            "rate_qoute_type": bid_load.rate_quote_type,
            # "src_city": ','.join(set(city for city in src_city if city is not None)) if src_city else None,
            # "dest_city": ','.join(set(city for city in dest_city if city is not None)) if dest_city else None,
            "src_city": ' | '.join(list(set(src_addresses))),
            "dest_city": ' | '.join(list(set(dest_addresses))),
            "bid_time": bid_load.bid_time,
            "bid_end_time": bid_load.bid_end_time,
            "bid_extended_time": bid_load.bid_extended_time,
            "load_status": bid_load.load_status,
            "reporting_from_time":bid_load.reporting_from_time,
            "reporting_to_time":bid_load.reporting_to_time,
            "bid_mode": bid_load.bid_mode,
            "no_of_tries": bid_load.no_of_tries,
            "show_current_lowest_rate_transporter" : bid_load.show_current_lowest_rate_transporter,
            "completion_reason":bid_load.completion_reason,
            "no_of_fleets_assigned":0,
            "no_of_fleets_provided":set(fleets_provided).pop(),
            "pending_vehicles":0
        }
        

        bid_details.append(bid_detail)
    log("BID DETAILS", bid_details)
    return bid_details


def structurize_bidding_stats(bids):

    status_counters = {
        "confirmed": 0,
        "partially_confirmed": 0,
        "completed": 0,
        "cancelled": 0,
        "live": 0,
        "not_started": 0,
        "pending": 0
    }

    total = len(bids)

    log("TOTAL BIDS", total)

    for bid in bids:
        load_status = bid.load_status
        if load_status in status_counters:
            status_counters[load_status] += 1

    return {**status_counters, "total": total}


def add_filter(query: str, filter: FilterBidsRequest):

    if filter.shipper_id is not None:
        query = query.filter(BiddingLoad.bl_shipper_id == filter.shipper_id)
    if filter.rc_id is not None:
        query = query.filter(BiddingLoad.bl_region_cluster_id == filter.rc_id)
    if filter.branch_id is not None:
        query = query.filter(BiddingLoad.bl_branch_id == filter.branch_id)
    if filter.from_date is not None:
        query = query.filter(BiddingLoad.bid_time >= filter.from_date)
    if filter.to_date is not None:
        query = query.filter(BiddingLoad.bid_time <= filter.to_date)

    return query


def structurize_confirmed_cancelled_trip_trend_stats(bids, filter:FilterBidsRequest, type: str):

    from_datetime = filter.from_date
    to_datetime  = filter.to_date
    day_difference = (to_datetime-from_datetime).days+1
    datapoints =0 
    trip_trend = []
    counter_datetime= copy.copy(from_datetime)
    datapoints = {'day':(to_datetime-from_datetime).days+1, 'month':((to_datetime.year-from_datetime.year)*12+(to_datetime.month-from_datetime.month))+1, 'year':(to_datetime.year-from_datetime.year)+1}.get(type, None)
    
    for _ in range(datapoints):
        
        if type == 'day':            
            trip_trend.append({
                'x-axis-label':str(counter_datetime.day)+"-"+str(counter_datetime.month)+"-"+str(counter_datetime.year),
                'confirmed':0,
                'cancelled':0
            })
            counter_datetime+=datetime.timedelta(days=1)
                
        elif type == 'month':
            trip_trend.append({
                'x-axis-label':str(counter_datetime.month)+"-"+str(counter_datetime.year),
                'confirmed':0,
                'cancelled':0
            })
            counter_datetime+=datetime.timedelta(days=30)
                
        elif type == 'year':
            trip_trend.append({
                'x-axis-label':counter_datetime.year,
                'confirmed':0,
                'cancelled':0
            })
            counter_datetime+=datetime.timedelta(days=365)
        
        
        
    for bid in bids:
        date_created= bid.created_at
        status = bid.load_status
        
        if type== 'day':
            for record in trip_trend:
                if (str(date_created.day)+"-"+str(date_created.month)+"-"+str(date_created.year)) == record['x-axis-label']:
                    record[status]+=1
                    
        elif type== 'month':
            for record in trip_trend:
                if (str(date_created.month)+"-"+str(date_created.year)) == record['x-axis-label']:
                    record[status]+=1
                    
        if type== 'year':
            for record in trip_trend:
                if (date_created.year) == record['x-axis-label']:
                    record[status]+=1

    return trip_trend