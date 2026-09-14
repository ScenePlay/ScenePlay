"""Path builders replacing url_for(). Static assets keep their Flask paths."""
import socket

import core.config as config


def static_url(filename, external=False):
    path = '/static/' + filename.lstrip('/')
    return (lan_base() + path) if external else path


def _local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()


def lan_base():
    """http://<this box on the LAN>:<port> — the base other devices (OBS,
    the relay's asset fetch, phones scanning a QR) reach this server at.
    The operator override `obs_card_base` wins when set."""
    try:
        from sql import appsettingGet
        base = (appsettingGet('obs_card_base', '') or '').strip().rstrip('/')
        if base:
            return base
    except Exception:
        pass
    return f'http://{_local_ip()}:{config.PORT}'
