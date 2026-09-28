"""Platform error types. HTTP mapping happens in the API layer."""


class PlatformError(Exception):
    code = "platform_error"
    status_code = 500

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class ConfigError(PlatformError):
    code = "config_error"
    status_code = 400


class UnknownProviderError(ConfigError):
    code = "unknown_provider"


class ProviderNotImplementedError(PlatformError):
    code = "provider_not_implemented"
    status_code = 501


class SecretResolutionError(ConfigError):
    code = "secret_resolution_error"


class OverlayDeniedError(ConfigError):
    code = "overlay_denied"
    status_code = 403


class UnauthenticatedError(PlatformError):
    code = "unauthenticated"
    status_code = 401


class ForbiddenError(PlatformError):
    code = "forbidden"
    status_code = 403


class NotFoundError(PlatformError):
    code = "not_found"
    status_code = 404


class ConflictError(PlatformError):
    code = "conflict"
    status_code = 409


class ValidationFailedError(PlatformError):
    code = "validation_error"
    status_code = 422


class RateLimitedError(PlatformError):
    code = "rate_limited"
    status_code = 429


class BudgetExceededError(PlatformError):
    code = "budget_exceeded"
    status_code = 402


class ConnectorError(PlatformError):
    code = "connector_error"
    status_code = 502


class ConnectorAuthExpiredError(ConnectorError):
    code = "CONNECTOR_AUTH_EXPIRED"
    status_code = 401


class ConnectorRateLimitedError(ConnectorError):
    code = "CONNECTOR_RATE_LIMITED"
    status_code = 429
