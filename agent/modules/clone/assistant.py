"""Validate session structure without login or untrusted outbound connections."""
import ipaddress

# Only production Telegram IPv4 DC networks; reject arbitrary session endpoints.
NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    '149.154.160.0/20', '91.108.4.0/22', '91.108.8.0/22',
    '91.108.12.0/22', '91.108.16.0/22', '91.108.20.0/22', '91.108.56.0/22',
))


def validate_session(value):
    if not isinstance(value, str) or not 300 <= len(value) <= 512 or not value.startswith('1'):
        raise ValueError('A production Telethon StringSession is required.')
    from telethon.sessions import StringSession
    session = StringSession(value)
    address = ipaddress.ip_address(session.server_address)
    if (session.dc_id not in range(1, 6) or session.port != 443
            or not any(address in network for network in NETWORKS)
            or session.auth_key is None):
        raise ValueError('Only production Telegram IPv4 sessions on port 443 are supported.')
    return value
