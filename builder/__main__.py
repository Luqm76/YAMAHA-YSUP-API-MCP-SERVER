import argparse
import threading
import webbrowser
import json
from urllib.request import build_opener, ProxyHandler
from urllib.error import URLError

import uvicorn

from .api import create_app

parser=argparse.ArgumentParser()
parser.add_argument('--port',type=int,default=8765)
parser.add_argument('--open',action='store_true')
args=parser.parse_args()
if args.open:
    url=f'http://127.0.0.1:{args.port}'
    try:
        with build_opener(ProxyHandler({})).open(url+'/api/health',timeout=2) as response:
            running=json.load(response).get('application')=='yamaha-program-builder'
    except (URLError,TimeoutError,ValueError):running=False
    if running:
        webbrowser.open(url)
        raise SystemExit(0)
    threading.Timer(1.5,lambda:webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
uvicorn.run(create_app(),host='127.0.0.1',port=args.port)
