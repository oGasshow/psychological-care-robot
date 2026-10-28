"""Safe public exceptions. Never retain input values or validator context."""
class OutboxError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

class InputValidationError(OutboxError):
    def __init__(self, details):
        self.details = details
        super().__init__('validation_error')
