import multiprocessing

bind = "127.0.0.1:5000"
workers = 6
worker_class = "sync"
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50

# Log paths only: callback query strings contain Telegram login credentials.
# Exclude Referer too, since it can contain a callback URL.
accesslog = "-"
access_log_format = '%(h)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s'
