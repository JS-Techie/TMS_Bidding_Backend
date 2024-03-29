import time

from config.redis import r as redis
from utils.utilities import log


class Redis:

    async def update(self, sorted_set: str, transporter_id: str, transporter_name: str, comment: str, rate: float, attempts: int) -> (any, str):

        log("TRANSPORTER ID", transporter_id)
        log("TRANSPORTER NAME", transporter_name)
        log("COMMENT", comment)
        log("RATE", rate)
        log("NUMBER OF ATTEMPTS", attempts)

        current_timestamp = int(time.time())

        # key = f"{transporter_id}_{current_timestamp}"

        rate = rate + current_timestamp / (10**10)
        log("RATE APPENDED WITH TIMESTAMP", rate)
        redis.hmset(transporter_id, {
            'transporter_id': transporter_id,
            'transporter_name': transporter_name,
            'comment': comment,
            'attempts': attempts
        })

        log("HASHING IN REDIS", "OK")

        redis.zadd(sorted_set, {transporter_id: rate})

        # redis.zadd(sorted_set, {transporter_id: (rate, current_timestamp)})

        log("SORTED SET APPEND IN REDIS", "OK")

        return await self.bid_details(sorted_set=sorted_set)

    async def bid_details(self, sorted_set: str) -> (any, str):

        log("FETCHING BID DETAILS FROM REDIS")

        try:

            transporter_data_with_rates = []

            transporter_ids = self.get_all(sorted_set=sorted_set)

            log("TRANSPORTER IDS", transporter_ids)

            for transporter_id in transporter_ids:
                rate = int(redis.zscore(sorted_set, transporter_id))
                log("TRANSPORTER DETAILS", {
                    "TRANSPORTER_ID": transporter_id, "RATE": rate})
                transporter_data = redis.hgetall(transporter_id)

                log("TRANSPORTER DETAILS BEFORE RATE", transporter_data)

                transporter_data['rate'] = rate
                log("TRANSPORTER DETAILS AFTER RATE", transporter_data)

                transporter_data_with_rates.append(transporter_data)

            log("LIVE BID RESULTS", transporter_data_with_rates)

            return (transporter_data_with_rates, "")

        except Exception as e:
            return ([], str(e))

    async def get_first(self, sorted_set: str):
        log("FETCHING LOWEST PRICE FROM REDIS")
        transporter_id = redis.zrange(sorted_set, 0, 0)[0]
        return (redis.zscore(sorted_set, transporter_id), "")

    async def get_last(self, sorted_set: str):
        return redis.zrevrange(sorted_set, 0, 0)

    async def get_first_n(self, sorted_set: str, n: int):
        return redis.zrange(sorted_set, 0, n)

    async def get_last_n(self, sorted_set: str, n: int):
        return redis.zrevrange(sorted_set, 0, n)

    def get_all(self, sorted_set: str):
        log("ALL RECORDS IN SORTED SET")
        return redis.zrange(sorted_set, 0, -1)

    async def exists(self, sorted_set: str, key: str) -> bool:
        if not redis.zscore(sorted_set, key):
            return False
        return True

    def delete(self, sorted_set: str):
        transporters = self.get_all(sorted_set=sorted_set)

        log("TRANSPORTERS TO DELETE",transporters)

        if not transporters:
            return
        
        for transporter in transporters:
            log("TRANSPORTER ID",transporter)
            redis.delete(transporter)
            redis.zrem(sorted_set,transporter)
        

    def position(self, sorted_set: str, key: str) -> (any, str):

        try:
            return (redis.zrank(name=sorted_set, value=key, withscore=False), "")
        except Exception as e:
            return ({}, str(e))
