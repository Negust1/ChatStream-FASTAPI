

class ChatbotException(Exception):
    def __init__(self, message: str, code: str = "chatbot_error_or_value_error"):
        self.message = message
        self.code = code
        super().__init__(message)


class UserNotFound(ChatbotException):
    def __init__(self, message: str = "User not found"):
        super().__init__(message, code="user_not_found")


class UserAlreadyExists(ChatbotException):
    def __init__(self, message: str = "User already exists"):
        super().__init__(message, code="user_already_exists")


class InvalidCredentials(ChatbotException):
    def __init__(self, message: str = "Invalid credentials"):
        super().__init__(message, code="invalid_credentials")


class SessionNotFound(ChatbotException):
    def __init__(self, message: str = "Session not found"):
        super().__init__(message, code="session_not_found")


class MessageLimitExceeded(ChatbotException):
    def __init__(self, message: str = "Message limit exceeded"):
        super().__init__(message, code="message_limit_exceeded")


class UnauthorizedAccess(ChatbotException):
    def __init__(self, message: str = "Unauthorized access"):
        super().__init__(message, code="unauthorized_access")
