from typing import Dict, Any
import os
from src.tools.data_access import DataAccess
from src.telemetry.logger import logger


class DBTool:
    """Wrapper exposing simple student info query for agent tools."""

    def __init__(self, db_path: str = 'gradebook.db', csv_dir: str = None):
        # prefer sqlite if exists
        if os.path.exists(db_path):
            self.da = DataAccess(db_path=db_path)
            logger.log_event('DBTOOL_INIT', {'backend': 'sqlite', 'path': db_path})
        else:
            self.da = DataAccess(csv_dir=csv_dir or './my-pfio')
            logger.log_event('DBTOOL_INIT', {'backend': 'csv', 'csv_dir': csv_dir})

    def get_student_info(self, student_id: str) -> Dict[str, Any]:
        student = self.da.get_student(student_id)
        submissions = self.da.get_submissions(student_id)
        # basic aggregates
        records = []
        try:
            records = self.da.list_students() if False else []
        except Exception:
            records = []

        res = {
            'student': student,
            'submissions': submissions,
            'summary': {
                'num_submissions': len(submissions or []),
            }
        }
        logger.log_event('DBTOOL_QUERY', {'student_id': student_id, 'found': bool(student)})
        return res


db_tool = DBTool()
