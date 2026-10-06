"""Run focused tests and persist complete results independently of terminal logs."""
import argparse
import io
import json
from pathlib import Path
import sys
import time
import unittest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    started=time.perf_counter()
    repo=Path(__file__).resolve().parents[1]
    suite=unittest.defaultTestLoader.discover(str(repo/'backend/tests'))
    stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    report={'status':'complete','successful':result.wasSuccessful(),
            'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
            'skipped':len(result.skipped),'elapsed_seconds':round(time.perf_counter()-started,3),
            'failure_details':[{'test':str(test),'traceback':trace} for test,trace in result.failures+result.errors]}
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    args.output.with_suffix('.log').write_text(stream.getvalue())
    print(json.dumps(report))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    sys.exit(main())
