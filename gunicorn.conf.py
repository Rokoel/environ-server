import multiprocessing

bind = "127.0.0.1:8000"
workers = 6
worker_class = "sync"
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
