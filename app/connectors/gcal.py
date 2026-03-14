from typing import Dict, Any, List

class GCalConnector:
    def __init__(self, decrypted_creds: Dict[str, Any]):
        self.creds = decrypted_creds
        # self.service = build('calendar', 'v3', credentials=Credentials(**self.creds))

    async def check_availability(self, time_min: str, time_max: str) -> List[Dict[str, Any]]:
        return [{"status": "free", "time": time_min}]

    async def create_event(self, summary: str, start_time: str, end_time: str) -> Dict[str, Any]:
        # event = {"summary": summary, "start": {"dateTime": start_time}, ...}
        # return self.service.events().insert(calendarId='primary', body=event).execute()
        return {"status": "created", "event_id": "evt_abc"}
