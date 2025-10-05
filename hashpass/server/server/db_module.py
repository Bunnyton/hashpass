import sqlite3
import time
from models import StudentRecord, StudentScoreShort


class DBConnector:
    def __init__(self, db_path: str):
        self.db_path: str = db_path
        self._init_db()
    
    def _init_db(self) -> None:
        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        # IP нужен для хоть какой-то отсечки 2х студентов с логином "vasya"
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS Students (
        `record_id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        `username` TEXT NOT NULL,
        `ip_address` TEXT NOT NULL,
        `task_id` INTEGER NOT NULL,
        `tstamp` timestamp NOT NULL
        )
        ''')        
        connection.commit()
        connection.close()
    
    def is_record_exists(self, username: str, task_number: int,
                         ip_address: str) -> bool:
        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        cursor.execute('''
        SELECT `tstamp` FROM Students WHERE
        `username` = ? AND `task_id` = ? AND `ip_address` = ?
        ''', (username, task_number, ip_address))
        
        result: bool = bool(cursor.fetchone())
        connection.close()
        return result
    
    def add_record(self, username: str, task_number: int,
                   ip_address: str) -> bool:
        if self.is_record_exists(username, task_number, ip_address):
            return False # Дубликат
        
        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        cursor.execute('''
        INSERT INTO Students (`username`, `task_id`, `tstamp`, `ip_address`) 
        VALUES (?, ?, ?, ?)''', 
                              (username, task_number, time.time(),ip_address))
        connection.commit()
        connection.close()
        return True
    
    def get_students_score_detailed(self) -> list[StudentRecord]:
        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        cursor.execute('''
        SELECT `username`, `task_id`, `tstamp`, `ip_address` 
        FROM Students ORDER BY tstamp
        ''')
        result: list[StudentRecord] = [StudentRecord(username=i[0],
                                                     task_id=i[1],
                                                     tstamp=i[2],
                                                     IP=i[3]
                                                     ) for i in cursor.fetchall()]
        connection.close()
        return result
    
    def get_students_score_short(self) -> list[StudentScoreShort]:
        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        cursor.execute('''
        SELECT `username`, count(`task_id`), max(`task_id`), max(`tstamp`)
        FROM Students GROUP BY `username` ORDER BY `tstamp`
        ''')
        result: list[StudentScoreShort] = [StudentScoreShort(username=i[0], 
                                                             task_count=i[1],
                                                             max_task_num=i[2],
                                                             last_tstamp=i[3]
                                                             ) 
                                           for i in cursor.fetchall()]
        connection.close()
        return result        
    
    


if __name__ == "__main__":
    con = DBConnector("storage/students.sqlite")
    print(con.get_students_score_detailed())
    '''
c=con.connection.cursor()
c.execute("drop table Students")
con.connection.commit()
    '''
    
