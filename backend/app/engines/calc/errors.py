class CalcInputError(ValueError):
    """계산 입력값 오류. field 로 어느 입력이 문제인지 알려준다."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")
