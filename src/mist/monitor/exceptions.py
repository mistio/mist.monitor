"""Custom exceptions used by mist"""


class MistError(Exception):
    """All custom mist exceptions should subclass this one.

    When printed, this class will always print its default message plus
    the message provided during exception initialization, if provided.

    """
    msg = "Error"

    def __init__(self, msg=None):
        msg = "%s: %s" % (self.msg, msg) if msg is not None else self.msg
        super(MistError, self).__init__(msg)


# BAD REQUESTS (translated as 400 in views)
class BadRequestError(MistError):
    msg = "Bad Request"


class RequiredParameterMissingError(BadRequestError):
    msg = "Required parameter not provided"


# UNAUTHORIZED (translated as 401 in views)
class UnauthorizedError(MistError):
    msg = "Not authorized"


# NOT FOUND (translated as 404 in views)
class NotFoundError(MistError):
    msg = "Not Found"


class RuleNotFoundError(NotFoundError, KeyError):
    msg = "Rule not found"


class MachineNotFoundError(NotFoundError, KeyError):
    msg = "Machine not found"


# CONFLICT (translated as 409 in views)
class ConflictError(MistError):
    msg = "Conflict"


class MachineExistsError(ConflictError):
    msg = "Machine exists"


# INTERNAL ERROR (translated as 500 in views)
class InternalServerError(MistError):
    msg = "Internal Server Error"


# SERVICE UNAVAILABLE (translated as 503 in views)
class ServiceUnavailableError(MistError):
    msg = "Service unavailable"
