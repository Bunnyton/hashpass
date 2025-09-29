import random 

class DBConnector:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def add_record(self, username: str, task_number: int) -> bool:
        return random.choice([True, False])
