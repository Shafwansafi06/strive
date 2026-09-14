"""Smoke-test a running server over HTTP; STRIVE_API_TOKEN is optional locally."""
import json
import os
import urllib.request
import argparse


def main():
    p = argparse.ArgumentParser(); p.add_argument('--url', default='http://127.0.0.1:8000'); a = p.parse_args()
    def request(path, method='GET', body=None):
        headers = {'Content-Type':'application/json'}
        if os.getenv('STRIVE_API_TOKEN'): headers['Authorization'] = 'Bearer ' + os.environ['STRIVE_API_TOKEN']
        req = urllib.request.Request(a.url + path, method=method, headers=headers,
            data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(req, timeout=45) as r: return json.load(r)
    assert request('/health')['status'] == 'ok'
    result = request('/v1/demo/switch','POST',{'context':{'amount_inr':4000000}})
    key = result['call_id']
    try:
        assert len(result['events']) >= 3
        assert request(f'/v1/calls/{key}/transaction','POST')['status'] == 'held_mock'
        request(f'/v1/calls/{key}/verify','POST',{'method':'callback','confirmed':True})
        assert request(f'/v1/calls/{key}/transaction','POST')['status'] == 'executed_mock'
        print(json.dumps({'http_smoke':'PASS', 'windows':len(result['events']),'hold_verify_release':'PASS'}))
    finally: request(f'/v1/calls/{key}','DELETE')


if __name__ == '__main__': main()
