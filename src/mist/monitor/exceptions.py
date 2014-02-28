"""Custom exceptions used by mist"""


class MistError(Exception):
    """All custom mist exceptions should subclass this one.

    When printed, this class will always print its default message plus
    the message provided during exception initialization, if provided.

    """
    msg = "Mist Error"
    http_code = 500

    def __init__(self, msg=None):
        msg = "%s: %s" % (self.msg, msg) if msg else self.msg
        super(MistError, self).__init__(msg)


# BAD REQUESTS (translated as 400 in views)
class BadRequestError(MistError):
    msg = "Bad Request"
    http_code = 400


class RequiredParameterMissingError(BadRequestError):
    msg = "Required parameter not provided"


# UNAUTHORIZED (translated as 401 in views)
class UnauthorizedError(MistError):
    msg = "Not authorized"
    http_code = 401


# PAYMENT REQUIRED (translated as 402 in views)
class PaymentRequiredError(MistError):
    msg = "Payment required"
    http_code = 402


# FORBIDDEN (translated as 403 in views)
class ForbiddenError(MistError):
    msg = "Forbidden"
    http_code = 403


# NOT FOUND (translated as 404 in views)
class NotFoundError(MistError):
    msg = "Not Found"
    http_code = 404


class MachineNotFoundError(NotFoundError):
    msg = "Machine not found"


class RuleNotFoundError(NotFoundError, KeyError):
    msg = "Rule not found"


class ConditionNotFoundError(NotFoundError):
    msg = "Condition not found"


# NOT ALLOWED (translated as 405 in views)
class MethodNotAllowedError(MistError):
    msg = "Method Not Allowed"
    http_code = 405


# CONFLICT (translated as 409 in views)
class ConflictError(MistError):
    msg = "Conflict"
    http_code = 409


class MachineExistsError(ConflictError):
    msg = "Machine is already registered"


# INTERNAL ERROR (translated as 500 in views)
class InternalServerError(MistError):
    msg = "Internal Server Error"
    http_code = 500


class GraphiteError(InternalServerError):
    msg = "Error communicating with graphite"


# SERVICE UNAVAILABLE (translated as 503 in views)
class ServiceUnavailableError(MistError):
    msg = "Service unavailable"
    http_code = 503
