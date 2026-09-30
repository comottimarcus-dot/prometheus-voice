"""Read-only client for the documented X6 WebSocket capability query."""
import json
import re
import threading
import math
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4


class X6Unavailable(Exception):
    pass


def validate_camera(data, request_id):
    if (not isinstance(data, dict) or data.get('type') != 'x6_camera_capture_result'
            or data.get('request_id') != request_id or data.get('status') != 'DETECTED'
            or data.get('source') != 'zhengchen-cam' or data.get('detector') != 'x6-z800-yolo'
            or data.get('independently_verified') is not False or data.get('face_recognition_used') is not False):
        raise ValueError('Invalid camera result')
    rows=data.get('objects')
    if not isinstance(rows,list) or len(rows)>200: raise ValueError('Invalid objects')
    clean=[]
    for row in rows:
        name,count=row.get('label'),row.get('count')
        if (not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9 -]{1,40}',name)
                or type(count) is not int or not 1 <= count <= 200): raise ValueError('Invalid object')
        clean.append({'label':name,'count':count})
    if sum(row['count'] for row in clean)>200: raise ValueError('Invalid total')
    return {'status':'DETECTED','objects':clean,'independently_verified':False,'face_recognition_used':False}


def validate_sentinel(data, request_id):
    if (not isinstance(data, dict) or data.get('type') != 'x6_sentinel_result'
            or data.get('request_id') != request_id or data.get('status') != 'ok'
            or type(data.get('schema_version')) is not int or data['schema_version'] != 1
            or data.get('node') != 'sentinel-nm0' or data.get('source') != 'open-meteo'
            or any(data.get(key) is not False for key in
                   ('execution_authorized', 'node_identity_verified', 'source_transport_verified'))):
        raise ValueError('Invalid Sentinel result')
    updated = data.get('source_updated_at')
    if not isinstance(updated, str) or len(updated) > 40: raise ValueError('Invalid timestamp')
    stamp = datetime.fromisoformat(updated)
    age = data.get('source_age_seconds')
    if (stamp.tzinfo is None or not 0 <= (datetime.now(UTC)-stamp).total_seconds() <= 1200
            or type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age <= 1200):
        raise ValueError('Stale Sentinel result')
    cells, echoes, maximum = data.get('cells'), data.get('echoes'), data.get('max_precipitation_mm')
    if (type(cells) is not int or cells != 25 or type(echoes) is not int or not 0 <= echoes <= 25
            or type(maximum) not in (int, float) or not math.isfinite(maximum)
            or not 0 <= maximum <= 1000 or (echoes == 0) != (maximum == 0)):
        raise ValueError('Invalid grid')
    motion, bearing = data.get('motion'), data.get('bearing_deg')
    if motion not in ('waiting', 'no_echo', 'stationary', 'moving'): raise ValueError('Invalid motion')
    if motion == 'moving':
        if type(bearing) not in (int, float) or not math.isfinite(bearing) or not 0 <= bearing < 360:
            raise ValueError('Invalid bearing')
    elif bearing is not None: raise ValueError('Unexpected bearing')
    return {key: data[key] for key in ('status', 'node', 'source', 'source_updated_at',
        'source_age_seconds', 'cells', 'echoes', 'max_precipitation_mm', 'motion',
        'bearing_deg', 'execution_authorized', 'node_identity_verified', 'source_transport_verified')}


def validate_sentinel_air(data, request_id):
    if (not isinstance(data, dict) or data.get('type') != 'x6_sentinel_air_result'
            or data.get('request_id') != request_id or data.get('status') != 'ok'
            or type(data.get('schema_version')) is not int or data['schema_version'] != 1
            or data.get('node') != 'sentinel-nm0' or data.get('source') != 'adsb.fi'
            or data.get('scope') != 'filtered_display_targets'
            or any(data.get(key) is not False for key in
                   ('execution_authorized', 'node_identity_verified', 'source_transport_verified'))):
        raise ValueError('Invalid AIR result')
    count, age = data.get('targets'), data.get('fetch_age_seconds')
    if (type(count) is not int or not 0 <= count <= 40
            or type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age <= 45
            or type(data.get('range_nm')) is not int or data['range_nm'] != 25
            or type(data.get('display_limit')) is not int or data['display_limit'] != 40
            or data.get('limit_reached') is not (count == 40) or data.get('source_updated_at') is not None):
        raise ValueError('Invalid AIR count or freshness')
    return {key: data[key] for key in ('status', 'node', 'source', 'scope', 'targets', 'range_nm',
        'display_limit', 'limit_reached', 'fetch_age_seconds', 'source_updated_at',
        'execution_authorized', 'node_identity_verified', 'source_transport_verified')}


def validate_information(data, request_id):
    if (not isinstance(data, dict) or data.get('type') != 'x6_information_result'
            or data.get('request_id') != request_id or data.get('status') != 'ok'
            or type(data.get('schema_version')) is not int or data['schema_version'] != 1
            or data.get('provenance') != 'shadowbroker' or data.get('execution_authorized') is not False):
        raise ValueError('Invalid information')
    age, updated, stories = data.get('source_age_seconds'), data.get('source_updated_at'), data.get('stories')
    if type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age <= 900:
        raise ValueError('Invalid freshness')
    if not isinstance(updated, str) or len(updated) > 80:
        raise ValueError('Invalid timestamp')
    stamp = datetime.fromisoformat(updated.replace('Z', '+00:00'))
    if stamp.tzinfo is None or not 0 <= (datetime.now(UTC)-stamp).total_seconds() <= 900:
        raise ValueError('Stale information')
    if not isinstance(stories, list) or len(stories) > 3:
        raise ValueError('Invalid stories')
    clean = []
    for story in stories:
        if not isinstance(story, dict): raise ValueError('Invalid story')
        item = {}
        for key, limit in [('title', 300), ('source', 120), ('published', 80)]:
            value = story.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ValueError('Invalid field')
            item[key] = value.strip()
        link = story.get('link', '')
        if not isinstance(link, str) or len(link) > 1024: raise ValueError('Invalid link')
        url = urlsplit(link)
        item['link'] = link if (url.scheme in ('http', 'https') and url.hostname
            and not url.username and not url.password and not any(ord(c) < 33 for c in link)) else ''
        clean.append(item)
    return {'status': 'ok', 'provenance': 'shadowbroker', 'source_updated_at': updated,
            'source_age_seconds': age, 'stories': clean, 'execution_authorized': False}


def validate_snapshot(data, request_id):
    if (not isinstance(data, dict)
            or data.get('type') != 'x6_capabilities_result'
            or data.get('request_id') != request_id
            or data.get('status') != 'ok'
            or type(data.get('schema_version')) is not int
            or data['schema_version'] != 1
            or data.get('scope') != 'runtime_capability_registry'
            or data.get('execution_authorized') is not False
            or data.get('health_checked') is not False):
        raise ValueError('Invalid snapshot')
    entries = data.get('capabilities')
    if not isinstance(entries, list) or len(entries) > 128:
        raise ValueError('Invalid entries')
    clean, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Invalid entry')
        name, count = entry.get('name'), entry.get('registered_provider_count')
        if (not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', name)
                or name in seen or type(count) is not int or not 0 <= count <= 10000
                or entry.get('availability') != 'unknown'):
            raise ValueError('Invalid entry')
        seen.add(name)
        clean.append({'name': name, 'registered_provider_count': count, 'availability': 'unknown'})
    return {'status': 'ok', 'scope': 'runtime_capability_registry',
            'capabilities': clean, 'execution_authorized': False, 'health_checked': False}


class X6CapabilityClient:
    def __init__(self, *, enabled=False, connect=None):
        self.enabled = enabled
        self._connect = connect
        self._lock = threading.Lock()

    def snapshot(self):
        return self._query('capabilities', 'x6_capabilities', validate_snapshot, 3)

    def information(self):
        return self._query('information', 'x6_information', validate_information, 10)

    def sentinel(self):
        return self._query('sentinel', 'x6_sentinel', validate_sentinel, 3)

    def sentinel_air(self):
        return self._query('sentinel-air', 'x6_sentinel_air', validate_sentinel_air, 3)

    def camera_preview(self, *, clear=False):
        if not self.enabled: raise X6Unavailable('X6_NOT_ENABLED')
        try:
            import base64
            from websockets.sync.client import connect
            with connect('ws://127.0.0.1:8765/camera-preview',proxy=None,compression=None,
                         open_timeout=2,close_timeout=1,max_size=1500000,max_queue=1,ping_interval=None) as socket:
                socket.send(json.dumps({'action':'clear' if clear else 'read'}))
                data=json.loads(socket.recv(timeout=3))
                if data == {'jpeg':None}: return None
                if not isinstance(data,dict) or set(data)!={'jpeg'} or not isinstance(data['jpeg'],str): raise ValueError()
                photo=base64.b64decode(data['jpeg'],validate=True)
                if len(photo)>1024*1024 or not photo.startswith(b'\xff\xd8'): raise ValueError()
                return photo
        except Exception:
            raise X6Unavailable('X6_QUERY_UNAVAILABLE') from None

    def camera(self, request_id=None):
        return self._query('camera-capture', 'x6_camera_capture', validate_camera, 50, request_id=request_id)

    def _query(self, path, operation, validate, timeout, request_id=None):
        if not self.enabled:
            raise X6Unavailable('X6_NOT_ENABLED')
        if not self._lock.acquire(blocking=False):
            raise X6Unavailable('X6_QUERY_BUSY')
        try:
            connect = self._connect
            if connect is None:
                from websockets.sync.client import connect
            request_id = request_id or uuid4().hex
            # Fixed loopback destination, no proxy, no caller-controlled commands.
            with connect('ws://127.0.0.1:8765/' + path, proxy=None, compression=None,
                         open_timeout=2, close_timeout=1, max_size=32768,
                         max_queue=1, ping_interval=None) as socket:
                socket.send(json.dumps({'type': operation, 'request_id': request_id}))
                raw = socket.recv(timeout=timeout)
                if not isinstance(raw, str) or len(raw.encode('utf-8')) > 32768:
                    raise ValueError('Invalid frame')
                return validate(json.loads(raw), request_id)
        except Exception:
            raise X6Unavailable('X6_QUERY_UNAVAILABLE') from None
        finally:
            self._lock.release()
