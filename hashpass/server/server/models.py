from dataclasses import dataclass


@dataclass
class StudentScoreShort:
    username: str
    task_count: int
    max_task_num: int
    last_tstamp: float


@dataclass
class StudentRecord:
    username: str
    task_id: int
    tstamp: float
    IP: str
