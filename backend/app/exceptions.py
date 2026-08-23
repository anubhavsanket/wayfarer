from fastapi import HTTPException, status

class WayfarerError(Exception):
    """Base class for all Wayfarer domain exceptions."""
    def __init__(self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        self.message = message
        self.status_code = status_code
        super().__init__(message)

class ResumeNotFoundError(WayfarerError):
    def __init__(self, resume_id: str):
        super().__init__(f"Resume {resume_id} not found", status.HTTP_404_NOT_FOUND)

class ResumeValidationError(WayfarerError):
    def __init__(self, message: str):
        super().__init__(message, status.HTTP_400_BAD_REQUEST)

class RedisUnavailableError(WayfarerError):
    def __init__(self):
        super().__init__("Redis unavailable", status.HTTP_503_SERVICE_UNAVAILABLE)
