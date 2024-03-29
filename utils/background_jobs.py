from apscheduler.schedulers.background import BackgroundScheduler
from utils.bids.bidding import Bid
from config.scheduler import Scheduler

bid = Bid()
sched = Scheduler()


def schedule_jobs():
    scheduler = sched.new_scheduler()
    scheduler.add_job(func=bid.initiate, trigger="interval",
                      id="initiate-bid", minutes=1)
    scheduler.add_job(func=bid.close, trigger="interval",
                      id="close-bid", minutes=1)
    scheduler.add_job(func=bid.move_from_pending_to_cancelled, trigger="interval",
                      id="move-bid-from-pending-to-cancelled", minutes=30)
    sched.start(scheduler=scheduler)
