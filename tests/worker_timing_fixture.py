"""Small child solely for worker-lifetime telemetry tests."""
import json,time
buffer=bytearray(1024*1024)
print(json.dumps(dict(phase='fixture-start')),flush=True)
time.sleep(.2)
print(json.dumps(dict(phase='fixture-end')),flush=True)
