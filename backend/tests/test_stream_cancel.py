"""Closing the progress stream stops its background search cooperatively."""
import asyncio
import os
from pathlib import Path
import sys
from threading import Event
import time
import unittest
from unittest.mock import patch

os.environ['MONGO_URI']='mongodb://localhost:1/?serverSelectionTimeoutMS=1'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from starlette.requests import Request
import api


class StreamCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnection_stops_background_search(self):
        stopped=Event()
        def slow_search(lat,lon,alt,inc,hours,trace):
            try:
                while True:
                    trace.update({'phase':'coarse_discovery'})
                    time.sleep(.01)
            finally:
                stopped.set()
        request=Request({'type':'http','method':'GET','path':'/safe-windows/stream','headers':[]})
        request.state.request_id='cancel-test'
        with patch.object(api,'_run_window_search',side_effect=slow_search):
            response=await api.safe_windows_stream(request,28.573,-80.649,420,51.6,1)
            iterator=response.body_iterator
            frame=await anext(iterator)
            self.assertIn('event: progress',frame)
            await iterator.aclose()
            self.assertTrue(await asyncio.to_thread(stopped.wait,2))
