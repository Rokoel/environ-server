"""Keep query-string credentials out of Werkzeug access logs."""
import logging
import re


class QueryStringFilter(logging.Filter):
    # Match the request target in standard HTTP request-line log messages.
    request_target = re.compile(r'(\b[A-Z]+ [^\s?]+)\?[^\s]*(?= HTTP/[0-9.]+)')

    def filter(self, record):
        message = record.getMessage()
        redacted = self.request_target.sub(r'\1', message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True
